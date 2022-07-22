"""Classes used in the main application."""  # pylint: disable=too-many-lines
from datetime import datetime
from threading import Lock
from uuid import uuid4

import requests
from glom import glom

from kytos.core import log
from kytos.core.common import EntityStatus, GenericEntity
from kytos.core.exceptions import KytosNoTagAvailableError
from kytos.core.helpers import get_time, now
from kytos.core.interface import UNI
from napps.kytos.mef_eline import controllers, settings
from napps.kytos.mef_eline.exceptions import FlowModException, InvalidPath
from napps.kytos.mef_eline.utils import (
    compare_endpoint_trace,
    emit_event,
    notify_link_available_tags,
)
from .path import Path, DynamicPathManager


class EVCBase(GenericEntity):
    """Class to represent a circuit."""

    read_only_attributes = [
        "creation_time",
        "active",
        "current_path",
        "_id",
        "archived",
    ]
    attributes_requiring_redeploy = [
        "primary_path",
        "backup_path",
        "dynamic_backup_path",
        "queue_id",
        "priority",
    ]
    required_attributes = ["name", "uni_a", "uni_z"]

    def __init__(self, controller, **kwargs):
        """Create an EVC instance with the provided parameters.

        Args:
            id(str): EVC identifier. Whether it's None an ID will be genereted.
                     Only the first 14 bytes passed will be used.
            name: represents an EVC name.(Required)
            uni_a (UNI): Endpoint A for User Network Interface.(Required)
            uni_z (UNI): Endpoint Z for User Network Interface.(Required)
            start_date(datetime|str): Date when the EVC was registred.
                                      Default is now().
            end_date(datetime|str): Final date that the EVC will be fineshed.
                                    Default is None.
            bandwidth(int): Bandwidth used by EVC instance. Default is 0.
            primary_links(list): Primary links used by evc. Default is []
            backup_links(list): Backups links used by evc. Default is []
            current_path(list): Circuit being used at the moment if this is an
                                active circuit. Default is [].
            primary_path(list): primary circuit offered to user IF one or more
                                links were provided. Default is [].
            backup_path(list): backup circuit offered to the user IF one or
                               more links were provided. Default is [].
            dynamic_backup_path(bool): Enable computer backup path dynamically.
                                       Dafault is False.
            creation_time(datetime|str): datetime when the circuit should be
                                         activated. default is now().
            enabled(Boolean): attribute to indicate the administrative state;
                              default is False.
            active(Boolean): attribute to indicate the operational state;
                             default is False.
            archived(Boolean): indicate the EVC has been deleted and is
                               archived; default is False.
            owner(str): The EVC owner. Default is None.
            priority(int): Service level provided in the request. Default is 0.

        Raises:
            ValueError: raised when object attributes are invalid.

        """
        self._validate(**kwargs)
        super().__init__()

        # required attributes
        self._id = kwargs.get("id", uuid4().hex)[:14]
        self.uni_a = kwargs.get("uni_a")
        self.uni_z = kwargs.get("uni_z")
        self.name = kwargs.get("name")

        # optional attributes
        self.start_date = get_time(kwargs.get("start_date")) or now()
        self.end_date = get_time(kwargs.get("end_date")) or None
        self.queue_id = kwargs.get("queue_id", None)

        self.bandwidth = kwargs.get("bandwidth", 0)
        self.primary_links = Path(kwargs.get("primary_links", []))
        self.backup_links = Path(kwargs.get("backup_links", []))
        self.current_path = Path(kwargs.get("current_path", []))
        self.next_path = Path(kwargs.get("next_path", []))
        self.primary_path = Path(kwargs.get("primary_path", []))
        self.backup_path = Path(kwargs.get("backup_path", []))
        self.dynamic_backup_path = kwargs.get("dynamic_backup_path", False)
        self.creation_time = get_time(kwargs.get("creation_time")) or now()
        self.owner = kwargs.get("owner", None)
        self.priority = kwargs.get("priority", -1)
        self.circuit_scheduler = kwargs.get("circuit_scheduler", [])

        self.current_links_cache = set()
        self.primary_links_cache = set()
        self.backup_links_cache = set()

        self.lock = Lock()

        self.archived = kwargs.get("archived", False)

        self.metadata = kwargs.get("metadata", {})

        self._controller = controller
        self._mongo_controller = controllers.ELineController()

        if kwargs.get("active", False):
            self.activate()
        else:
            self.deactivate()

        if kwargs.get("enabled", False):
            self.enable()
        else:
            self.disable()

        # datetime of user request for a EVC (or datetime when object was
        # created)
        self.request_time = kwargs.get("request_time", now())
        # dict with the user original request (input)
        self._requested = kwargs

    def sync(self):
        """Sync this EVC in the MongoDB."""
        self._mongo_controller.upsert_evc(self.as_dict())

    def update(self, **kwargs):
        """Update evc attributes.

        This method will raises an error trying to change the following
        attributes: [name, uni_a and uni_z]

        Returns:
            the values for enable and a redeploy attribute, if exists and None
            otherwise
        Raises:
            ValueError: message with error detail.

        """
        enable, redeploy = (None, None)
        uni_a = kwargs.get("uni_a") or self.uni_a
        uni_z = kwargs.get("uni_z") or self.uni_z
        for attribute, value in kwargs.items():
            if attribute in self.read_only_attributes:
                raise ValueError(f"{attribute} can't be updated.")
            if not hasattr(self, attribute):
                raise ValueError(f'The attribute "{attribute}" is invalid.')
            if attribute in ("primary_path", "backup_path"):
                try:
                    value.is_valid(
                        uni_a.interface.switch, uni_z.interface.switch
                    )
                except InvalidPath as exception:
                    raise ValueError(
                        f"{attribute} is not a " f"valid path: {exception}"
                    )
        for attribute, value in kwargs.items():
            if attribute in ("enable", "enabled"):
                if value:
                    self.enable()
                else:
                    self.disable()
                enable = value
            else:
                setattr(self, attribute, value)
                if attribute in self.attributes_requiring_redeploy:
                    redeploy = value
        self.sync()
        return enable, redeploy

    def __repr__(self):
        """Repr method."""
        return f"EVC({self._id}, {self.name})"

    def _validate(self, **kwargs):
        """Do Basic validations.

        Verify required attributes: name, uni_a, uni_z
        Verify if the attributes uni_a and uni_z are valid.

        Raises:
            ValueError: message with error detail.

        """
        for attribute in self.required_attributes:

            if attribute not in kwargs:
                raise ValueError(f"{attribute} is required.")

            if "uni" in attribute:
                uni = kwargs.get(attribute)
                if not isinstance(uni, UNI):
                    raise ValueError(f"{attribute} is an invalid UNI.")

                if not uni.is_valid():
                    tag = uni.user_tag.value
                    message = f"VLAN tag {tag} is not available in {attribute}"
                    raise ValueError(message)

    def __eq__(self, other):
        """Override the default implementation."""
        if not isinstance(other, EVC):
            return False

        attrs_to_compare = ["name", "uni_a", "uni_z", "owner", "bandwidth"]
        for attribute in attrs_to_compare:
            if getattr(other, attribute) != getattr(self, attribute):
                return False
        return True

    def shares_uni(self, other):
        """Check if two EVCs share an UNI."""
        if other.uni_a in (self.uni_a, self.uni_z) or other.uni_z in (
            self.uni_a,
            self.uni_z,
        ):
            return True
        return False

    def as_dict(self):
        """Return a dictionary representing an EVC object."""
        evc_dict = {
            "id": self.id,
            "name": self.name,
            "uni_a": self.uni_a.as_dict(),
            "uni_z": self.uni_z.as_dict(),
        }

        time_fmt = "%Y-%m-%dT%H:%M:%S"

        evc_dict["start_date"] = self.start_date
        if isinstance(self.start_date, datetime):
            evc_dict["start_date"] = self.start_date.strftime(time_fmt)

        evc_dict["end_date"] = self.end_date
        if isinstance(self.end_date, datetime):
            evc_dict["end_date"] = self.end_date.strftime(time_fmt)

        evc_dict["queue_id"] = self.queue_id
        evc_dict["bandwidth"] = self.bandwidth
        evc_dict["primary_links"] = self.primary_links.as_dict()
        evc_dict["backup_links"] = self.backup_links.as_dict()
        evc_dict["current_path"] = self.current_path.as_dict()
        evc_dict["primary_path"] = self.primary_path.as_dict()
        evc_dict["backup_path"] = self.backup_path.as_dict()
        evc_dict["dynamic_backup_path"] = self.dynamic_backup_path
        evc_dict["metadata"] = self.metadata

        # if self._requested:
        #     request_dict = self._requested.copy()
        #     request_dict['uni_a'] = request_dict['uni_a'].as_dict()
        #     request_dict['uni_z'] = request_dict['uni_z'].as_dict()
        #     request_dict['circuit_scheduler'] = self.circuit_scheduler
        #     evc_dict['_requested'] = request_dict

        evc_dict["request_time"] = self.request_time
        if isinstance(self.request_time, datetime):
            evc_dict["request_time"] = self.request_time.strftime(time_fmt)

        time = self.creation_time.strftime(time_fmt)
        evc_dict["creation_time"] = time

        evc_dict["owner"] = self.owner
        evc_dict["circuit_scheduler"] = [
            sc.as_dict() for sc in self.circuit_scheduler
        ]

        evc_dict["active"] = self.is_active()
        evc_dict["enabled"] = self.is_enabled()
        evc_dict["archived"] = self.archived
        evc_dict["priority"] = self.priority

        return evc_dict

    @property
    def id(self):  # pylint: disable=invalid-name
        """Return this EVC's ID."""
        return self._id

    def archive(self):
        """Archive this EVC on deletion."""
        self.archived = True


