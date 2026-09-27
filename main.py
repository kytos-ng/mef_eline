# pylint: disable=protected-access, too-many-lines
"""Main module of kytos/mef_eline Kytos Network Application.

NApp to provision circuits from user request.
"""
import pathlib
import time
import traceback
from collections import defaultdict
from contextlib import ExitStack
from copy import deepcopy
from threading import Lock
from typing import Optional

from jsonschema.exceptions import ValidationError as OpenapiValidationError
from openapi_schema_validator import validate
from pydantic import ValidationError

from kytos.core import KytosNApp, log, rest
from kytos.core.common import EntityStatus
from kytos.core.events import KytosEvent
from kytos.core.exceptions import KytosNoTagAvailableError, KytosTagError
from kytos.core.helpers import (alisten_to, listen_to, load_spec, now,
                                validate_openapi)
from kytos.core.interface import TAG, UNI, TAGRange
from kytos.core.link import Link
from kytos.core.rest_api import (HTTPException, JSONResponse, Request,
                                 get_json_or_400)
from kytos.core.tag_ranges import get_tag_ranges
from napps.kytos.mef_eline import controllers, settings
from napps.kytos.mef_eline.exceptions import (ActivationError, DisabledSwitch,
                                              DuplicatedNoTagUNI,
                                              FlowModException, InvalidPath)
from napps.kytos.mef_eline.models import (EVC, DynamicPathManager, EVCDeploy,
                                          Path)
from napps.kytos.mef_eline.scheduler import CircuitSchedule, Scheduler
from napps.kytos.mef_eline.utils import (_does_uni_affect_evc, aemit_event,
                                         emit_event, get_vlan_tags_and_masks,
                                         map_evc_event_content,
                                         merge_flow_dicts, prepare_delete_flow,
                                         send_flow_mods_http)


