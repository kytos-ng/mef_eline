# pylint: disable=protected-access
"""Main module of kytos/mef_eline Kytos Network Application.

NApp to provision circuits from user request.
"""
from threading import Lock

from flask import jsonify, request
from werkzeug.exceptions import (
    BadRequest,
    Conflict,
    Forbidden,
    MethodNotAllowed,
    NotFound,
    UnsupportedMediaType,
)

from kytos.core import KytosNApp, log, rest
from kytos.core.events import KytosEvent
from kytos.core.helpers import listen_to
from kytos.core.interface import TAG, UNI
from kytos.core.link import Link
from napps.kytos.mef_eline import settings
from napps.kytos.mef_eline.exceptions import InvalidPath
from napps.kytos.mef_eline.models import EVC, DynamicPathManager, Path
from napps.kytos.mef_eline.scheduler import CircuitSchedule, Scheduler
from napps.kytos.mef_eline.storehouse import StoreHouse
from napps.kytos.mef_eline.utils import emit_event, load_spec, validate


# pylint: disable=too-many-public-methods
class Main(KytosNApp):
    """Main class of amlight/mef_eline NApp.

    This class is the entry point for this napp.
    """

    spec = load_spec()

    def setup(self):
        """Replace the '__init__' method for the KytosNApp subclass.

        The setup method is automatically called by the controller when your
        application is loaded.

        So, if you have any setup routine, insert it here.
        """
        # object used to scheduler circuit events
        self.sched = Scheduler()

        # object to save and load circuits
        self.storehouse = StoreHouse(self.controller)

        # set the controller that will manager the dynamic paths
        DynamicPathManager.set_controller(self.controller)

        # dictionary of EVCs created. It acts as a circuit buffer.
        # Every create/update/delete must be synced to storehouse.
        self.circuits = {}

        self._lock = Lock()

        self.execute_as_loop(settings.DEPLOY_EVCS_INTERVAL)
        self.execution_rounds = 0
        self.load_all_evcs()

    def execute(self):
        """Execute once when the napp is running."""
        if self._lock.locked():
            return
        log.debug("Starting consistency routine")
        with self._lock:
            self.execute_consistency()
        log.debug("Finished consistency routine")

    def execute_consistency(self):
        """Execute consistency routine."""
        self.execution_rounds += 1
        stored_circuits = self.storehouse.get_data().copy()
        for circuit in tuple(self.circuits.values()):
            stored_circuits.pop(circuit.id, None)
            if (
                circuit.is_enabled()
                and not circuit.is_active()
                and not circuit.lock.locked()
            ):
                if circuit.check_traces():
                    log.info(f"{circuit} enabled but inactive - activating")
                    with circuit.lock:
                        circuit.activate()
                        circuit.sync()
                else:
                    if self.execution_rounds > settings.WAIT_FOR_OLD_PATH:
                        log.info(f"{circuit} enabled but inactive - redeploy")
                        with circuit.lock:
                            circuit.deploy()
        for circuit_id in stored_circuits:
            log.info(f"EVC found in storehouse but unloaded {circuit_id}")
            self._load_evc(stored_circuits[circuit_id])

    def shutdown(self):
        """Execute when your napp is unloaded.

        If you have some cleanup procedure, insert it here.
        """

    @rest("/v2/evc/", methods=["GET"])
    def list_circuits(self):
        """Endpoint to return circuits stored.

        If archived is set to True return all circuits, else only the ones
        not archived.
        """
        log.debug("list_circuits /v2/evc")
        archived = request.args.get("archived", False)
        circuits = self.storehouse.get_data()
        if not circuits:
            return jsonify({}), 200
        if archived:
            return jsonify(circuits), 200
        return (
            jsonify(
                {
                    circuit_id: circuit
                    for circuit_id, circuit in circuits.items()
                    if not circuit.get("archived", False)
                }
            ),
            200,
        )

    @rest("/v2/evc/<circuit_id>", methods=["GET"])
    def get_circuit(self, circuit_id):
        """Endpoint to return a circuit based on id."""
        log.debug("get_circuit /v2/evc/%s", circuit_id)
        circuits = self.storehouse.get_data()

        try:
            result = circuits[circuit_id]
        except KeyError:
            result = f"circuit_id {circuit_id} not found"
            log.debug("get_circuit result %s %s", result, 404)
            raise BadRequest(result) from KeyError
        status = 200
        log.debug("get_circuit result %s %s", result, status)
        return jsonify(result), status

    @rest("/v2/evc/", methods=["POST"])
    @validate(spec)
    def create_circuit(self, data):
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

        try:
            evc = self._evc_from_dict(data)
        except ValueError as exception:
            log.debug("create_circuit result %s %s", exception, 400)
            raise BadRequest(str(exception)) from BadRequest

        if evc.primary_path:
            try:
                evc.primary_path.is_valid(
                    evc.uni_a.interface.switch,
                    evc.uni_z.interface.switch,
                    bool(evc.circuit_scheduler),
                )
            except InvalidPath as exception:
                raise BadRequest(f"primary_path is not valid: {exception}")
        if evc.backup_path:
            try:
                evc.backup_path.is_valid(
                    evc.uni_a.interface.switch,
                    evc.uni_z.interface.switch,
                    bool(evc.circuit_scheduler),
                )
            except InvalidPath as exception:
                raise BadRequest(f"backup_path is not valid: {exception}")

        # verify duplicated evc
        if self._is_duplicated_evc(evc):
            result = "The EVC already exists."
            log.debug("create_circuit result %s %s", result, 409)
            raise Conflict(result)

        if (
            not evc.primary_path
            and evc.dynamic_backup_path is False
            and evc.uni_a.interface.switch != evc.uni_z.interface.switch
        ):
            result = "The EVC must have a primary path or allow dynamic paths."
            log.debug("create_circuit result %s %s", result, 400)
            raise BadRequest(result) from BadRequest

        # store circuit in dictionary
        self.circuits[evc.id] = evc

        # save circuit
        self.storehouse.save_evc(evc)

        # Schedule the circuit deploy
        self.sched.add(evc)

        # Circuit has no schedule, deploy now
        if not evc.circuit_scheduler:
            with evc.lock:
                evc.deploy()

        # Notify users
        event = KytosEvent(name="kytos.mef_eline.created", content=evc.as_dict())
        self.controller.buffers.app.put(event)

        result = {"circuit_id": evc.id}
        status = 201
        log.debug("create_circuit result %s %s", result, status)
        emit_event(self.controller, "created", evc_id=evc.id)
        return jsonify(result), status

    @rest("/v2/evc/<circuit_id>", methods=["PATCH"])
    def update(self, circuit_id):
        """Update a circuit based on payload.

        The EVC required attributes (name, uni_a, uni_z) can't be updated.
        """
        log.debug("update /v2/evc/%s", circuit_id)
        try:
            evc = self.circuits[circuit_id]
        except KeyError:
            result = f"circuit_id {circuit_id} not found"
            log.debug("update result %s %s", result, 404)
            raise NotFound(result) from NotFound

        if evc.archived:
            result = "Can't update archived EVC"
            log.debug("update result %s %s", result, 405)
            raise MethodNotAllowed(["GET"], result)

        try:
            data = request.get_json()
        except BadRequest:
            result = "The request body is not a well-formed JSON."
            log.debug("update result %s %s", result, 400)
            raise BadRequest(result) from BadRequest
        if data is None:
            result = "The request body mimetype is not application/json."
            log.debug("update result %s %s", result, 415)
            raise UnsupportedMediaType(result) from UnsupportedMediaType

        try:
            enable, redeploy = evc.update(**self._evc_dict_with_instances(data))
        except ValueError as exception:
            log.error(exception)
            log.debug("update result %s %s", exception, 400)
            raise BadRequest(str(exception)) from BadRequest

        if evc.is_active():
            if enable is False:  # disable if active
                with evc.lock:
                    evc.remove()
            elif redeploy is not None:  # redeploy if active
                with evc.lock:
                    evc.remove()
                    evc.deploy()
        else:
            if enable is True:  # enable if inactive
                with evc.lock:
                    evc.deploy()
        result = {evc.id: evc.as_dict()}
        status = 200

        log.debug("update result %s %s", result, status)
        emit_event(self.controller, "updated", evc_id=evc.id, data=data)
        return jsonify(result), status

    @rest("/v2/evc/<circuit_id>", methods=["DELETE"])
    def delete_circuit(self, circuit_id):
        """Remove a circuit.

        First, the flows are removed from the switches, and then the EVC is
        disabled.
        """
        log.debug("delete_circuit /v2/evc/%s", circuit_id)
        try:
            evc = self.circuits[circuit_id]
        except KeyError:
            result = f"circuit_id {circuit_id} not found"
            log.debug("delete_circuit result %s %s", result, 404)
            raise NotFound(result) from NotFound

        if evc.archived:
            result = f"Circuit {circuit_id} already removed"
            log.debug("delete_circuit result %s %s", result, 404)
            raise NotFound(result) from NotFound

        log.info("Removing %s", evc)
        evc.remove_current_flows()
        evc.deactivate()
        evc.disable()
        self.sched.remove(evc)
        evc.archive()
        evc.sync()
        log.info("EVC removed. %s", evc)
        result = {"response": f"Circuit {circuit_id} removed"}
        status = 200

        log.debug("delete_circuit result %s %s", result, status)
        emit_event(self.controller, "deleted", evc_id=evc.id)
        return jsonify(result), status

    @rest("v2/evc/<circuit_id>/metadata", methods=["GET"])
    def get_metadata(self, circuit_id):
        """Get metadata from an EVC."""
        try:
            return jsonify({"metadata": self.circuits[circuit_id].metadata}), 200
        except KeyError as error:
            raise NotFound(f"circuit_id {circuit_id} not found.") from error

    @rest("v2/evc/<circuit_id>/metadata", methods=["POST"])
    def add_metadata(self, circuit_id):
        """Add metadata to an EVC."""
        try:
            metadata = request.get_json()
            content_type = request.content_type
        except BadRequest as error:
            result = "The request body is not a well-formed JSON."
            raise BadRequest(result) from error
        if content_type is None:
            result = "The request body is empty."
            raise BadRequest(result)
        if metadata is None:
            if content_type != "application/json":
                result = (
                    "The content type must be application/json "
                    f"(received {content_type})."
                )
            else:
                result = "Metadata is empty."
            raise UnsupportedMediaType(result)

        try:
            evc = self.circuits[circuit_id]
        except KeyError as error:
            raise NotFound(f"circuit_id {circuit_id} not found.") from error

        evc.extend_metadata(metadata)
        evc.sync()
        return jsonify("Operation successful"), 201

    @rest("v2/evc/<circuit_id>/metadata/<key>", methods=["DELETE"])
    def delete_metadata(self, circuit_id, key):
        """Delete metadata from an EVC."""
        try:
            evc = self.circuits[circuit_id]
        except KeyError as error:
            raise NotFound(f"circuit_id {circuit_id} not found.") from error

        evc.remove_metadata(key)
        evc.sync()
        return jsonify("Operation successful"), 200

    @rest("/v2/evc/<circuit_id>/redeploy", methods=["PATCH"])
    def redeploy(self, circuit_id):
        """Endpoint to force the redeployment of an EVC."""
        log.debug("redeploy /v2/evc/%s/redeploy", circuit_id)
        try:
            evc = self.circuits[circuit_id]
        except KeyError:
            result = f"circuit_id {circuit_id} not found"
            raise NotFound(result) from NotFound
        if evc.is_enabled():
            with evc.lock:
                evc.remove_current_flows()
                evc.deploy()
            result = {"response": f"Circuit {circuit_id} redeploy received."}
            status = 202
        else:
            result = {"response": f"Circuit {circuit_id} is disabled."}
            status = 409

        return jsonify(result), status

    @rest("/v2/evc/schedule", methods=["GET"])
    def list_schedules(self):
        """Endpoint to return all schedules stored for all circuits.

        Return a JSON with the following template:
        [{"schedule_id": <schedule_id>,
         "circuit_id": <circuit_id>,
         "schedule": <schedule object>}]
        """
        log.debug("list_schedules /v2/evc/schedule")
        circuits = self.storehouse.get_data().values()
        if not circuits:
            result = {}
            status = 200
            return jsonify(result), status

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
        return jsonify(result), status

    @rest("/v2/evc/schedule/", methods=["POST"])
    def create_schedule(self):
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

        json_data = self._json_from_request("create_schedule")
        try:
            circuit_id = json_data["circuit_id"]
        except TypeError:
            result = "The payload should have a dictionary."
            log.debug("create_schedule result %s %s", result, 400)
            raise BadRequest(result) from BadRequest
        except KeyError:
            result = "Missing circuit_id."
            log.debug("create_schedule result %s %s", result, 400)
            raise BadRequest(result) from BadRequest

        try:
            schedule_data = json_data["schedule"]
        except KeyError:
            result = "Missing schedule data."
            log.debug("create_schedule result %s %s", result, 400)
            raise BadRequest(result) from BadRequest

        # Get EVC from circuits buffer
        circuits = self._get_circuits_buffer()

        # get the circuit
        evc = circuits.get(circuit_id)

        # get the circuit
        if not evc:
            result = f"circuit_id {circuit_id} not found"
            log.debug("create_schedule result %s %s", result, 404)
            raise NotFound(result) from NotFound
        # Can not modify circuits deleted and archived
        if evc.archived:
            result = f"Circuit {circuit_id} is archived. Update is forbidden."
            log.debug("create_schedule result %s %s", result, 403)
            raise Forbidden(result) from Forbidden

        # new schedule from dict
        new_schedule = CircuitSchedule.from_dict(schedule_data)

        # If there is no schedule, create the list
        if not evc.circuit_scheduler:
            evc.circuit_scheduler = []

        # Add the new schedule
        evc.circuit_scheduler.append(new_schedule)

        # Add schedule job
        self.sched.add_circuit_job(evc, new_schedule)

        # save circuit to storehouse
        evc.sync()

        result = new_schedule.as_dict()
        status = 201

        log.debug("create_schedule result %s %s", result, status)
        return jsonify(result), status

    @rest("/v2/evc/schedule/<schedule_id>", methods=["PATCH"])
    def update_schedule(self, schedule_id):
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
        log.debug("update_schedule /v2/evc/schedule/%s", schedule_id)

        # Try to find a circuit schedule
        evc, found_schedule = self._find_evc_by_schedule_id(schedule_id)

        # Can not modify circuits deleted and archived
        if not found_schedule:
            result = f"schedule_id {schedule_id} not found"
            log.debug("update_schedule result %s %s", result, 404)
            raise NotFound(result) from NotFound
        if evc.archived:
            result = f"Circuit {evc.id} is archived. Update is forbidden."
            log.debug("update_schedule result %s %s", result, 403)
            raise Forbidden(result) from Forbidden

        data = self._json_from_request("update_schedule")

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
        # Save EVC to the storehouse
        evc.sync()

        result = new_schedule.as_dict()
        status = 200

        log.debug("update_schedule result %s %s", result, status)
        return jsonify(result), status

    @rest("/v2/evc/schedule/<schedule_id>", methods=["DELETE"])
    def delete_schedule(self, schedule_id):
        """Remove a circuit schedule.

        Remove the Schedule from EVC.
        Remove the Schedule from cron job.
        Save the EVC to the Storehouse.
        """
        log.debug("delete_schedule /v2/evc/schedule/%s", schedule_id)
        evc, found_schedule = self._find_evc_by_schedule_id(schedule_id)

        # Can not modify circuits deleted and archived
        if not found_schedule:
            result = f"schedule_id {schedule_id} not found"
            log.debug("delete_schedule result %s %s", result, 404)
            raise NotFound(result)

        if evc.archived:
            result = f"Circuit {evc.id} is archived. Update is forbidden."
            log.debug("delete_schedule result %s %s", result, 403)
            raise Forbidden(result)

        # Remove the old schedule
        evc.circuit_scheduler.remove(found_schedule)

        # Cancel all schedule jobs
        self.sched.cancel_job(found_schedule.id)
        # Save EVC to the storehouse
        evc.sync()

        result = "Schedule removed"
        status = 200

        log.debug("delete_schedule result %s %s", result, status)
        return jsonify(result), status

    def _is_duplicated_evc(self, evc):
        """Verify if the circuit given is duplicated with the stored evcs.

        Args:
            evc (EVC): circuit to be analysed.

        Returns:
            boolean: True if the circuit is duplicated, otherwise False.

        """
        for circuit in tuple(self.circuits.values()):
            if not circuit.archived and circuit.shares_uni(evc):
                return True
        return False

    @listen_to("kytos/topology.link_up")
    def handle_link_up(self, event):
        """Change circuit when link is up or end_maintenance."""
        log.debug("Event handle_link_up %s", event)
        for evc in self.circuits.values():
            if evc.is_enabled() and not evc.archived:
                with evc.lock:
                    evc.handle_link_up(event.content["link"])

    @listen_to("kytos/topology.link_down")
    def handle_link_down(self, event):
        """Change circuit when link is down or under_mantenance."""
        log.debug("Event handle_link_down %s", event)
        for evc in self.circuits.values():
            with evc.lock:
                if evc.is_affected_by_link(event.content["link"]):
                    log.debug(f"Handling evc {evc.id} on link down")
                    if evc.handle_link_down():
                        emit_event(
                            self.controller,
                            "redeployed_link_down",
                            evc_id=evc.id,
                        )
                    else:
                        emit_event(
                            self.controller,
                            "error_redeploy_link_down",
                            evc_id=evc.id,
                        )

    def load_all_evcs(self):
        """Try to load all EVCs on startup."""
        for circuit_id, circuit in self.storehouse.get_data().items():
            if circuit_id not in self.circuits:
                self._load_evc(circuit)

    def _load_evc(self, circuit_dict):
        """Load one EVC from storehouse to memory."""
        try:
            evc = self._evc_from_dict(circuit_dict)
        except ValueError as exception:
            log.error(
                f'Could not load EVC {circuit_dict["id"]} ' f"because {exception}"
            )
            return None

        if evc.archived:
            return None
        evc.deactivate()
        evc.sync()
        self.circuits.setdefault(evc.id, evc)
        self.sched.add(evc)
        return evc

    @listen_to("kytos/flow_manager.flow.error")
    def handle_flow_mod_error(self, event):
        """Handle flow mod errors related to an EVC."""
        flow = event.content["flow"]
        command = event.content.get("error_command")
        if command != "add":
            return
        evc = self.circuits.get(EVC.get_id_from_cookie(flow.cookie))
        if evc:
            evc.remove_current_flows()

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
                except ValueError:
                    result = "Error creating UNI: Invalid value"
                    raise BadRequest(result) from BadRequest

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
                data[attribute] = [self._link_from_dict(link) for link in value]

            # Ex: current_path,
            #     primary_path,
            #     backup_path
            if "path" in attribute and attribute != "dynamic_backup_path":
                data[attribute] = Path([self._link_from_dict(link) for link in value])

        return data

    def _evc_from_dict(self, evc_dict):
        data = self._evc_dict_with_instances(evc_dict)
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

        tag_dict = uni_dict.get("tag", None)
        if tag_dict:
            tag = TAG.from_dict(tag_dict)
        else:
            tag = None
        uni = UNI(interface, tag)

        return uni

    def _link_from_dict(self, link_dict):
        """Return a Link object from python dict."""
        id_a = link_dict.get("endpoint_a").get("id")
        id_b = link_dict.get("endpoint_b").get("id")

        endpoint_a = self.controller.get_interface_by_id(id_a)
        endpoint_b = self.controller.get_interface_by_id(id_b)

        link = Link(endpoint_a, endpoint_b)
        if "metadata" in link_dict:
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

        If the buffer is empty, try to load data from storehouse.
        """
        if not self.circuits:
            # Load storehouse circuits to buffer
            circuits = self.storehouse.get_data()
            for c_id, circuit in circuits.items():
                evc = self._evc_from_dict(circuit)
                self.circuits[c_id] = evc
        return self.circuits

    @staticmethod
    def _json_from_request(caller):
        """Return a json from request.

        If it was not possible to get a json from the request, log, for debug,
        who was the caller and the error that ocurred, and raise an
        Exception.
        """
        try:
            json_data = request.get_json()
        except ValueError as exception:
            log.error(exception)
            log.debug(f"{caller} result {exception} 400")
            raise BadRequest(str(exception)) from BadRequest
        except BadRequest:
            result = "The request is not a valid JSON."
            log.debug(f"{caller} result {result} 400")
            raise BadRequest(result) from BadRequest
        if json_data is None:
            result = "Content-Type must be application/json"
            log.debug(f"{caller} result {result} 415")
            raise UnsupportedMediaType(result)
        return json_data
