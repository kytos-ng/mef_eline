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

from pydantic import ValidationError

from kytos.core import KytosNApp, log, rest
from kytos.core.events import KytosEvent
from kytos.core.exceptions import KytosTagError
from kytos.core.helpers import (alisten_to, listen_to, load_spec, now,
                                validate_openapi)
from kytos.core.interface import TAG, UNI, TAGRange
from kytos.core.link import Link
from kytos.core.rest_api import (HTTPException, JSONResponse, Request,
                                 get_json_or_400)
from kytos.core.tag_ranges import get_tag_ranges
from napps.kytos.mef_eline import controllers, settings
from napps.kytos.mef_eline.exceptions import (DisabledSwitch,
                                              DuplicatedNoTagUNI,
                                              FlowModException, InvalidPath)
from napps.kytos.mef_eline.models import (EVC, DynamicPathManager, EVCDeploy,
                                          Path)
from napps.kytos.mef_eline.scheduler import CircuitSchedule, Scheduler
from napps.kytos.mef_eline.utils import (_does_uni_affect_evc, aemit_event,
                                         check_disabled_component, emit_event,
                                         get_vlan_tags_and_masks,
                                         map_evc_event_content,
                                         merge_flow_dicts, prepare_delete_flow,
                                         send_flow_mods_http)