# pylint: disable=fixme, too-many-public-methods
class EVCDeploy(EVCBase):
    """Class to handle the deploy procedures."""

    def create(self):
        """Create a EVC."""

    def discover_new_paths(self):
        """Discover new paths to satisfy this circuit and deploy it."""
        return DynamicPathManager.get_best_paths(self)

    def discover_disjoint_paths(self):
        """Discover disjoint paths to satisfy this circuit."""
        return DynamicPathManager.get_disjoint_paths(self)

    def change_path(self):
        """Change EVC path."""

    def reprovision(self):
        """Force the EVC (re-)provisioning."""

    def is_affected_by_link(self, link):
        """Return True if this EVC has the given link on its current path."""
        return link in self.current_path

    def link_affected_by_interface(self, interface):
        """Return True if this EVC has the given link on its current path."""
        return self.current_path.link_affected_by_interface(interface)

    def is_backup_path_affected_by_link(self, link):
        """Return True if the backup path of this EVC uses the given link."""
        return link in self.backup_path

    # pylint: disable=invalid-name
    def is_primary_path_affected_by_link(self, link):
        """Return True if the primary path of this EVC uses the given link."""
        return link in self.primary_path

    def is_using_primary_path(self):
        """Verify if the current deployed path is self.primary_path."""
        return self.primary_path and (self.current_path == self.primary_path)

    def is_using_backup_path(self):
        """Verify if the current deployed path is self.backup_path."""
        return self.backup_path and (self.current_path == self.backup_path)

    def is_using_dynamic_path(self):
        """Verify if the current deployed path is a dynamic path."""
        if (
            self.current_path
            and not self.is_using_primary_path()
            and not self.is_using_backup_path()
            and self.current_path.status == EntityStatus.UP
        ):
            return True
        return False

    def deploy_to_backup_path(self):
        """Deploy the backup path into the datapaths of this circuit.

        If the backup_path attribute is valid and up, this method will try to
        deploy this backup_path.

        If everything fails and dynamic_backup_path is True, then tries to
        deploy a dynamic path.
        """
        # TODO: Remove flows from current (cookies)
        if self.is_using_backup_path():
            # TODO: Log to say that cannot move backup to backup
            return True

        success = False
        if self.backup_path.status is EntityStatus.UP:
            success = self.deploy_to_path(self.backup_path)

        if success:
            return True

        if (
            self.dynamic_backup_path
            or self.uni_a.interface.switch == self.uni_z.interface.switch
        ):
            return self.deploy_to_path()

        return False

    def deploy_to_primary_path(self):
        """Deploy the primary path into the datapaths of this circuit.

        If the primary_path attribute is valid and up, this method will try to
        deploy this primary_path.
        """
        # TODO: Remove flows from current (cookies)
        if self.is_using_primary_path():
            # TODO: Log to say that cannot move primary to primary
            return True

        if self.primary_path.status is EntityStatus.UP:
            return self.deploy_to_path(self.primary_path)
        return False

    def deploy(self):
        """Deploy EVC to best path.

        Best path can be the primary path, if available. If not, the backup
        path, and, if it is also not available, a dynamic path.
        """
        if self.archived:
            return False
        self.enable()
        success = self.deploy_to_primary_path()
        if not success:
            success = self.deploy_to_backup_path()

        if success:
            emit_event(self._controller, "deployed", evc_id=self.id)
        return success

    @staticmethod
    def get_path_status(path):
        """Check for the current status of a path.

        If any link in this path is down, the path is considered down.
        """
        if not path:
            return EntityStatus.DISABLED

        for link in path:
            if link.status is not EntityStatus.UP:
                return link.status
        return EntityStatus.UP

    #    def discover_new_path(self):
    #        # TODO: discover a new path to satisfy this circuit and deploy

    def remove(self):
        """Remove EVC path and disable it."""
        self.remove_current_flows()
        self.remove_flows_path(self.next_path)
        self.disable()
        self.sync()
        emit_event(self._controller, "undeployed", evc_id=self.id)

    def remove_current_flows(self, current_path=None, force=True):
        """Remove all flows from current path."""
        switches = set()

        switches.add(self.uni_a.interface.switch)
        switches.add(self.uni_z.interface.switch)
        if not current_path:
            current_path = self.current_path
        for link in current_path:
            switches.add(link.endpoint_a.switch)
            switches.add(link.endpoint_b.switch)

        match = {
            "cookie": self.get_cookie(),
            "cookie_mask": 18446744073709551615,
        }

        for switch in switches:
            try:
                self._send_flow_mods(switch, [match], 'delete', force=force)
            except FlowModException:
                log.error(
                    f"Error removing flows from switch {switch.id} for"
                    f"EVC {self}"
                )

        current_path.make_vlans_available()
        for link in current_path:
            notify_link_available_tags(self._controller, link)
        self.current_path = Path([])
        self.deactivate()
        self.sync()

    def _remove_flows_uni(self, switch, endpoint, vlan_id, force=False):
        """Remove flow for UNI."""
        flow = {
            "cookie": self.get_cookie(),
            "match": {
                "in_port": endpoint.port_number,
                "dl_vlan": vlan_id,
            },
        }
        try:
            self._send_flow_mods(switch, [flow], 'delete', force=force)
        except FlowModException:
            log.error(
                f"Error removing failover flows from switch {switch.id}"
                f" for {self}"
            )

    def remove_flows_path(self, path=None, force=True, skip_nni=False):
        """Remove all flows from next path."""
        if path is None:
            path = self.next_path

        if not path:
            return

        for incoming, outgoing in self.links_zipped(path):
            in_vlan = incoming.get_metadata("s_vlan").value
            # incoming direction
            flow_in = {
                "cookie": self.get_cookie(),
                "match": {
                    "in_port": incoming.endpoint_b.port_number,
                    "dl_vlan": incoming.get_metadata("s_vlan").value,
                },
            }
            # outgoing direction
            flow_out = {
                "cookie": self.get_cookie(),
                "match": {
                    "in_port": outgoing.endpoint_a.port_number,
                    "dl_vlan": outgoing.get_metadata("s_vlan").value,
                },
            }
            try:
                self._send_flow_mods(incoming.endpoint_b.switch, [flow_in, flow_out], 'delete', force=force)
            except FlowModException:
                log.error(
                    f"Error removing failover flows from switch {switch.id}"
                    f" for {self}"
                )

        if not skip_nni:
            self._remove_flows_uni(
                self.uni_a.interface.switch,
                path[0].endpoint_a,
                path[0].get_metadata("s_vlan").value,
                force=force,
            )
            self._remove_flows_uni(
                self.uni_z.interface.switch,
                path[-1].endpoint_b,
                path[-1].get_metadata("s_vlan").value,
                force=force,
            )

        path.make_vlans_available()
        for link in path:
            notify_link_available_tags(self._controller, link)

    @staticmethod
    def links_zipped(path=None):
        """Return an iterator which yields pairs of links in order."""
        if not path:
            return []
        return zip(path[:-1], path[1:])

    def should_deploy(self, path=None):
        """Verify if the circuit should be deployed."""
        if not path:
            log.debug("Path is empty.")
            return False

        if not self.is_enabled():
            log.debug(f"{self} is disabled.")
            return False

        if not self.is_active():
            log.debug(f"{self} will be deployed.")
            return True

        return False

    def deploy_to_path(self, path=None):
        """Install the flows for this circuit.

        Procedures to deploy:

        0. Remove current flows installed
        1. Decide if will deploy "path" or discover a new path
        2. Choose vlan
        3. Install NNI flows
        4. Install UNI flows
        5. Activate
        6. Update current_path
        7. Update links caches(primary, current, backup)

        """
        self.remove_current_flows()
        use_path = path
        if self.should_deploy(use_path):
            try:
                use_path.choose_vlans()
                for link in use_path:
                    notify_link_available_tags(self._controller, link)
            except KytosNoTagAvailableError:
                use_path = None
        else:
            for use_path in self.discover_new_paths():
                if use_path is None:
                    continue
                try:
                    use_path.choose_vlans()
                    for link in use_path:
                        notify_link_available_tags(self._controller, link)
                    break
                except KytosNoTagAvailableError:
                    pass
            else:
                use_path = None

        try:
            if use_path:
                self._install_nni_flows(use_path)
                self._install_uni_flows(use_path)
            elif self.uni_a.interface.switch == self.uni_z.interface.switch:
                use_path = Path()
                self._install_direct_uni_flows()
            else:
                log.warn(
                    f"{self} was not deployed. " "No available path was found."
                )
                return False
        except FlowModException:
            log.error(f"Error deploying EVC {self} when calling flow_manager.")
            self.remove_current_flows(use_path)
            return False
        self.activate()
        self.current_path = use_path
        self.sync()
        log.info(f"{self} was deployed.")
        return True

    def setup_next_path(self, path=None):
        """Install the failover flows for this circuit (next path).

        Procedures to deploy:

        0. Remove flows currently installed for next_path (if any)
        1. Discover a disjoint path from current_path (if dynamic)
        2. Choose vlans
        3. Install NNI flows
        4. Install UNI egress flows
        5. Update next_path

        """
        # Intra-switch EVCs have nothing to be done
        if self.uni_a.interface.switch == self.uni_z.interface.switch:
            return True

        # For not only setup next path for totally dynamic EVCs
        if self.primary_path or self.backup_path or not self.dynamic_backup_path:
            return False

        self.remove_flows_path(self.next_path)
        use_path = path
        if use_path:
            try:
                use_path.choose_vlans()
                for link in use_path:
                    notify_link_available_tags(self._controller, link)
            except KytosNoTagAvailableError:
                use_path = None
        else:
            for use_path in self.discover_disjoint_paths():
                if use_path is None:
                    continue
                if use_path == self.next_path:
                    return True
                try:
                    use_path.choose_vlans()
                    for link in use_path:
                        notify_link_available_tags(self._controller, link)
                    break
                except KytosNoTagAvailableError:
                    pass
            else:
                use_path = None

        #log.info("setup_next_path use_path=%s" % use_path)
        try:
            if use_path:
                self._install_nni_flows(use_path)
                self._install_uni_flows(use_path, skip_in=True)
            else:
                log.warn(
                    f"Failover path for {self} was not deployed. "
                    "No available path was found."
                )
                return False
        except FlowModException:
            log.error(
                f"Error deploying failover path for {self}. "
                "Error on flow_manager."
            )
            self.remove_flows_path(use_path)
            return False
        self.next_path = use_path
        self.sync()
        #log.info(f"Failover path for {self} was deployed.")
        return True

    def deploy_next_path(self, delay_sync=False):
        """Install the flows to make the failover path as the current path.

        Procedures to deploy:

        1. Install UNI ingress flows
        2. Remove flows from current_path
        3. Update current_path with the next path
        4. Setup a new next path (?)
        """
        #log.info("deploy_next_path start %s" % self.id)
        use_path = self.next_path
        try:
            if use_path:
                self._install_uni_flows(use_path, skip_out=True, using_event=True)
            else:
                log.warn(
                    f"Failover path for {self} was not deployed. "
                    "No available path was found."
                )
                return False
        except FlowModException:
            log.error(
                f"Error deploying failover path for {self}. "
                "Error on flow_manager."
            )
            self.remove_flows_path(use_path)
            return False
        prev_path = self.current_path
        self.current_path = use_path
        #self.remove_flows_path(prev_path)
        self.next_path = Path()
        if not delay_sync:
            self.sync()
        #log.info(f"{self} was deployed using next_path.")
        #log.info("deploy_next_path end %s" % self.id)
         return True

    def _install_direct_uni_flows(self):
        """Install flows connecting two UNIs.

        This case happens when the circuit is between UNIs in the
        same switch.
        """
        vlan_a = self.uni_a.user_tag.value if self.uni_a.user_tag else None
        vlan_z = self.uni_z.user_tag.value if self.uni_z.user_tag else None

        flow_mod_az = self._prepare_flow_mod(
            self.uni_a.interface, self.uni_z.interface, self.queue_id
        )
        flow_mod_za = self._prepare_flow_mod(
            self.uni_z.interface, self.uni_a.interface, self.queue_id
        )

        if vlan_a and vlan_z:
            flow_mod_az["match"]["dl_vlan"] = vlan_a
            flow_mod_za["match"]["dl_vlan"] = vlan_z
            flow_mod_az["actions"].insert(
                0, {"action_type": "set_vlan", "vlan_id": vlan_z}
            )
            flow_mod_za["actions"].insert(
                0, {"action_type": "set_vlan", "vlan_id": vlan_a}
            )
        elif vlan_a:
            flow_mod_az["match"]["dl_vlan"] = vlan_a
            flow_mod_az["actions"].insert(0, {"action_type": "pop_vlan"})
            flow_mod_za["actions"].insert(
                0, {"action_type": "set_vlan", "vlan_id": vlan_a}
            )
        elif vlan_z:
            flow_mod_za["match"]["dl_vlan"] = vlan_z
            flow_mod_za["actions"].insert(0, {"action_type": "pop_vlan"})
            flow_mod_az["actions"].insert(
                0, {"action_type": "set_vlan", "vlan_id": vlan_z}
            )
        self._send_flow_mods(
            self.uni_a.interface.switch, [flow_mod_az, flow_mod_za]
        )

    def _install_nni_flows(self, path=None):
        """Install NNI flows."""
        for incoming, outcoming in self.links_zipped(path):
            in_vlan = incoming.get_metadata("s_vlan").value
            out_vlan = outcoming.get_metadata("s_vlan").value

            flows = []
            # Flow for one direction
            flows.append(
                self._prepare_nni_flow(
                    incoming.endpoint_b,
                    outcoming.endpoint_a,
                    in_vlan,
                    out_vlan,
                    queue_id=self.queue_id,
                )
            )

            # Flow for the other direction
            flows.append(
                self._prepare_nni_flow(
                    outcoming.endpoint_a,
                    incoming.endpoint_b,
                    out_vlan,
                    in_vlan,
                    queue_id=self.queue_id,
                )
            )
            self._send_flow_mods(incoming.endpoint_b.switch, flows)

    def prepare_uni_flows(self, path=None, skip_in=False, skip_out=False):
        """Prepare flows to install UNIs."""
        uni_flows = []
        if not path:
            #log_info("install uni flows without path.")
            return uni_flows

        # Determine VLANs
        in_vlan_a = self.uni_a.user_tag.value if self.uni_a.user_tag else None
        out_vlan_a = path[0].get_metadata("s_vlan").value

        in_vlan_z = self.uni_z.user_tag.value if self.uni_z.user_tag else None
        out_vlan_z = path[-1].get_metadata("s_vlan").value

        # Flows for the first UNI
        flows_a = []

        # Flow for one direction, pushing the service tag
        if not skip_in:
            push_flow = self._prepare_push_flow(
                self.uni_a.interface,
                path[0].endpoint_a,
                in_vlan_a,
                out_vlan_a,
                in_vlan_z,
                queue_id=self.queue_id,
            )
            flows_a.append(push_flow)

        # Flow for the other direction, popping the service tag
        if not skip_out:
            pop_flow = self._prepare_pop_flow(
                path[0].endpoint_a,
                self.uni_a.interface,
                out_vlan_a,
                queue_id=self.queue_id,
            )
            flows_a.append(pop_flow)

        uni_flows.append((self.uni_a.interface.switch.id, flows_a))

        # Flows for the second UNI
        flows_z = []

        # Flow for one direction, pushing the service tag
        if not skip_in:
            push_flow = self._prepare_push_flow(
                self.uni_z.interface,
                path[-1].endpoint_b,
                in_vlan_z,
                out_vlan_z,
                in_vlan_a,
                queue_id=self.queue_id,
            )
            flows_z.append(push_flow)

        # Flow for the other direction, popping the service tag
        if not skip_out:
            pop_flow = self._prepare_pop_flow(
                path[-1].endpoint_b,
                self.uni_z.interface,
                out_vlan_z,
                queue_id=self.queue_id,
            )
            flows_z.append(pop_flow)

        uni_flows.append((self.uni_z.interface.switch.id, flows_z))

        return uni_flows

    def _install_uni_flows(self, path=None, skip_in=False, skip_out=False, using_event=False):
        """Install UNI flows."""
        uni_flows = self.prepare_uni_flows(path, skip_in, skip_out)

        for dpid,flows in uni_flows:
            self._send_flow_mods2(dpid, flows, using_event=using_event)
            self._send_flow_mods2(dpid, flows, using_event=using_event)

    def _send_flow_mods2(self, dpid, flow_mods, command='flows', force=False, using_event=False):
        """Send a flow_mod list to a specific switch either via REST or KytosEvent."""
        if using_event:
            return self._send_flow_mods_event(dpid, flow_mods, command=command, force=force)
        return self._send_flow_mods_rest(dpid, flow_mods, command=command, force=force)

    def _send_flow_mods(self, switch, flow_mods, command='flows', force=False, using_event=False):
        """Send a flow_mod list to a specific switch either via REST or KytosEvent."""
        if using_event:
            return self._send_flow_mods_event(switch.id, flow_mods, command=command, force=force)
        return self._send_flow_mods_rest(switch.id, flow_mods, command=command, force=force)

    @staticmethod
    def _send_flow_mods_rest(dpid, flow_mods, command='flows', force=False):
        """Send a flow_mod list to a specific switch via REST API.

        Args:
            switch(Switch): The target of flows.
            flow_mods(dict): Python dictionary with flow_mods.
            command(str): By default is 'flows'. To remove a flow is 'remove'.
            force(bool): True to send via consistency check in case of conn errors

        """
        endpoint = f"{settings.MANAGER_URL}/{command}/{dpid}"

        data = {"flows": flow_mods, "force": force}
        response = requests.post(endpoint, json=data)
        if response.status_code >= 400:
            raise FlowModException

    def _send_flow_mods_event(self, dpid, flow_mods, command='flows', force=False):
        """Send a flow_mod list to a specific switch via KytosEvent.

        Args:
            switch(Switch): The target of flows.
            flow_mods(dict): Python dictionary with flow_mods.
            command(str): By default is 'flows'. To remove a flow is 'remove'.
            force(bool): True to send via consistency check in case of conn errors

        """
        if command == "flows":
            command = "install"

        emit_event(
            self._controller,
            command,
            context="kytos.flow_manager.flows",
            dpid=dpid,
            flow_dict={"flows": flow_mods},
            force=force,
        )

    def get_cookie(self):
        """Return the cookie integer from evc id."""
        return int(self.id, 16) + (settings.COOKIE_PREFIX << 56)

    @staticmethod
    def get_id_from_cookie(cookie):
        """Return the evc id given a cookie value."""
        evc_id = cookie - (settings.COOKIE_PREFIX << 56)
        return f"{evc_id:x}".zfill(14)

    def _prepare_flow_mod(self, in_interface, out_interface, queue_id=None):
        """Prepare a common flow mod."""
        default_actions = [
            {"action_type": "output", "port": out_interface.port_number}
        ]
        if queue_id:
            default_actions.append(
                {"action_type": "set_queue", "queue_id": queue_id}
            )

        flow_mod = {
            "match": {"in_port": in_interface.port_number},
            "cookie": self.get_cookie(),
            "actions": default_actions,
        }
        if self.priority > -1:
            flow_mod["priority"] = self.priority

        return flow_mod

    def _prepare_nni_flow(self, *args, queue_id=None):
        """Create NNI flows."""
        in_interface, out_interface, in_vlan, out_vlan = args
        flow_mod = self._prepare_flow_mod(
            in_interface, out_interface, queue_id
        )
        flow_mod["match"]["dl_vlan"] = in_vlan

        new_action = {"action_type": "set_vlan", "vlan_id": out_vlan}
        flow_mod["actions"].insert(0, new_action)

        return flow_mod

    def _prepare_push_flow(self, *args, queue_id=None):
        """Prepare push flow.

        Arguments:
            in_interface(str): Interface input.
            out_interface(str): Interface output.
            in_vlan(str): Vlan input.
            out_vlan(str): Vlan output.
            new_c_vlan(str): New client vlan.

        Return:
            dict: An python dictionary representing a FlowMod

        """
        # assign all arguments
        in_interface, out_interface, in_vlan, out_vlan , new_c_vlan = args

        flow_mod = self._prepare_flow_mod(
            in_interface, out_interface, queue_id
        )

        # the service tag must be always pushed
        new_action = {"action_type": "set_vlan", "vlan_id": out_vlan}
        flow_mod["actions"].insert(0, new_action)

        new_action = {"action_type": "push_vlan", "tag_type": "s"}
        flow_mod["actions"].insert(0, new_action)

        if in_vlan:
            # if in_vlan is set, it must be included in the match
            flow_mod["match"]["dl_vlan"] = in_vlan
        if new_c_vlan:
            # new_in_vlan is set, so an action to set it is necessary
            new_action = {"action_type": "set_vlan", "vlan_id": new_c_vlan}
            flow_mod["actions"].insert(0, new_action)
            if not in_vlan:
                # new_in_vlan is set, but in_vlan is not, so there was no
                # vlan set; then it is set now
                new_action = {"action_type": "push_vlan", "tag_type": "c"}
                flow_mod["actions"].insert(0, new_action)
        elif in_vlan:
            # in_vlan is set, but new_in_vlan is not, so the existing vlan
            # must be removed
            new_action = {"action_type": "pop_vlan"}
            flow_mod["actions"].insert(0, new_action)
        return flow_mod

    def _prepare_pop_flow(
        self, in_interface, out_interface, out_vlan, queue_id=None
    ):
        # pylint: disable=too-many-arguments
        """Prepare pop flow."""
        flow_mod = self._prepare_flow_mod(
            in_interface, out_interface, queue_id
        )
        flow_mod["match"]["dl_vlan"] = out_vlan
        new_action = {"action_type": "pop_vlan"}
        flow_mod["actions"].insert(0, new_action)
        return flow_mod

    @staticmethod
    def run_sdntrace(uni):
        """Run SDN trace on control plane starting from EVC UNIs."""
        endpoint = f"{settings.SDN_TRACE_CP_URL}/trace"
        data_uni = {
            "trace": {
                "switch": {
                    "dpid": uni.interface.switch.dpid,
                    "in_port": uni.interface.port_number,
                }
            }
        }
        if uni.user_tag:
            data_uni["trace"]["eth"] = {
                "dl_type": 0x8100,
                "dl_vlan": uni.user_tag.value,
            }
        response = requests.put(endpoint, json=data_uni)
        if response.status_code >= 400:
            #log.error(f"Failed to run sdntrace-cp: {response.text}")
            return []
        return response.json().get('result', [])

    def check_traces(self):
        """Check if current_path is deployed comparing with SDN traces."""
        trace_a = self.run_sdntrace(self.uni_a)
        if len(trace_a) != len(self.current_path) + 1:
            #log.warn(f"Invalid trace from uni_a: {trace_a} -- wrong len")
            return False
        trace_z = self.run_sdntrace(self.uni_z)
        if len(trace_z) != len(self.current_path) + 1:
            #log.warn(f"Invalid trace from uni_z: {trace_z} -- wrong len")
            return False

        for link, trace1, trace2 in zip(self.current_path,
                                        trace_a[1:],
                                        trace_z[:0:-1]):
            if compare_endpoint_trace(
               link.endpoint_a,
               glom(link.metadata, 's_vlan.value'), trace2) is False:
                #log.warn(f"Invalid trace from uni_a: {trace_a} -- compare_endpoint_trace")
                return False
            if compare_endpoint_trace(
               link.endpoint_b,
               glom(link.metadata, 's_vlan.value'), trace1) is False:
                #log.warn(f"Invalid trace from uni_z: {trace_z} -- compare_endpoint_trace")
                return False

        return True

    def flows_match_from_path(self, path):
        """Create a list of flows match from the path."""
        path_flows = []
        for incoming, outgoing in zip(path[:-1], path[1:]):
            sw = incoming.endpoint_b.switch.id
            in_vlan = incoming.get_metadata("s_vlan").value
            # incoming direction
            path_flows.append({
                "switch": sw,
                "match": {
                    "in_port": incoming.endpoint_b.port_number,
                    "dl_vlan": incoming.get_metadata("s_vlan").value,
                },
            })
            # outgoing direction
            path_flows.append({
                "switch": sw,
                "match": {
                    "in_port": outgoing.endpoint_a.port_number,
                    "dl_vlan": outgoing.get_metadata("s_vlan").value,
                },
            })
        return path_flows

    def flows_match_from_uni(self, path, skip_in=False):
        if not path:
            return []
        in_vlan_a = self.uni_a.user_tag.value if self.uni_a.user_tag else None
        out_vlan_a = path[0].get_metadata("s_vlan").value
        in_vlan_z = self.uni_z.user_tag.value if self.uni_z.user_tag else None
        out_vlan_z = path[-1].get_metadata("s_vlan").value

        # outgoing flows
        uni_flows = [
            (self.uni_a.interface.switch, path[0].endpoint_a, out_vlan_a),
            (self.uni_z.interface.switch, path[-1].endpoint_b, out_vlan_z),
        ]

        # incoming flows
        if not skip_in:
            uni_flows.extend([
                (self.uni_a.interface.switch, self.uni_a.interface, in_vlan_a),
                (self.uni_z.interface.switch, self.uni_z.interface, in_vlan_z),
            ])

        flows_match = []
        for uni_flow in uni_flows:
             flow = {
                 "switch": uni_flow[0].id,
                 "match": {"in_port": uni_flow[1].port_number},
             }
             if uni_flow[2]:
                 flow["match"]["dl_vlan"] = uni_flow[2]
             flows_match.append(flow)

        return flows_match