# pylint: disable=too-many-public-methods
class Main(KytosNApp):
    """Main class of amlight/mef_eline NApp.

    This class is the entry point for this napp.
    """

    allowed_default_keys = {
        "primary_constraints": 'PathConstraints',
        "secondary_constraints": 'PathConstraints'
    }
    spec = load_spec(pathlib.Path(__file__).parent / "openapi.yml")

    def setup(self):
        """Replace the '__init__' method for the KytosNApp subclass.

        The setup method is automatically called by the controller when your
        application is loaded.

        So, if you have any setup routine, insert it here.
        """
        # object used to scheduler circuit events
        self.sched = Scheduler()

        # EVC default values
        self.default_values = {}
        self.load_default_evc_values(
            settings.EVC_DEFAULT, self.allowed_default_keys
        )

        # object to save and load circuits
        self.mongo_controller = self.get_eline_controller()
        self.mongo_controller.bootstrap_indexes()

        # set the controller that will manager the dynamic paths
        DynamicPathManager.set_controller(self.controller)

        # dictionary of EVCs created. It acts as a circuit buffer.
        # Every create/update/delete must be synced to mongodb.
        self.circuits = dict[str, EVC]()

        self._intf_events = defaultdict(dict)
        self._lock_interfaces = defaultdict(Lock)
        self.table_group = {"epl": 0, "evpl": 0}
        self._lock = Lock()
        self.multi_evc_lock = Lock()
        self.execute_as_loop(settings.DEPLOY_EVCS_INTERVAL)

        self.load_all_evcs()
        self._topology_updated_at = None

    def load_default_evc_values(
        self,
        defaul_values: dict,
        allowed_default_keys: dict
    ):
        """Load default EVC values from settings."""
        dynamic_schema = {
            "openapi": self.spec["openapi"],
            "components": self.spec['components'],
            "$ref": ""
        }
        for key, value in defaul_values.items():
            if key not in allowed_default_keys:
                raise ValueError(f"Invalid {key} is not allowed.")
            schema = allowed_default_keys[key]
            dynamic_schema["$ref"] = f"#/components/schemas/{schema}"
            try:
                validate(value, dynamic_schema)
                self.default_values[key] = value
            except OpenapiValidationError as err:
                msg = f"Invalid {key} with error: {err.message}"
                raise ValueError(msg) from err

    def get_evcs_by_svc_level(self, enable_filter: bool = True) -> list[EVC]:
        """Get circuits sorted by desc service level and asc creation_time.

        In the future, as more ops are offloaded it should be get from the DB.
        """
        if enable_filter:
            return sorted(
                          [circuit for circuit in self.circuits.values()
                           if circuit.is_enabled()],
                          key=lambda x: (-x.service_level, x.creation_time),
            )
        return sorted(self.circuits.values(),
                      key=lambda x: (-x.service_level, x.creation_time))

    @staticmethod
    def get_eline_controller():
        """Return the ELineController instance."""
        return controllers.ELineController()

    def execute(self):
        """Execute once when the napp is running."""
        if self._lock.locked():
            return
        log.debug("Starting consistency routine")
        with self._lock:
            self.execute_consistency()
        log.debug("Finished consistency routine")

    def should_be_checked(self, circuit):
        "Verify if the circuit meets the necessary conditions to be checked"
        # pylint: disable=too-many-boolean-expressions
        if (
                circuit.is_enabled()
                and not circuit.is_active()
                and not circuit.lock.locked()
                and not circuit.has_recent_removed_flow()
                and not circuit.is_recent_updated()
                and circuit.are_unis_active()
                # if a inter-switch EVC does not have current_path, it does not
                # make sense to run sdntrace on it
                and (circuit.is_intra_switch()
                     or circuit.current_path.is_deployed())
                ):
            return True
        return False

    def execute_consistency(self):
        """Execute consistency routine.

        An EVC inactive on its kept configured paths, with none UP and no
        dynamic backup, isn't checked: nothing can carry it, and a redeploy
        would only tear down the paths kept for its fast resume (EP041).
        """
        circuits_to_check = []
        for circuit in self.get_evcs_by_svc_level(enable_filter=False):
            if self.should_be_checked(circuit) and not (
                circuit.is_inactive_on_static()
                and not circuit.dynamic_backup_path
                and not circuit.get_reactivation_path()
            ):
                circuits_to_check.append(circuit)
            if circuit.is_active() and (
                (not circuit.failover_path
                 and circuit.is_eligible_for_failover_path())
                or circuit.needs_static_standby()
            ):
                emit_event(
                    self.controller,
                    "need_failover",
                    content=map_evc_event_content(circuit)
                )
        traced = {
            circuit.id: circuit.current_path for circuit in circuits_to_check
        }
        circuits_checked = EVCDeploy.check_list_traces(circuits_to_check)
        for circuit in circuits_to_check:
            is_checked = circuits_checked.get(circuit.id)
            with circuit.lock:
                # a link event may have changed it while it was traced
                if (circuit.is_active()
                        or circuit.current_path is not traced[circuit.id]):
                    continue
                if is_checked:
                    if (circuit.current_path
                            and circuit.current_path.status
                            != EntityStatus.UP):
                        continue
                    circuit.execution_rounds = 0
                    log.info(f"{circuit} enabled but inactive - activating")
                    circuit.activate()
                    circuit.sync()
                else:
                    circuit.execution_rounds += 1
                    if circuit.execution_rounds > settings.WAIT_FOR_OLD_PATH:
                        log.info(f"{circuit} enabled but inactive - redeploy")
                        circuit.deploy()

    # pylint: disable=too-many-branches
    def resume_on_static(self, evcs: list[EVC]) -> list[EVC]:
        """Resume inactive EVCs on an UP configured path, primary preferred,
        installing it first if needed, with only the UNI ingress (EP041)."""
        targets = {evc.id: evc.get_reactivation_path() for evc in evcs}
        installed, failed = self.execute_install_standby(
            [(evc, targets[evc.id]) for evc in evcs]
        )
        install_flows, done = {}, {}
        for evc in installed:
            try:
                install_flow = evc._prepare_uni_flows(
                    targets[evc.id], skip_out=True
                )
            except Exception:
                log.error(f"Fail to prepare {evc} ingress: "
                          f"{traceback.format_exc()}")
                install_flow = {}
            if install_flow:
                done[evc.id] = (evc, install_flow)
                install_flows = merge_flow_dicts(
                    install_flows, deepcopy(install_flow)
                )
            else:
                failed.append(evc)
        if done:
            try:
                send_flow_mods_http(install_flows, "install")
            except FlowModException as exc:
                log.error(f"Fail to install the ingress of {evcs}: {exc}")
                failed.extend(evc for evc, _ in done.values())
                done = {}

        detached = []
        for evc, _ in done.values():
            old_current, evc.current_path = evc.current_path, targets[evc.id]
            evc.activate()
            evc.execution_rounds = 0
            if old_current.is_deployed() and not any(
                old_current is path
                for path in (evc.primary_path, evc.backup_path)
            ):
                detached.append((evc, old_current))
        resumed = [evc for evc, _ in done.values()]
        if resumed:
            log.info(f"Resumed {resumed} on a configured path")
            emit_event(
                self.controller, "static.ingress_installed", content={
                    evc.id: map_evc_event_content(
                        evc,
                        flows=deepcopy(install_flow),
                        removed_flows={},
                        current_path=evc.current_path.as_dict(),
                    )
                    for evc, install_flow in done.values()
                }
            )
        if detached:
            self.execute_clear_paths(detached)
        for evc in resumed:
            self.request_failover_path(evc)
        if failed:
            log.error(f"Failed to resume {failed} on a configured path")
        if installed:
            self.mongo_controller.update_evcs(
                [evc.as_dict() for evc in installed]
            )
        return resumed

    def request_failover_path(self, evc: EVC) -> None:
        """Ask for a failover path right away for an active EVC that is
        eligible and has none, instead of waiting for the consistency
        routine to notice it (EP041)."""
        if (evc.is_active() and not evc.failover_path
                and evc.is_eligible_for_failover_path()):
            emit_event(
                self.controller, "need_failover",
                content=map_evc_event_content(evc)
            )

    def shutdown(self):
        """Execute when your napp is unloaded.

        If you have some cleanup procedure, insert it here.
        """

    @rest("/v2/evc/", methods=["GET"])
    def list_circuits(self, request: Request) -> JSONResponse:
        """Endpoint to return circuits stored.

        archive query arg if defined (not null) will be filtered
        accordingly, by default only non archived evcs will be listed
        """
        log.debug("list_circuits /v2/evc")
        args = request.query_params
        archived = args.get("archived", "false").lower()
        args = {k: v for k, v in args.items() if k not in {"archived"}}
        circuits = self.mongo_controller.get_circuits(archived=archived,
                                                      metadata=args)
        circuits = circuits['circuits']
        return JSONResponse(circuits)

    @rest("/v2/evc/schedule", methods=["GET"])
    def list_schedules(self, _request: Request) -> JSONResponse:
        """Endpoint to return all schedules stored for all circuits.

        Return a JSON with the following template:
        [{"schedule_id": <schedule_id>,
         "circuit_id": <circuit_id>,
         "schedule": <schedule object>}]
        """
        log.debug("list_schedules /v2/evc/schedule")
        circuits = self.mongo_controller.get_circuits()['circuits'].values()
        if not circuits:
            result = {}
            status = 200
            return JSONResponse(result, status_code=status)

        result = []
        status = 200
        for circuit in circuits:
            circuit_scheduler = circuit.get("circuit_scheduler")
            if circuit_scheduler:
                for scheduler in circuit_scheduler:
                    value = {
                        "schedule_id": scheduler.get("id"),
                        "circuit_id": circuit.get("id"),
                        "schedule": scheduler,
                    }
                    result.append(value)

        log.debug("list_schedules result %s %s", result, status)
        return JSONResponse(result, status_code=status)

    @rest("/v2/evc/{circuit_id}", methods=["GET"])
    def get_circuit(self, request: Request) -> JSONResponse:
        """Endpoint to return a circuit based on id."""
        circuit_id = request.path_params["circuit_id"]
        log.debug("get_circuit /v2/evc/%s", circuit_id)
        circuit = self.mongo_controller.get_circuit(circuit_id)
        if not circuit:
            result = f"circuit_id {circuit_id} not found"
            log.debug("get_circuit result %s %s", result, 404)
            raise HTTPException(404, detail=result)
        status = 200
        log.debug("get_circuit result %s %s", circuit, status)
        return JSONResponse(circuit, status_code=status)

    # pylint: disable=too-many-branches, too-many-statements
    @rest("/v2/evc/", methods=["POST"])
    @validate_openapi(spec)
    def create_circuit(self, request: Request) -> JSONResponse:
        """Try to create a new circuit.

        Firstly, for EVPL: E-Line NApp verifies if UNI_A's requested C-VID and
        UNI_Z's requested C-VID are available from the interfaces' pools. This
        is checked when creating the UNI object.

        Then, E-Line NApp requests a primary and a backup path to the
        Pathfinder NApp using the attributes primary_links and backup_links
        submitted via REST

        # For each link composing paths in #3:
        #  - E-Line NApp requests a S-VID available from the link VLAN pool.
        #  - Using the S-VID obtained, generate abstract flow entries to be
        #    sent to FlowManager

        Push abstract flow entries to FlowManager and FlowManager pushes
        OpenFlow entries to datapaths

        E-Line NApp generates an event to notify all Kytos NApps of a new EVC
        creation

        Finnaly, notify user of the status of its request.
        """
        # Try to create the circuit object
        log.debug("create_circuit /v2/evc/")
        data = get_json_or_400(request, self.controller.loop)

        try:
            evc = self._evc_from_dict(data, created=True)
        except (ValueError, KytosTagError) as exception:
            log.debug("create_circuit result %s %s", exception, 400)
            raise HTTPException(400, detail=str(exception)) from exception
        if evc.primary_path:
            try:
                evc.primary_path.is_valid(
                    evc.uni_a.interface.switch,
                    evc.uni_z.interface.switch,
                    bool(evc.circuit_scheduler),
                )
            except InvalidPath as exception:
                raise HTTPException(
                    400,
                    detail=f"primary_path is not valid: {exception}"
                ) from exception
        if evc.backup_path:
            try:
                evc.backup_path.is_valid(
                    evc.uni_a.interface.switch,
                    evc.uni_z.interface.switch,
                    bool(evc.circuit_scheduler),
                )
            except InvalidPath as exception:
                raise HTTPException(
                    400,
                    detail=f"backup_path is not valid: {exception}"
                ) from exception

        if not evc._tag_lists_equal():
            detail = "UNI_A and UNI_Z tag lists should be the same."
            raise HTTPException(400, detail=detail)

        try:
            evc._validate_has_primary_or_dynamic()
        except ValueError as exception:
            raise HTTPException(400, detail=str(exception)) from exception

        try:
            evc._validate_static_paths()
        except ValueError as exception:
            raise HTTPException(400, detail=str(exception)) from exception

        try:
            self._check_no_tag_duplication(evc.id, evc.uni_a, evc.uni_z)
        except DuplicatedNoTagUNI as exception:
            log.debug("create_circuit result %s %s", exception, 409)
            raise HTTPException(409, detail=str(exception)) from exception

        try:
            self._use_uni_tags(evc)
        except KytosTagError as exception:
            raise HTTPException(400, detail=str(exception)) from exception

        # save circuit
        try:
            evc.sync()
        except ValidationError as exception:
            raise HTTPException(400, detail=str(exception)) from exception

        # store circuit in dictionary
        self.circuits[evc.id] = evc

        # Schedule the circuit deploy
        self.sched.add(evc)

        # Circuit has no schedule, deploy now
        deployed = False
        if not evc.circuit_scheduler:
            with evc.lock:
                deployed = evc.deploy()

        # Notify users
        result = {"circuit_id": evc.id, "deployed": deployed}
        status = 201
        log.debug("create_circuit result %s %s", result, status)
        emit_event(self.controller, name="created",
                   content=map_evc_event_content(evc))
        return JSONResponse(result, status_code=status)

    @staticmethod
    def _use_uni_tags(evc):
        uni_a = evc.uni_a
        evc._use_uni_vlan(uni_a)
        try:
            uni_z = evc.uni_z
            evc._use_uni_vlan(uni_z)
        except KytosTagError as err:
            evc.make_uni_vlan_available(uni_a)
            raise err

    @listen_to('kytos/flow_manager.flow.removed')
    def on_flow_delete(self, event):
        """Capture delete messages to keep track when flows got removed."""
        self.handle_flow_delete(event)

    def handle_flow_delete(self, event):
        """Keep track when the EVC got flows removed by deriving its cookie."""
        flow = event.content["flow"]
        evc = self.circuits.get(EVC.get_id_from_cookie(flow.cookie))
        if evc:
            log.debug("Flow removed in EVC %s", evc.id)
            evc.set_flow_removed_at()

    @rest("/v2/evc/{circuit_id}", methods=["PATCH"])
    @validate_openapi(spec)
    def update(self, request: Request) -> JSONResponse:
        """Update a circuit based on payload.

        The EVC attributes (creation_time, active, current_path,
        failover_path, _id, archived) can't be updated.
        """
        data = get_json_or_400(request, self.controller.loop)
        circuit_id = request.path_params["circuit_id"]
        log.debug("update /v2/evc/%s", circuit_id)
        try:
            evc = self.circuits[circuit_id]
        except KeyError:
            result = f"circuit_id {circuit_id} not found"
            log.debug("update result %s %s", result, 404)
            raise HTTPException(404, detail=result) from KeyError

        with evc.lock:
            try:
                updated_data = self._evc_dict_with_instances(data)
                self._check_no_tag_duplication(
                    circuit_id, updated_data.get("uni_a"),
                    updated_data.get("uni_z")
                )
                enable, redeploy = evc.update(**updated_data)
            except (ValueError, KytosTagError, ValidationError) as exception:
                log.debug("update result %s %s", exception, 400)
                raise HTTPException(400, detail=str(exception)) from exception
            except DuplicatedNoTagUNI as exception:
                log.debug("update result %s %s", exception, 409)
                raise HTTPException(409, detail=str(exception)) from exception
            except DisabledSwitch as exception:
                log.debug("update result %s %s", exception, 409)
                raise HTTPException(
                        409,
                        detail=f"Path is not valid: {exception}"
                    ) from exception
            redeployed = False
            if evc.is_active():
                if enable is False:  # disable if active
                    evc.remove()
                elif redeploy is not None:  # redeploy if active
                    evc.remove()
                    redeployed = evc.deploy()
            else:
                if enable is True:  # enable if inactive
                    redeployed = evc.deploy()
                elif enable is False and evc.current_path:
                    # inactive EVC still holding flows
                    evc.remove()
                elif evc.is_enabled() and redeploy:
                    evc.remove()
                    redeployed = evc.deploy()
            result = {evc.id: evc.as_dict(), 'redeployed': redeployed}
            status = 200

        log.debug("update result %s %s", result, status)
        emit_event(self.controller, "updated",
                   content=map_evc_event_content(evc, **data))
        return JSONResponse(result, status_code=status)

    @rest("/v2/evc/{circuit_id}", methods=["DELETE"])
    def delete_circuit(self, request: Request) -> JSONResponse:
        """Remove a circuit.

        First, the flows are removed from the switches, and then the EVC is
        disabled.
        """
        circuit_id = request.path_params["circuit_id"]
        log.debug("delete_circuit /v2/evc/%s", circuit_id)
        try:
            evc = self.circuits.pop(circuit_id)
        except KeyError:
            result = f"circuit_id {circuit_id} not found"
            log.debug("delete_circuit result %s %s", result, 404)
            raise HTTPException(404, detail=result) from KeyError
        log.info("Removing %s", evc)

        with evc.lock:
            if not evc.archived:
                evc.deactivate()
                evc.disable()
                self.sched.remove(evc)
                evc.remove_static_standby_flows()
                evc.remove_current_flows(sync=False)
                evc.remove_failover_flows(sync=False)
                evc.archive()
                evc.remove_uni_tags()
                evc.sync()
                emit_event(
                    self.controller, "deleted",
                    content=map_evc_event_content(evc)
                )

        log.info("EVC removed. %s", evc)
        result = {"response": f"Circuit {circuit_id} removed"}
        status = 200
        log.debug("delete_circuit result %s %s", result, status)

        return JSONResponse(result, status_code=status)

    @rest("/v2/evc/{circuit_id}/metadata", methods=["GET"])
    def get_metadata(self, request: Request) -> JSONResponse:
        """Get metadata from an EVC."""
        circuit_id = request.path_params["circuit_id"]
        try:
            return (
                JSONResponse({"metadata": self.circuits[circuit_id].metadata})
            )
        except KeyError as error:
            raise HTTPException(
                404,
                detail=f"circuit_id {circuit_id} not found."
            ) from error

    @rest("/v2/evc/metadata", methods=["POST"])
    @validate_openapi(spec)
    def bulk_add_metadata(self, request: Request) -> JSONResponse:
        """Add metadata to a bulk of EVCs."""
        data = get_json_or_400(request, self.controller.loop)
        circuit_ids = data.pop("circuit_ids")

        self.mongo_controller.update_evcs_metadata(circuit_ids, data, "add")

        fail_evcs = []
        for _id in circuit_ids:
            try:
                evc = self.circuits[_id]
                evc.extend_metadata(data)
            except KeyError:
                fail_evcs.append(_id)

        if fail_evcs:
            raise HTTPException(404, detail=fail_evcs)
        return JSONResponse("Operation successful", status_code=201)

    @rest("/v2/evc/{circuit_id}/metadata", methods=["POST"])
    @validate_openapi(spec)
    def add_metadata(self, request: Request) -> JSONResponse:
        """Add metadata to an EVC."""
        circuit_id = request.path_params["circuit_id"]
        metadata = get_json_or_400(request, self.controller.loop)
        if not isinstance(metadata, dict):
            raise HTTPException(400, f"Invalid metadata value: {metadata}")
        try:
            evc = self.circuits[circuit_id]
        except KeyError as error:
            raise HTTPException(
                404,
                detail=f"circuit_id {circuit_id} not found."
            ) from error

        evc.extend_metadata(metadata)
        evc.sync()
        return JSONResponse("Operation successful", status_code=201)

    @rest("/v2/evc/metadata/{key}", methods=["DELETE"])
    @validate_openapi(spec)
    def bulk_delete_metadata(self, request: Request) -> JSONResponse:
        """Delete metada from a bulk of EVCs"""
        data = get_json_or_400(request, self.controller.loop)
        key = request.path_params["key"]
        circuit_ids = data.pop("circuit_ids")
        self.mongo_controller.update_evcs_metadata(
            circuit_ids, {key: ""}, "del"
        )

        fail_evcs = []
        for _id in circuit_ids:
            try:
                evc = self.circuits[_id]
                evc.remove_metadata(key)
            except KeyError:
                fail_evcs.append(_id)

        if fail_evcs:
            raise HTTPException(404, detail=fail_evcs)
        return JSONResponse("Operation successful")

    @rest("/v2/evc/{circuit_id}/metadata/{key}", methods=["DELETE"])
    def delete_metadata(self, request: Request) -> JSONResponse:
        """Delete metadata from an EVC."""
        circuit_id = request.path_params["circuit_id"]
        key = request.path_params["key"]
        try:
            evc = self.circuits[circuit_id]
        except KeyError as error:
            raise HTTPException(
                404,
                detail=f"circuit_id {circuit_id} not found."
            ) from error

        evc.remove_metadata(key)
        evc.sync()
        return JSONResponse("Operation successful")

    @rest("/v2/evc/{circuit_id}/redeploy", methods=["PATCH"])
    def redeploy(self, request: Request) -> JSONResponse:
        """Endpoint to force the redeployment of an EVC."""
        circuit_id = request.path_params["circuit_id"]
        try_avoid_same_s_vlan = request.query_params.get(
            "try_avoid_same_s_vlan", "true"
        )
        try_avoid_same_s_vlan = try_avoid_same_s_vlan.lower()
        if try_avoid_same_s_vlan not in {"true", "false"}:
            msg = "Parameter try_avoid_same_s_vlan has an invalid value."
            raise HTTPException(400, detail=msg)
        log.debug("redeploy /v2/evc/%s/redeploy", circuit_id)
        try:
            evc = self.circuits[circuit_id]
        except KeyError:
            raise HTTPException(
                404,
                detail=f"circuit_id {circuit_id} not found"
            ) from KeyError
        deployed = False
        with evc.lock:
            if evc.is_enabled():
                evc.remove_static_standby_flows()
                path_dict = evc.remove_current_flows(
                    sync=False,
                    return_path=try_avoid_same_s_vlan == "true"
                )
                evc.remove_failover_flows(sync=True)
                deployed = evc.deploy(path_dict)
        if deployed:
            result = {"response": f"Circuit {circuit_id} redeploy received."}
            status = 202
        else:
            result = {
                "response": f"Circuit {circuit_id} is disabled."
            }
            status = 409

        return JSONResponse(result, status_code=status)

    @rest("/v2/evc/schedule/", methods=["POST"])
    @validate_openapi(spec)
    def create_schedule(self, request: Request) -> JSONResponse:
        """
        Create a new schedule for a given circuit.

        This service do no check if there are conflicts with another schedule.
        Payload example:
            {
              "circuit_id":"aa:bb:cc",
              "schedule": {
                "date": "2019-08-07T14:52:10.967Z",
                "interval": "string",
                "frequency": "1 * * * *",
                "action": "create"
              }
            }
        """
        log.debug("create_schedule /v2/evc/schedule/")
        data = get_json_or_400(request, self.controller.loop)
        circuit_id = data["circuit_id"]
        schedule_data = data["schedule"]

        # Get EVC from circuits buffer
        circuits = self._get_circuits_buffer()

        # get the circuit
        evc = circuits.get(circuit_id)

        # get the circuit
        if not evc:
            result = f"circuit_id {circuit_id} not found"
            log.debug("create_schedule result %s %s", result, 404)
            raise HTTPException(404, detail=result)

        # new schedule from dict
        new_schedule = CircuitSchedule.from_dict(schedule_data)

        # If there is no schedule, create the list
        if not evc.circuit_scheduler:
            evc.circuit_scheduler = []

        # Add the new schedule
        evc.circuit_scheduler.append(new_schedule)

        # Add schedule job
        self.sched.add_circuit_job(evc, new_schedule)

        # save circuit to mongodb
        evc.sync()

        result = new_schedule.as_dict()
        status = 201

        log.debug("create_schedule result %s %s", result, status)
        return JSONResponse(result, status_code=status)

    @rest("/v2/evc/schedule/{schedule_id}", methods=["PATCH"])
    @validate_openapi(spec)
    def update_schedule(self, request: Request) -> JSONResponse:
        """Update a schedule.

        Change all attributes from the given schedule from a EVC circuit.
        The schedule ID is preserved as default.
        Payload example:
            {
              "date": "2019-08-07T14:52:10.967Z",
              "interval": "string",
              "frequency": "1 * * *",
              "action": "create"
            }
        """
        data = get_json_or_400(request, self.controller.loop)
        schedule_id = request.path_params["schedule_id"]
        log.debug("update_schedule /v2/evc/schedule/%s", schedule_id)

        # Try to find a circuit schedule
        evc, found_schedule = self._find_evc_by_schedule_id(schedule_id)

        # Can not modify circuits deleted and archived
        if not found_schedule:
            result = f"schedule_id {schedule_id} not found"
            log.debug("update_schedule result %s %s", result, 404)
            raise HTTPException(404, detail=result)

        new_schedule = CircuitSchedule.from_dict(data)
        new_schedule.id = found_schedule.id
        # Remove the old schedule
        evc.circuit_scheduler.remove(found_schedule)
        # Append the modified schedule
        evc.circuit_scheduler.append(new_schedule)

        # Cancel all schedule jobs
        self.sched.cancel_job(found_schedule.id)
        # Add the new circuit schedule
        self.sched.add_circuit_job(evc, new_schedule)
        # Save EVC to mongodb
        evc.sync()

        result = new_schedule.as_dict()
        status = 200

        log.debug("update_schedule result %s %s", result, status)
        return JSONResponse(result, status_code=status)

    @rest("/v2/evc/schedule/{schedule_id}", methods=["DELETE"])
    def delete_schedule(self, request: Request) -> JSONResponse:
        """Remove a circuit schedule.

        Remove the Schedule from EVC.
        Remove the Schedule from cron job.
        Save the EVC to the Storehouse.
        """
        schedule_id = request.path_params["schedule_id"]
        log.debug("delete_schedule /v2/evc/schedule/%s", schedule_id)
        evc, found_schedule = self._find_evc_by_schedule_id(schedule_id)

        # Can not modify circuits deleted and archived
        if not found_schedule:
            result = f"schedule_id {schedule_id} not found"
            log.debug("delete_schedule result %s %s", result, 404)
            raise HTTPException(404, detail=result)

        # Remove the old schedule
        evc.circuit_scheduler.remove(found_schedule)

        # Cancel all schedule jobs
        self.sched.cancel_job(found_schedule.id)
        # Save EVC to mongodb
        evc.sync()

        result = "Schedule removed"
        status = 200

        log.debug("delete_schedule result %s %s", result, status)
        return JSONResponse(result, status_code=status)

    def _check_no_tag_duplication(
        self,
        evc_id: str,
        uni_a: Optional[UNI] = None,
        uni_z: Optional[UNI] = None
    ):
        """Check if the given EVC has UNIs with no tag and if these are
         duplicated. Raise DuplicatedNoTagUNI if duplication is found.
        Args:
            evc (dict): EVC to be analyzed.
        """

        # No UNIs
        if not (uni_a or uni_z):
            return

        if (not (uni_a and not uni_a.user_tag) and
                not (uni_z and not uni_z.user_tag)):
            return
        for circuit in self.circuits.copy().values():
            if (not circuit.archived and circuit._id != evc_id):
                if uni_a and uni_a.user_tag is None:
                    circuit.check_no_tag_duplicate(uni_a)
                if uni_z and uni_z.user_tag is None:
                    circuit.check_no_tag_duplicate(uni_z)

    @listen_to("kytos/topology.link_up")
    def on_link_up(self, event):
        """Change circuit when link is up or end_maintenance."""
        self.handle_link_up(event)

    # pylint: disable=too-many-locals
    def handle_link_up(self, event: KytosEvent):
        """Change circuit when link is up or end_maintenance.

        Static EVCs converge without a redeploy (EP041), by precedence:

        - active off primary_path, primary UP: revert with an ingress swap
        - inactive, a configured path recovered by this link: resume on it,
          primary preferred
        - inactive, no configured path UP, dynamic_backup_path: request a
          dynamic escape
        - otherwise the model's handle_link_up, which only deploys a
          configured path when nothing is provisioned; an active dual static
          EVC gets a missing standby installed
        """
        link = event.content["link"]
        log.info(f"Event handle_link_up {link}")

        with ExitStack() as exit_stack:
            exit_stack.enter_context(self.multi_evc_lock)

            revert_to_primary = []
            handle_link_up_ladder = []
            resume_static = []
            dyn_recovery = []
            evcs_to_update: dict[str, EVC] = {}

            for evc in self.get_evcs_by_svc_level():
                if not (evc.is_enabled() and not evc.archived):
                    continue
                exit_stack.enter_context(evc.lock)
                if evc.is_eligible_for_static_revert():
                    revert_to_primary.append(evc)
                elif evc.is_eligible_for_static_resume(link):
                    resume_static.append(evc)
                elif evc.is_eligible_for_dyn_failover_recovery():
                    dyn_recovery.append(evc)
                else:
                    handle_link_up_ladder.append(evc)

            # a failed resume keeps its configured paths installed, the
            # consistency routine redeploys it after its failed traces
            if resume_static:
                self.resume_on_static(resume_static)

            for evc in dyn_recovery:
                evc.request_dyn_escape()

            if revert_to_primary:
                reverted, failed = self.execute_swap_to_standby(
                    revert_to_primary
                )
                evcs_to_update.update((evc.id, evc) for evc in reverted)
                if failed:
                    # stored anyway, a primary cold installed before the
                    # failed swap must keep its s_vlan across a restart
                    evcs_to_update.update((evc.id, evc) for evc in failed)
                    log.error(f"Failed to revert {failed} to primary_path, "
                              "retried on the next link_up")
                for evc in reverted:
                    self.request_failover_path(evc)

            # stored before the per EVC ladder, so an error redeploying one
            # EVC can't skip storing the others
            if evcs_to_update:
                self.mongo_controller.update_evcs(
                    [evc.as_dict() for evc in evcs_to_update.values()]
                )

            for evc in handle_link_up_ladder:
                evc.handle_link_up(link)
                # a missing standby, e.g. a failed install or pre-EP041
                if evc.has_dual_static_paths() and evc.is_active():
                    self.install_static_standby(evc)

    def install_static_standby(self, evc: EVC) -> bool:
        """Install a dual static EVC's standby when it is UP but missing,
        through execute_install_standby, storing its new s_vlan. A no op when
        it's already installed (EP041)."""
        standby = evc.get_static_standby_path()
        if standby and standby.is_deployed():
            return True
        installed, _ = self.execute_install_standby([(evc, standby)])
        if installed:
            evc.sync()
        return bool(installed)

    # Possibly replace this with interruptions?
    @listen_to(
        '.*.switch.interface.(link_up|link_down|created|deleted)',
        '.*.interface.(disabled|enabled|up|down)'
    )
    def on_interface_link_change(self, event: KytosEvent):
        """
        Handler for interface link_up and link_down events.
        """
        self.handle_on_interface_link_change(event)

    def handle_on_interface_link_change(self, event: KytosEvent):
        """
        Handler to sort interface events {link_(up, down), create, deleted}

        To avoid multiple database updated (link flap):
        Every interface is identfied and processed in parallel.
        Once an interface event is received a time is started.
        While time is running self._intf_events will be updated.
        After time has passed last received event will be processed.
        """
        iface = event.content.get("interface")
        with self._lock_interfaces[iface.id]:
            _now = event.timestamp
            # Return out of order events
            if (
                iface.id in self._intf_events
                and self._intf_events[iface.id]["event"].timestamp > _now
            ):
                return
            self._intf_events[iface.id].update({"event": event})
            if "last_acquired" in self._intf_events[iface.id]:
                return
            self._intf_events[iface.id].update({"last_acquired": now()})
        time.sleep(settings.UNI_STATE_CHANGE_DELAY)
        with self._lock_interfaces[iface.id]:
            event = self._intf_events[iface.id]["event"]
            self._intf_events[iface.id].pop('last_acquired', None)
            _, _, event_type = event.name.rpartition('.')
            if event_type in ('link_up', 'created', 'enabled', 'up'):
                self.handle_interface_link_up(iface)
            elif event_type in ('link_down', 'deleted', 'disabled', 'down'):
                self.handle_interface_link_down(iface)

    def handle_interface_link_up(self, interface):
        """Handler for interface link_up events

        An EVC keeping its configured paths resumes on an UP one, never
        redeployed (EP041)."""
        log.info("Event handle_interface_link_up %s", interface)
        resume = list[EVC]()
        for evc in self.get_evcs_by_svc_level():
            if not _does_uni_affect_evc(evc, interface, "up"):
                continue
            with evc.lock:
                if not _does_uni_affect_evc(evc, interface, "up"):
                    continue
                if evc.is_eligible_for_static_resume():
                    resume.append(evc)
                elif (evc.keeps_static_paths() and evc.current_path
                      and evc.current_path.status != EntityStatus.UP):
                    if evc.is_eligible_for_dyn_failover_recovery():
                        evc.request_dyn_escape()
                else:
                    evc.handle_interface_link_up(interface)
        if not resume:
            return

        with ExitStack() as exit_stack:
            exit_stack.enter_context(self.multi_evc_lock)
            ready = list[EVC]()
            for evc in resume:
                exit_stack.enter_context(evc.lock)
                # it may have escaped, or a UNI gone down, meanwhile
                if (_does_uni_affect_evc(evc, interface, "up")
                        and evc.is_eligible_for_static_resume()):
                    ready.append(evc)
            for evc in self.resume_on_static(ready):
                emit_event(self.controller, "uni_active_updated",
                           content=map_evc_event_content(evc))

    def handle_interface_link_down(self, interface):
        """
        Handler for interface link_down events
        """
        log.info("Event handle_interface_link_down %s", interface)
        for evc in self.get_evcs_by_svc_level():
            if _does_uni_affect_evc(evc, interface, "down"):
                with evc.lock:
                    evc.handle_interface_link_down(
                        interface
                    )

    @listen_to("kytos/topology.link_down", pool="dynamic_single")
    def on_link_down(self, event):
        """Change circuit when link is down or under_mantenance."""
        self.handle_link_down(event)

    def prepare_swap_to_failover_flow(self, evc: EVC):
        """Prepare an evc for switching to failover."""
        install_flows = {}
        try:
            install_flows = evc.get_failover_flows()
        except Exception:
            err = traceback.format_exc()
            log.error(
                "Ignore Failover path for "
                f"{evc} due to error: {err}"
            )
        return install_flows

    def prepare_swap_to_failover_event(self, evc: EVC, install_flow):
        """Prepare event contents for swap to failover."""
        return map_evc_event_content(
            evc,
            flows=deepcopy(install_flow)
        )

    def execute_swap_to_failover(
        self,
        evcs: list[EVC],
        activate: bool = False,
    ) -> tuple[list[EVC], list[EVC]]:
        """Process changes needed to commit a swap to failover.

        With activate, an EVC that was down, such as a static EVC escaping
        onto a dynamic path, is activated once swapped, before the event is
        built so it reports its new state (EP041).
        """
        event_contents = {}
        install_flows = {}
        flows_by_evc = {}
        swapped_evcs = list[EVC]()
        not_swapped_evcs = list[EVC]()

        for evc in evcs:
            install_flow = self.prepare_swap_to_failover_flow(evc)
            if install_flow:
                flows_by_evc[evc.id] = deepcopy(install_flow)
                install_flows = merge_flow_dicts(install_flows, install_flow)
                event_contents[evc.id] =\
                    self.prepare_swap_to_failover_event(evc, install_flow)
                swapped_evcs.append(evc)
            else:
                not_swapped_evcs.append(evc)

        try:
            send_flow_mods_http(
                install_flows,
                "install"
            )
            for evc in swapped_evcs:
                temp_path = evc.current_path
                evc.current_path = evc.failover_path
                evc.failover_path = temp_path
                if activate:
                    try:
                        evc.try_to_activate()
                    except ActivationError as exc:
                        log.error(f"Fail to activate {evc}: {exc}")
                    event_contents[evc.id] = \
                        self.prepare_swap_to_failover_event(
                            evc, flows_by_evc[evc.id]
                        )
            emit_event(
                self.controller, "failover_link_down",
                content=deepcopy(event_contents)
            )
            return swapped_evcs, not_swapped_evcs
        except FlowModException as exc:
            log.error(f"Fail to install failover flows for {evcs}: {exc}")
            return [], [*swapped_evcs, *not_swapped_evcs]

    def execute_install_standby(
        self, evc_paths: list[tuple[EVC, Path]]
    ) -> tuple[list[EVC], list[EVC]]:
        """Install configured paths (egress + NNI) not installed yet, in one
        batch; installed ones are a no op (EP041)."""
        install_flows, contents = {}, {}
        ready, failed = list[EVC](), list[EVC]()
        chosen = list[tuple[EVC, Path, dict]]()
        for evc, path in evc_paths:
            if not path or path.status != EntityStatus.UP:
                failed.append(evc)
                continue
            if path.is_deployed():
                ready.append(evc)
                continue
            try:
                path.choose_vlans(self.controller)
            except KytosNoTagAvailableError as err:
                log.error(f"Fail to choose vlans for {evc} standby: {err}")
                failed.append(evc)
                continue
            try:
                flows = merge_flow_dicts(
                    evc._prepare_nni_flows(path),
                    evc._prepare_uni_flows(path, skip_in=True),
                )
            except Exception:
                log.error(f"Fail to prepare {evc} standby: "
                          f"{traceback.format_exc()}")
                path.make_vlans_available(self.controller)
                failed.append(evc)
                continue
            contents[evc.id] = map_evc_event_content(
                evc,
                flows=deepcopy(flows),
                removed_flows={},
                current_path=evc.current_path.as_dict(),
            )
            install_flows = merge_flow_dicts(install_flows, deepcopy(flows))
            chosen.append((evc, path, flows))
        if not chosen:
            return ready, failed

        try:
            send_flow_mods_http(install_flows, "install")
        except FlowModException as exc:
            log.error(f"Fail to install standby paths for "
                      f"{[evc for evc, _, _ in chosen]}: {exc}")
            self._roll_back_standby_install(chosen)
            return ready, [*failed, *(evc for evc, _, _ in chosen)]
        emit_event(
            self.controller, "static.standby_installed", content=contents
        )
        return [*ready, *(evc for evc, _, _ in chosen)], failed

    def _roll_back_standby_install(
        self, chosen: list[tuple[EVC, Path, dict]]
    ) -> None:
        """Delete a failed batch's possibly partial installs and free their
        VLANs, even if that delete fails too, like remove_path_flows."""
        delete_flows = {}
        for _, _, flows in chosen:
            delete_flows = merge_flow_dicts(
                delete_flows, prepare_delete_flow(deepcopy(flows))
            )
        try:
            send_flow_mods_http(delete_flows, "delete")
        except FlowModException as exc:
            log.error(f"Failed to roll back the standby paths of "
                      f"{[evc for evc, _, _ in chosen]}: {exc}")
        for _, path, _ in chosen:
            path.make_vlans_available(self.controller)

    def execute_swap_to_standby(
        self,
        evcs: list[EVC],
    ) -> tuple[list[EVC], list[EVC]]:
        """Swap static EVCs onto their standby configured path with a UNI
        ingress install; an old dynamic path is cleared, unless kept as a
        single static + dynamic EVC's failover (EP041)."""
        install_flows, flows_by_evc = {}, {}
        targets = {}
        swapped_evcs = list[EVC]()
        not_swapped_evcs = list[EVC]()

        standbys = {evc.id: evc.get_static_standby_path() for evc in evcs}
        ready, not_ready = self.execute_install_standby(
            [(evc, standbys[evc.id]) for evc in evcs]
        )
        not_swapped_evcs.extend(not_ready)

        for evc in ready:
            standby = standbys[evc.id]
            install_flow = {}
            try:
                install_flow = evc._prepare_uni_flows(standby, skip_out=True)
            except Exception:
                err = traceback.format_exc()
                log.error(
                    f"Ignore standby swap for {evc} due to error: {err}"
                )
            if install_flow:
                install_flows = merge_flow_dicts(
                    install_flows, deepcopy(install_flow)
                )
                flows_by_evc[evc.id] = install_flow
                targets[evc.id] = standby
                swapped_evcs.append(evc)
            else:
                not_swapped_evcs.append(evc)
        if not swapped_evcs:
            return [], not_swapped_evcs

        try:
            send_flow_mods_http(install_flows, "install")
        except FlowModException as exc:
            log.error(f"Fail to install standby flows for {evcs}: {exc}")
            return [], [*swapped_evcs, *not_swapped_evcs]
        detached = []
        for evc in swapped_evcs:
            old_current, evc.current_path = evc.current_path, targets[evc.id]
            evc.execution_rounds = 0
            # it now forwards, don't leave it reported as inactive
            if not evc.is_active() and evc.are_unis_active():
                try:
                    evc.try_to_activate()
                except ActivationError as exc:
                    log.error(f"Fail to activate {evc}: {exc}")
            if any(old_current is path
                   for path in (evc.primary_path, evc.backup_path)):
                continue  # kept installed as the new standby
            # a single static + dynamic EVC keeps its old dynamic as its
            # failover while it's UP and disjoint from primary
            if (evc.has_single_static_dynamic_path()
                    and not evc.failover_path):
                evc.failover_path = old_current
                if evc.is_failover_reusable_after_revert():
                    continue
                evc.failover_path = Path([])
            if old_current.is_deployed():
                detached.append((evc, old_current))
        # built once repointed and activated
        emit_event(
            self.controller, "static.ingress_swapped", content={
                evc.id: self.prepare_swap_to_failover_event(
                    evc, flows_by_evc[evc.id]
                )
                for evc in swapped_evcs
            }
        )
        if detached:
            self.execute_clear_paths(detached)
        return swapped_evcs, not_swapped_evcs

    def prepare_clear_failover_flow(self, evc: EVC, path: Path = None):
        """Prepare an evc for clearing the old path, failover_path unless
        another detached path is given."""
        path = evc.failover_path if path is None else path
        del_flows = {}
        try:
            del_flows = prepare_delete_flow(
                merge_flow_dicts(
                    evc._prepare_uni_flows(path, skip_in=True),
                    evc._prepare_nni_flows(path)
                )
            )
        except Exception:
            err = traceback.format_exc()
            log.error(f"Fail to remove {evc} old_path: {err}")
        return del_flows

    def prepare_clear_failover_event(self, evc: EVC, delete_flow):
        """Prepare event contents for clearing failover."""
        return map_evc_event_content(
            evc,
            current_path=evc.current_path.as_dict(),
            removed_flows=deepcopy(delete_flow)
        )

    def execute_clear_failover(
        self,
        evcs: list[EVC]
    ) -> tuple[list[EVC], list[EVC]]:
        """Process changes needed to commit clearing the failover path"""
        event_contents = {}
        delete_flows = {}
        cleared_evcs = list[EVC]()
        not_cleared_evcs = list[EVC]()

        for evc in evcs:
            delete_flow = self.prepare_clear_failover_flow(evc)
            if delete_flow:
                delete_flows = merge_flow_dicts(delete_flows, delete_flow)
                event_contents[evc.id] =\
                    self.prepare_clear_failover_event(evc, delete_flow)
                cleared_evcs.append(evc)
            else:
                not_cleared_evcs.append(evc)

        try:
            send_flow_mods_http(
                delete_flows,
                'delete'
            )
            for evc in cleared_evcs:
                evc.failover_path.make_vlans_available(self.controller)
                evc.failover_path = Path([])
            emit_event(
                self.controller,
                "failover_old_path",
                content=event_contents
            )
            return cleared_evcs, not_cleared_evcs
        except FlowModException as exc:
            log.error(f"Failed to delete failover flows for {evcs}: {exc}")
            return [], [*cleared_evcs, *not_cleared_evcs]

    def execute_clear_paths(self, evc_paths: list[tuple[EVC, Path]]) -> None:
        """Clear the egress/NNI flows and VLANs of paths no ingress points at
        anymore, detached from every role of their EVC, in one batched delete
        emitting failover_old_path (EP041). Like remove_path_flows the VLANs
        are freed even if the delete fails, as nothing else references these
        paths.
        """
        delete_flows, event_contents, removed_flows = {}, {}, {}
        cleared = []
        for evc, path in evc_paths:
            delete_flow = self.prepare_clear_failover_flow(evc, path)
            if not delete_flow:
                log.error(f"Failed to prepare the deletion of {evc} path "
                          f"{path}")
                continue
            removed_flows[evc.id] = merge_flow_dicts(
                removed_flows.get(evc.id, {}), deepcopy(delete_flow)
            )
            delete_flows = merge_flow_dicts(delete_flows, delete_flow)
            event_contents[evc.id] = self.prepare_clear_failover_event(
                evc, removed_flows[evc.id]
            )
            cleared.append((evc, path))
        sent = False
        if cleared:
            try:
                send_flow_mods_http(delete_flows, "delete")
                sent = True
            except FlowModException as exc:
                log.error(f"Failed to delete the flows of paths {cleared}: "
                          f"{exc}")
        for evc, path in evc_paths:
            try:
                path.make_vlans_available(self.controller)
            except KytosTagError as err:
                log.error(f"Error removing {evc} path: {err}")
        if sent:
            emit_event(
                self.controller, "failover_old_path", content=event_contents
            )

    def prepare_remove_ingress_flow(self, evc: EVC):
        """Prepare deletion of a static EVC's active UNI ingress."""
        del_flows = {}
        try:
            del_flows = prepare_delete_flow(
                evc._prepare_uni_flows(evc.current_path, skip_out=True)
            )
        except Exception:
            err = traceback.format_exc()
            log.error(f"Fail to remove {evc} ingress: {err}")
        return del_flows

    def execute_remove_ingress(
        self,
        evcs: list[EVC]
    ) -> tuple[list[EVC], list[EVC]]:
        """Drop only the UNI ingress of static EVCs with no usable path,
        keeping their configured paths installed, and deactivate them
        (EP041)."""
        delete_flows, removed = {}, {}
        not_removed_evcs = list[EVC]()

        for evc in evcs:
            delete_flow = self.prepare_remove_ingress_flow(evc)
            if delete_flow:
                removed[evc.id] = (evc, delete_flow)
                delete_flows = merge_flow_dicts(
                    delete_flows, deepcopy(delete_flow)
                )
            else:
                not_removed_evcs.append(evc)
        removed_evcs = [evc for evc, _ in removed.values()]
        if not removed_evcs:
            return [], not_removed_evcs

        try:
            send_flow_mods_http(delete_flows, 'delete')
        except FlowModException as exc:
            log.error(f"Failed to remove ingress flows for {evcs}: {exc}")
            return [], [*removed_evcs, *not_removed_evcs]
        for evc in removed_evcs:
            evc.deactivate()
        # built once deactivated, consumers see its actual state
        emit_event(
            self.controller, "static.ingress_removed", content={
                evc.id: map_evc_event_content(
                    evc,
                    current_path=evc.current_path.as_dict(),
                    removed_flows=deepcopy(delete_flow),
                )
                for evc, delete_flow in removed.values()
            }
        )
        return removed_evcs, not_removed_evcs

    def execute_dyn_escape(
        self,
        evcs: list[EVC],
    ) -> tuple[list[EVC], list[EVC]]:
        """Drop the ingress of static EVCs with a dynamic backup and no usable
        path, keeping their installed configured paths, and schedule their
        dynamic escape (EP041). Returns the scheduled EVCs, and the ones
        left for the undeploy fallback."""
        handled, remove_ingress, failed = [], [], []
        for evc in evcs:
            if evc.current_path.is_deployed():
                remove_ingress.append(evc)
            else:
                handled.append(evc)
        if remove_ingress:
            removed, not_removed = self.execute_remove_ingress(remove_ingress)
            handled.extend(removed)
            failed.extend(not_removed)

        scheduled, detached = [], []
        for evc in handled:
            static = evc.get_installed_static_path()
            if not static:
                # nothing kept installed to protect, a redeploy is as good
                failed.append(evc)
                continue
            for path in (evc.current_path, evc.failover_path):
                if path.is_deployed() and not any(
                    path is kept for kept in (evc.primary_path,
                                              evc.backup_path)
                ):
                    detached.append((evc, path))
            evc.current_path, evc.failover_path = static, Path([])
            evc.deactivate()
            scheduled.append(evc)
            evc.request_dyn_escape()
        if detached:
            self.execute_clear_paths(detached)
        return scheduled, failed

    @listen_to("kytos/mef_eline.need_dyn_escape")
    def on_evc_need_dyn_escape(self, event):
        """Recover a down static EVC onto a dynamic escape."""
        self.handle_evc_need_dyn_escape(event)

    def handle_evc_need_dyn_escape(self, event):
        """Escape a down static EVC onto a fresh dynamic path, holding only its
        lock, like handle_evc_need_redeploy (EP041)."""
        evc = self.circuits.get(event.content["evc_id"])
        if evc is None:
            return
        with evc.lock:
            if not (evc.is_enabled() and not evc.archived
                    and evc.is_eligible_for_dyn_failover_recovery()):
                return
            # the consistency routine redeploys it after WAIT_FOR_OLD_PATH
            # failed traces
            if not self.escape_to_dynamic(evc):
                log.info(f"{evc} found no usable dynamic escape, it stays "
                         "down on its kept configured paths")

    def escape_to_dynamic(self, evc: EVC) -> bool:
        """Swap the UNI ingress onto a fresh dynamic path disjoint from
        primary_path, keeping the configured paths installed (EP041)."""
        statics = [path for path in (evc.primary_path, evc.backup_path)
                   if path]
        old_current = evc.current_path
        try:
            fresh = (
                evc.setup_failover_path(
                    warn_if_not_path=False,
                    reference_path=evc.primary_path,
                )
                and evc.failover_path
                and evc.failover_path.status == EntityStatus.UP
                # same links as a configured path would be mistaken for it
                and not any(evc.failover_path == path for path in statics)
            )
        except Exception:
            log.error(f"Fail to setup failover for {evc}: "
                      f"{traceback.format_exc()}")
            fresh = False

        if fresh:
            swapped, _ = self.execute_swap_to_failover([evc], activate=True)
            if swapped:
                evc.failover_path = Path([])
                # cleared after activating, so failover_old_path reports
                # the EVC as active
                if old_current.is_deployed() and not any(
                    old_current is path for path in statics
                ):
                    self.execute_clear_paths([(evc, old_current)])
                evc.execution_rounds = 0
                evc.sync()
                log.info(f"{evc} escaped onto a dynamic path")
                return True
            self.execute_remove_ingress([evc])

        if evc.failover_path:
            self.execute_clear_paths([(evc, evc.failover_path)])
            evc.failover_path = Path([])
        evc.sync()
        return False

    def prepare_undeploy_flow(self, evc: EVC):
        """Prepare an evc for undeploying, its kept standby static paths
        included so they are swept in the same batch (EP041)."""
        del_flows = {}
        try:
            del_flows = prepare_delete_flow(
                merge_flow_dicts(
                    evc._prepare_uni_flows(evc.current_path, skip_in=False),
                    evc._prepare_uni_flows(evc.failover_path, skip_in=True),
                    evc._prepare_nni_flows(evc.current_path),
                    evc._prepare_nni_flows(evc.failover_path),
                    *(
                        merge_flow_dicts(
                            evc._prepare_uni_flows(path, skip_in=True),
                            evc._prepare_nni_flows(path),
                        )
                        for path in evc.get_kept_standby_paths()
                    ),
                )
            )
        except Exception:
            err = traceback.format_exc()
            log.error(f"Fail to undeploy {evc}: {err}")
        return del_flows

    def execute_undeploy(self, evcs: list[EVC]):
        """Process changes needed to commit an undeploy"""
        delete_flows = {}
        undeploy_evcs = list[EVC]()
        not_undeploy_evcs = list[EVC]()

        standbys = {}
        for evc in evcs:
            standbys[evc.id] = evc.get_kept_standby_paths()
            delete_flow = self.prepare_undeploy_flow(evc)
            if delete_flow:
                delete_flows = merge_flow_dicts(delete_flows, delete_flow)
                undeploy_evcs.append(evc)
            else:
                not_undeploy_evcs.append(evc)

        try:
            send_flow_mods_http(
                delete_flows,
                'delete'
            )

            for evc in undeploy_evcs:
                for path in standbys[evc.id]:
                    path.make_vlans_available(self.controller)
                evc.current_path.make_vlans_available(self.controller)
                evc.failover_path.make_vlans_available(self.controller)
                evc.current_path = Path([])
                evc.failover_path = Path([])
                evc.deactivate()
                emit_event(
                    self.controller,
                    "need_redeploy",
                    content={"evc_id": evc.id}
                )
                log.info(f"{evc} scheduled for redeploy")
            return undeploy_evcs, not_undeploy_evcs
        except FlowModException as exc:
            log.error(
                f"Failed to delete flows before redeploy for {evcs}: {exc}"
            )
            return [], [*undeploy_evcs, *not_undeploy_evcs]

    # pylint: disable=too-many-return-statements
    @staticmethod
    def classify_static_link_down(evc: EVC, link) -> str:
        """Convergence bucket of an EVC keeping its configured paths on a
        link_down, "" for nothing to do (EP041)."""
        if not evc.is_affected_by_link(link):
            if (evc.failover_path
                    and evc.is_failover_path_affected_by_link(link)):
                return "clear_failover"
            return ""

        standby = evc.get_static_standby_path()
        if (standby and standby.status == EntityStatus.UP
                and not standby.is_affected_by_link(link)):
            return "swap_to_standby"
        if (evc.has_single_static_dynamic_path()
                and evc.failover_path
                and evc.failover_path.status == EntityStatus.UP
                and not evc.is_failover_path_affected_by_link(link)):
            return "swap_to_failover"
        # also an inactive EVC: it may still hold its ingress (a UNI down, a
        # reinstall pending its trace), never waste NNI bandwidth on a dead
        # path; deleting an ingress already removed is harmless
        return "dyn_escape" if evc.dynamic_backup_path else "remove_ingress"

    # pylint: disable=too-many-locals
    def handle_link_down(self, event):
        """Change circuit when link is down or under_mantenance.

        Static EVCs keep their configured paths installed (EP041), by
        precedence when their forwarding path is hit:

        - a configured standby is UP: swap the ingress onto it
        - single static + dynamic with a usable failover_path: swap onto it
        - nothing pre-installed is usable: remove the ingress and deactivate,
          a dead dynamic path is cleared; with dynamic_backup_path a dynamic
          escape is also requested, computed off this handler's locks

        A failover_path hit on its own is cleared, a standby is left alone,
        and any failure falls back to undeploy and redeploy. Other EVCs swap
        to their failover_path or are undeployed and redeployed.
        """
        link = event.content["link"]
        log.info("Event handle_link_down %s", link)

        with ExitStack() as exit_stack:
            exit_stack.enter_context(self.multi_evc_lock)
            swap_to_failover = list[EVC]()
            swap_to_standby = list[EVC]()
            remove_ingress = list[EVC]()
            dyn_escape = list[EVC]()
            undeploy = list[EVC]()
            clear_failover = list[EVC]()
            evcs_to_update = dict[str, EVC]()
            buckets = {
                "swap_to_standby": swap_to_standby,
                "swap_to_failover": swap_to_failover,
                "dyn_escape": dyn_escape,
                "remove_ingress": remove_ingress,
                "clear_failover": clear_failover,
            }

            for evc in self.get_evcs_by_svc_level():
                with ExitStack() as sub_stack:
                    sub_stack.enter_context(evc.lock)
                    if evc.keeps_static_paths():
                        action = self.classify_static_link_down(evc, link)
                        if action:
                            buckets[action].append(evc)
                            exit_stack.push(sub_stack.pop_all())
                        continue

                    failover_usable = (
                        evc.failover_path
                        and evc.failover_path.status == EntityStatus.UP
                        and not evc.is_failover_path_affected_by_link(link)
                    )
                    if evc.is_affected_by_link(link) and failover_usable:
                        swap_to_failover.append(evc)
                    elif evc.is_affected_by_link(link) and not failover_usable:
                        undeploy.append(evc)
                    elif all((
                        not evc.is_affected_by_link(link),
                        evc.failover_path,
                        evc.is_failover_path_affected_by_link(link),
                    )):
                        clear_failover.append(evc)
                    else:
                        continue

                    exit_stack.push(sub_stack.pop_all())

            if swap_to_standby:
                success, failure = self.execute_swap_to_standby(
                    swap_to_standby
                )
                # e.g. a single static + dynamic EVC swapped back to primary
                for evc in success:
                    self.request_failover_path(evc)

                evcs_to_update.update((evc.id, evc) for evc in success)
                # A failed swap falls back to a full teardown, standby included
                undeploy.extend(failure)

            # Swap from current path to failover path

            if swap_to_failover:
                success, failure = self.execute_swap_to_failover(
                    swap_to_failover
                )

                for evc in success:
                    # After the swap, failover_path holds the old current path
                    if (evc.has_single_static_dynamic_path()
                            and evc.failover_path == evc.primary_path):
                        evc.failover_path = Path([])
                    else:
                        clear_failover.append(evc)

                evcs_to_update.update((evc.id, evc) for evc in success)

                undeploy.extend(failure)

            # Clear out failover path

            if clear_failover:
                success, failure = self.execute_clear_failover(clear_failover)

                evcs_to_update.update((evc.id, evc) for evc in success)

                undeploy.extend(failure)

            if remove_ingress:
                success, failure = self.execute_remove_ingress(remove_ingress)

                evcs_to_update.update((evc.id, evc) for evc in success)

                # A failed ingress removal falls back to a full teardown
                undeploy.extend(failure)

            if dyn_escape:
                success, failure = self.execute_dyn_escape(dyn_escape)

                evcs_to_update.update((evc.id, evc) for evc in success)

                # so does one with no configured path installed to keep
                undeploy.extend(failure)

            # Undeploy the evc, schedule a redeploy

            if undeploy:
                success, failure = self.execute_undeploy(undeploy)

                evcs_to_update.update((evc.id, evc) for evc in success)

                if failure:
                    log.error(f"Failed to handle_link_down for {failure}")

            # Push update to DB

            if evcs_to_update:
                self.mongo_controller.update_evcs(
                    [evc.as_dict() for evc in evcs_to_update.values()]
                )

    @listen_to("kytos/mef_eline.need_redeploy")
    def on_evc_need_redeploy(self, event):
        """Redeploy evcs that need to be redeployed."""
        self.handle_evc_need_redeploy(event)

    def handle_evc_need_redeploy(self, event):
        """Redeploy evcs that need to be redeployed."""
        evc = self.circuits.get(event.content["evc_id"])
        if evc is None:
            return
        with evc.lock:
            if not evc.is_enabled() or evc.is_active():
                return
            if evc.is_inactive_on_static():
                log.info(f"Skipping stale redeploy of {evc}, it is on its "
                         "kept configured paths")
                return
            result = evc.deploy()
        event_name = "error_redeploy_link_down"
        if result:
            log.info(f"{evc} redeployed")
            event_name = "redeployed_link_down"
        emit_event(self.controller, event_name,
                   content=map_evc_event_content(evc))

    @listen_to(
        "kytos/mef_eline.(redeployed_link_(up|down)|deployed|need_failover)"
    )
    def on_evc_deployed(self, event):
        """Handle EVC deployed|redeployed_link_down."""
        self.handle_evc_deployed(event)

    def handle_evc_deployed(self, event):
        """Setup protection on evc deployed."""
        evc = self.circuits.get(event.content["evc_id"])
        if evc is None:
            return
        with evc.lock:
            if not evc.is_active() or not evc.current_path:
                return
            if evc.has_dual_static_paths():
                # Dual static EVCs keep the standby configured path
                # installed instead of a failover_path (EP041).
                self.install_static_standby(evc)
                return
            if (
                not evc.is_eligible_for_failover_path()
                or evc.failover_path
            ):
                return
            evc.setup_failover_path()

    @listen_to("kytos/topology.topology_loaded")
    def on_topology_loaded(self, event):  # pylint: disable=unused-argument
        """Load EVCs once the topology is available."""
        self.load_all_evcs()

    def load_all_evcs(self):
        """Try to load all EVCs on startup."""
        circuits = self.mongo_controller.get_circuits()['circuits'].items()
        for circuit_id, circuit in circuits:
            if circuit_id not in self.circuits:
                self._load_evc(circuit)
        emit_event(self.controller, "evcs_loaded", content=dict(circuits),
                   timeout=1)

    def _load_evc(self, circuit_dict):
        """Load one EVC from mongodb to memory."""
        try:
            evc = self._evc_from_dict(circuit_dict, from_db=True)
        except (ValueError, KytosTagError) as exception:
            log.error(
                f"Could not load EVC: dict={circuit_dict} error={exception}"
            )
            return None
        if evc.archived:
            return None

        self.circuits.setdefault(evc.id, evc)
        self.sched.add(evc)
        return evc

    @listen_to("kytos/flow_manager.flow.error")
    def on_flow_mod_error(self, event):
        """Handle flow mod errors related to an EVC."""
        self.handle_flow_mod_error(event)

    def handle_flow_mod_error(self, event):
        """Handle flow mod errors related to an EVC."""
        flow = event.content["flow"]
        command = event.content.get("error_command")
        if command != "add":
            return
        evc = self.circuits.get(EVC.get_id_from_cookie(flow.cookie))
        if not evc or evc.archived or not evc.is_enabled():
            return
        with evc.lock:
            evc.remove_static_standby_flows()
            evc.remove_current_flows(sync=False)
            evc.remove_failover_flows(sync=True)

    def _evc_dict_with_instances(self, evc_dict, from_db=False):
        """Convert some dict values to instance of EVC classes.

        This method will convert: [UNI, Link]. Link metadata of the
        configured static paths is only trusted when ``from_db``.
        """
        data = evc_dict.copy()  # Do not modify the original dict
        for attribute, value in data.items():
            # Get multiple attributes.
            # Ex: uni_a, uni_z
            if "uni" in attribute:
                try:
                    data[attribute] = self._uni_from_dict(value)
                except ValueError as exception:
                    result = "Error creating UNI: Invalid value"
                    raise ValueError(result) from exception

            if attribute == "circuit_scheduler":
                data[attribute] = []
                for schedule in value:
                    data[attribute].append(CircuitSchedule.from_dict(schedule))

            # Get multiple attributes.
            # Ex: primary_links,
            #     backup_links,
            #     current_links_cache,
            #     primary_links_cache,
            #     backup_links_cache
            if "links" in attribute:
                data[attribute] = [
                    self._link_from_dict(link, attribute, from_db)
                    for link in value
                ]

            # Ex: current_path,
            #     primary_path,
            #     backup_path
            if (attribute.endswith("path") and
                    attribute != "dynamic_backup_path"):
                data[attribute] = Path([
                    self._link_from_dict(link, attribute, from_db)
                    for link in value
                ])

        return data

    def _evc_from_dict(self, evc_dict, created=False, from_db=False):
        data = self._evc_dict_with_instances(evc_dict, from_db)
        # Add default values
        if created:
            for key, value in self.default_values.items():
                if key not in data:
                    data[key] = value
        data["table_group"] = self.table_group
        evc = EVC(self.controller, **data)
        if from_db:
            self._realias_static_paths(evc)
        return evc

    @staticmethod
    def _realias_static_paths(evc: EVC) -> None:
        """Point current_path/failover_path back at the static Path object they
        were deployed as, keeping the copy holding the s_vlan (EP041)."""
        for role in ("current_path", "failover_path"):
            path = getattr(evc, role)
            if not path:
                continue
            for static_role in ("primary_path", "backup_path"):
                static = getattr(evc, static_role)
                if not static or path != static:
                    continue
                if static.is_deployed() or not path.is_deployed():
                    setattr(evc, role, static)
                else:
                    setattr(evc, static_role, path)
                break

    def _uni_from_dict(self, uni_dict):
        """Return a UNI object from python dict."""
        if uni_dict is None:
            return False

        interface_id = uni_dict.get("interface_id")
        interface = self.controller.get_interface_by_id(interface_id)
        if interface is None:
            result = (
                "Error creating UNI:"
                + f"Could not instantiate interface {interface_id}"
            )
            raise ValueError(result) from ValueError
        tag_convert = {1: "vlan"}
        tag_dict = uni_dict.get("tag", None)
        if tag_dict:
            tag_type = tag_dict.get("tag_type")
            tag_type = tag_convert.get(tag_type, tag_type)
            tag_value = tag_dict.get("value")
            if isinstance(tag_value, list):
                tag_value = get_tag_ranges(tag_value)
                mask_list = get_vlan_tags_and_masks(tag_value)
                tag = TAGRange(tag_type, tag_value, mask_list)
            else:
                tag = TAG(tag_type, tag_value)
        else:
            tag = None
        uni = UNI(interface, tag)
        return uni

    def _link_from_dict(
        self, link_dict: dict, attribute: str, from_db=False
    ) -> Link:
        """Return a Link object from python dict.

        Static paths keep their metadata (s_vlan) only when loaded from the
        DB, a request payload must never claim VLANs (EP041).
        """
        id_a = link_dict.get("endpoint_a").get("id")
        id_b = link_dict.get("endpoint_b").get("id")

        endpoint_a = self.controller.get_interface_by_id(id_a)
        endpoint_b = self.controller.get_interface_by_id(id_b)
        if not endpoint_a:
            error_msg = f"Could not get interface endpoint_a id {id_a}"
            raise ValueError(error_msg)
        if not endpoint_b:
            error_msg = f"Could not get interface endpoint_b id {id_b}"
            raise ValueError(error_msg)

        link = Link(endpoint_a, endpoint_b)
        allowed_paths = {"current_path", "failover_path"}
        if from_db:
            allowed_paths |= {"primary_path", "backup_path"}
        if "metadata" in link_dict and attribute in allowed_paths:
            link.extend_metadata(link_dict.get("metadata"))

        s_vlan = link.get_metadata("s_vlan")
        if s_vlan:
            tag = TAG.from_dict(s_vlan)
            if tag is False:
                error_msg = f"Could not instantiate tag from dict {s_vlan}"
                raise ValueError(error_msg)
            link.update_metadata("s_vlan", tag)
        return link

    def _find_evc_by_schedule_id(self, schedule_id):
        """
        Find an EVC and CircuitSchedule based on schedule_id.

        :param schedule_id: Schedule ID
        :return: EVC and Schedule
        """
        circuits = self._get_circuits_buffer()
        found_schedule = None
        evc = None

        # pylint: disable=unused-variable
        for c_id, circuit in circuits.items():
            for schedule in circuit.circuit_scheduler:
                if schedule.id == schedule_id:
                    found_schedule = schedule
                    evc = circuit
                    break
            if found_schedule:
                break
        return evc, found_schedule

    def _get_circuits_buffer(self):
        """
        Return the circuit buffer.

        If the buffer is empty, try to load data from mongodb.
        """
        if not self.circuits:
            # Load circuits from mongodb to buffer
            circuits = self.mongo_controller.get_circuits()['circuits']
            for c_id, circuit in circuits.items():
                evc = self._evc_from_dict(circuit, from_db=True)
                self.circuits[c_id] = evc
        return self.circuits

    # pylint: disable=attribute-defined-outside-init
    @alisten_to("kytos/of_multi_table.enable_table")
    async def on_table_enabled(self, event):
        """Handle a recently table enabled."""
        table_group = event.content.get("mef_eline", None)
        if not table_group:
            return
        for group in table_group:
            if group not in settings.TABLE_GROUP_ALLOWED:
                log.error(f'The table group "{group}" is not allowed for '
                          f'mef_eline. Allowed table groups are '
                          f'{settings.TABLE_GROUP_ALLOWED}')
                return
        self.table_group.update(table_group)
        content = {"group_table": self.table_group}
        name = "kytos/mef_eline.enable_table"
        await aemit_event(self.controller, name, content)