# pylint: disable=too-many-public-methods
class Main(KytosNApp):
    """Main class of amlight/mef_eline NApp.

    This class is the entry point for this napp.
    """

    spec = load_spec(pathlib.Path(__file__).parent / "openapi.yml")

    def setup(self):
        """Replace the '__init__' method for the KytosNApp subclass.

        The setup method is automatically called by the controller when your
        application is loaded.

        So, if you have any setup routine, insert it here.
        """
        # object used to scheduler circuit events
        self.sched = Scheduler()

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
                and (circuit.is_intra_switch() or circuit.current_path)
                ):
            return True
        return False

    def execute_consistency(self):
        """Execute consistency routine."""
        circuits_to_check = []
        for circuit in self.get_evcs_by_svc_level(enable_filter=False):
            if self.should_be_checked(circuit):
                circuits_to_check.append(circuit)
            circuit.try_setup_failover_path(warn_if_not_path=False)
        circuits_checked = EVCDeploy.check_list_traces(circuits_to_check)
        for circuit in circuits_to_check:
            is_checked = circuits_checked.get(circuit.id)
            if is_checked:
                circuit.execution_rounds = 0
                log.info(f"{circuit} enabled but inactive - activating")
                with circuit.lock:
                    circuit.activate()
                    circuit.sync()
            else:
                circuit.execution_rounds += 1
                if circuit.execution_rounds > settings.WAIT_FOR_OLD_PATH:
                    log.info(f"{circuit} enabled but inactive - redeploy")
                    with circuit.lock:
                        circuit.deploy()

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
            evc = self._evc_from_dict(data)
        except (ValueError, KytosTagError) as exception:
            log.debug("create_circuit result %s %s", exception, 400)
            raise HTTPException(400, detail=str(exception)) from exception
        try:
            check_disabled_component(evc.uni_a, evc.uni_z)
        except DisabledSwitch as exception:
            log.debug("create_circuit result %s %s", exception, 409)
            raise HTTPException(
                    409,
                    detail=f"Path is not valid: {exception}"
                ) from exception

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
                with evc.lock:
                    evc.remove()
            elif redeploy is not None:  # redeploy if active
                with evc.lock:
                    evc.remove()
                    redeployed = evc.deploy()
        else:
            if enable is True:  # enable if inactive
                with evc.lock:
                    redeployed = evc.deploy()
            elif evc.is_enabled() and redeploy:
                with evc.lock:
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
        if evc.is_enabled():
            with evc.lock:
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

    def handle_link_up(self, event):
        """Change circuit when link is up or end_maintenance."""
        log.info("Event handle_link_up %s", event.content["link"])
        for evc in self.get_evcs_by_svc_level():
            if evc.is_enabled() and not evc.archived:
                with evc.lock:
                    evc.handle_link_up(event.content["link"])

    # Possibly replace this with interruptions?
    @listen_to(
        '.*.switch.interface.(link_up|link_down|created|deleted)'
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
            if event_type in ('link_up', 'created'):
                self.handle_interface_link_up(iface)
            elif event_type in ('link_down', 'deleted'):
                self.handle_interface_link_down(iface)

    def handle_interface_link_up(self, interface):
        """
        Handler for interface link_up events
        """
        log.info("Event handle_interface_link_up %s", interface)
        for evc in self.get_evcs_by_svc_level():
            if _does_uni_affect_evc(evc, interface, "up"):
                with evc.lock:
                    evc.handle_interface_link_up(
                        interface
                    )

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
        # pylint: disable=broad-except
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
        evcs: list[EVC]
    ) -> tuple[list[EVC], list[EVC]]:
        """Process changes needed to commit a swap to failover."""
        event_contents = {}
        install_flows = {}
        swapped_evcs = list[EVC]()
        not_swapped_evcs = list[EVC]()

        for evc in evcs:
            install_flow = self.prepare_swap_to_failover_flow(evc)
            if install_flow:
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
            emit_event(
                self.controller, "failover_link_down",
                content=deepcopy(event_contents)
            )
            return swapped_evcs, not_swapped_evcs
        except FlowModException as exc:
            log.error(f"Fail to install failover flows for {evcs}: {exc}")
            return [], [*swapped_evcs, *not_swapped_evcs]

    def prepare_clear_failover_flow(self, evc: EVC):
        """Prepare an evc for clearing the old path."""
        del_flows = {}
        try:
            del_flows = prepare_delete_flow(
                merge_flow_dicts(
                    evc._prepare_uni_flows(evc.failover_path, skip_in=True),
                    evc._prepare_nni_flows(evc.failover_path)
                )
            )
        # pylint: disable=broad-except
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

    def prepare_undeploy_flow(self, evc: EVC):
        """Prepare an evc for undeploying."""
        del_flows = {}
        try:
            del_flows = prepare_delete_flow(
                merge_flow_dicts(
                    evc._prepare_uni_flows(evc.current_path, skip_in=True),
                    evc._prepare_nni_flows(evc.current_path),
                    evc._prepare_nni_flows(evc.failover_path)
                )
            )
        # pylint: disable=broad-except
        except Exception:
            err = traceback.format_exc()
            log.error(f"Fail to undeploy {evc}: {err}")
        return del_flows

    def execute_undeploy(self, evcs: list[EVC]):
        """Process changes needed to commit an undeploy"""
        delete_flows = {}
        undeploy_evcs = list[EVC]()
        not_undeploy_evcs = list[EVC]()

        for evc in evcs:
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

    def handle_link_down(self, event):
        """Change circuit when link is down or under_mantenance."""
        link = event.content["link"]
        log.info("Event handle_link_down %s", link)

        with ExitStack() as exit_stack:
            exit_stack.enter_context(self.multi_evc_lock)
            swap_to_failover = list[EVC]()
            undeploy = list[EVC]()
            clear_failover = list[EVC]()
            evcs_to_update = dict[str, EVC]()

            for evc in self.get_evcs_by_svc_level():
                with ExitStack() as sub_stack:
                    sub_stack.enter_context(evc.lock)
                    if all((
                        evc.is_affected_by_link(link),
                        evc.failover_path,
                        not evc.is_failover_path_affected_by_link(link)
                    )):
                        swap_to_failover.append(evc)
                    elif all((
                        evc.is_affected_by_link(link),
                        not evc.failover_path or
                        evc.is_failover_path_affected_by_link(link)
                    )):
                        undeploy.append(evc)
                    elif all((
                        not evc.is_affected_by_link(link),
                        evc.failover_path,
                        evc.is_failover_path_affected_by_link(link)
                    )):
                        clear_failover.append(evc)
                    else:
                        continue

                    exit_stack.push(sub_stack.pop_all())

            # Swap from current path to failover path

            if swap_to_failover:
                success, failure = self.execute_swap_to_failover(
                    swap_to_failover
                )

                clear_failover.extend(success)

                evcs_to_update.update((evc.id, evc) for evc in success)

                undeploy.extend(failure)

            # Clear out failover path

            if clear_failover:
                success, failure = self.execute_clear_failover(clear_failover)

                evcs_to_update.update((evc.id, evc) for evc in success)

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
            result = evc.deploy()
        event_name = "error_redeploy_link_down"
        if result:
            log.info(f"{evc} redeployed")
            event_name = "redeployed_link_down"
        emit_event(self.controller, event_name,
                   content=map_evc_event_content(evc))

    @listen_to("kytos/mef_eline.evc_affected_by_link_down")
    def on_evc_affected_by_link_down(self, event):
        """Change circuit when link is down or under_mantenance."""
        self.handle_evc_affected_by_link_down(event)

    def handle_evc_affected_by_link_down(self, event):
        """Change circuit when link is down or under_mantenance."""
        evc = self.circuits.get(event.content["evc_id"])
        link = event.content['link']
        if not evc:
            return
        with evc.lock:
            if not evc.is_affected_by_link(link):
                return
            result = evc.handle_link_down()
        event_name = "error_redeploy_link_down"
        if result:
            log.info(f"{evc} redeployed due to link down {link.id}")
            event_name = "redeployed_link_down"
        emit_event(self.controller, event_name,
                   content=map_evc_event_content(evc))

    @listen_to("kytos/mef_eline.(redeployed_link_(up|down)|deployed)")
    def on_evc_deployed(self, event):
        """Handle EVC deployed|redeployed_link_down."""
        self.handle_evc_deployed(event)

    def handle_evc_deployed(self, event):
        """Setup failover path on evc deployed."""
        evc = self.circuits.get(event.content["evc_id"])
        if not evc:
            return
        evc.try_setup_failover_path()

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
            evc = self._evc_from_dict(circuit_dict)
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
            evc.remove_current_flows(sync=False)
            evc.remove_failover_flows(sync=True)

    def _evc_dict_with_instances(self, evc_dict):
        """Convert some dict values to instance of EVC classes.

        This method will convert: [UNI, Link]
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
                    self._link_from_dict(link, attribute) for link in value
                ]

            # Ex: current_path,
            #     primary_path,
            #     backup_path
            if (attribute.endswith("path") and
                    attribute != "dynamic_backup_path"):
                data[attribute] = Path(
                    [self._link_from_dict(link, attribute) for link in value]
                )

        return data

    def _evc_from_dict(self, evc_dict):
        data = self._evc_dict_with_instances(evc_dict)
        data["table_group"] = self.table_group
        return EVC(self.controller, **data)

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

    def _link_from_dict(self, link_dict: dict, attribute: str) -> Link:
        """Return a Link object from python dict."""
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
                evc = self._evc_from_dict(circuit)
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