class LinkProtection(EVCDeploy):
    """Class to handle link protection."""

    def is_affected_by_link(self, link=None):
        """Verify if the current path is affected by link down event."""
        return self.current_path.is_affected_by_link(link)

    def is_using_primary_path(self):
        """Verify if the current deployed path is self.primary_path."""
        return self.current_path == self.primary_path

    def is_using_backup_path(self):
        """Verify if the current deployed path is self.backup_path."""
        return self.current_path == self.backup_path

    def is_using_dynamic_path(self):
        """Verify if the current deployed path is dynamic."""
        if (
            self.current_path
            and not self.is_using_primary_path()
            and not self.is_using_backup_path()
            and self.current_path.status is EntityStatus.UP
        ):
            return True
        return False

    def deploy_to(self, path_name=None, path=None):
        """Create a deploy to path."""
        if self.current_path == path:
            #log.debug(f"{path_name} is equal to current_path.")
            return True

        if path.status is EntityStatus.UP:
            return self.deploy_to_path(path)

        return False

    def handle_link_up(self, link):
        """Handle circuit when link down.

        Args:
            link(Link): Link affected by link.down event.

        """
        if self.is_using_primary_path():
            return True

        success = False
        if self.primary_path.is_affected_by_link(link):
            success = self.deploy_to_primary_path()

        if success:
            return True

        # We tried to deploy(primary_path) without success.
        # And in this case is up by some how. Nothing to do.
        if self.is_using_backup_path() or self.is_using_dynamic_path():
            return True

        # In this case, probably the circuit is not being used and
        # we can move to backup
        if self.backup_path.is_affected_by_link(link):
            success = self.deploy_to_backup_path()

        if success:
            return True

        # In this case, the circuit is not being used and we should
        # try a dynamic path
        if self.dynamic_backup_path:
            return self.deploy_to_path()

        return True

    def handle_link_down(self, delay_sync=False):
        """Handle circuit when link down.

        Returns:
            bool: True if the re-deploy was successly otherwise False.

        """
        #log_info("handle_link_down start %s" % self.id)
        success = False
        if self.is_using_primary_path():
            success = self.deploy_to_backup_path()
        elif self.is_using_backup_path():
            success = self.deploy_to_primary_path()

        if not success and self.dynamic_backup_path:
            #if self.next_path and self.next_path.status is EntityStatus.UP:
            if self.next_path:
                success = self.deploy_next_path(delay_sync)
            if not success:
                success = self.deploy_to_path()

        if success:
            #log.debug(f"{self} deployed after link down.")
            pass
        else:
            self.deactivate()
            self.current_path = Path([])
            if not delay_sync:
                self.sync()
            #log.debug(f"Failed to re-deploy {self} after link down.")

        #log_info("handle_link_down end %s" % self.id)
        return success


class EVC(LinkProtection):
    """Class that represents a E-Line Virtual Connection."""
