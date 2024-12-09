"""Classes used in the main application."""  # pylint: disable=too-many-lines
import traceback
from collections import OrderedDict
from copy import deepcopy
from datetime import datetime
from operator import eq, ne
from threading import Lock
from typing import Union
from uuid import uuid4

import httpx
from glom import glom
from tenacity import (retry, retry_if_exception_type, stop_after_attempt,
                      wait_combine, wait_fixed, wait_random)

from kytos.core import log
from kytos.core.common import EntityStatus, GenericEntity
from kytos.core.exceptions import KytosNoTagAvailableError, KytosTagError
from kytos.core.helpers import get_time, now
from kytos.core.interface import UNI, Interface, TAGRange
from kytos.core.link import Link
from kytos.core.retry import before_sleep
from kytos.core.tag_ranges import range_difference
from napps.kytos.mef_eline import controllers, settings
from napps.kytos.mef_eline.exceptions import (ActivationError,
                                              DuplicatedNoTagUNI,
                                              EVCPathNotInstalled,
                                              FlowModException, InvalidPath)
from napps.kytos.mef_eline.utils import (check_disabled_component,
                                         compare_endpoint_trace,
                                         compare_uni_out_trace, emit_event,
                                         make_uni_list, map_dl_vlan,
                                         map_evc_event_content,
                                         merge_flow_dicts)

from .path import DynamicPathManager, Path


class EVCBase(GenericEntity):
    """Class to represent a circuit."""

    attributes_requiring_redeploy = [
        "primary_path",
        "backup_path",
        "dynamic_backup_path",
        "queue_id",
        "sb_priority",
        "primary_constraints",
        "secondary_constraints",
        "uni_a",
        "uni_z",
    ]
    required_attributes = ["name", "uni_a", "uni_z"]

    updatable_attributes = {
        "uni_a",
        "uni_z",
        "name",
        "start_date",
        "end_date",
        "queue_id",
        "bandwidth",
        "primary_path",
        "backup_path",
        "dynamic_backup_path",
        "primary_constraints",
        "secondary_constraints",
        "owner",
        "sb_priority",
        "service_level",
        "circuit_scheduler",
        "metadata",
        "enabled"
    }

    # pylint: disable=too-many-statements
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
            failover_path(list): Path being used to provide EVC protection via
                                failover during link failures. Default is [].
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
            sb_priority(int): Service level provided in the request.
                              Default is None.
            service_level(int): Service level provided. The higher the better.
                                Default is 0.

        Raises:
            ValueError: raised when object attributes are invalid.

        """
        self._controller = controller
        self._validate(**kwargs)
        super().__init__()

        # required attributes
        self._id = kwargs.get("id", uuid4().hex)[:14]
        self.uni_a: UNI = kwargs.get("uni_a")
        self.uni_z: UNI = kwargs.get("uni_z")
        self.name = kwargs.get("name")

        # optional attributes
        self.start_date = get_time(kwargs.get("start_date")) or now()
        self.end_date = get_time(kwargs.get("end_date")) or None
        self.queue_id = kwargs.get("queue_id", -1)

        self.bandwidth = kwargs.get("bandwidth", 0)
        self.primary_links = Path(kwargs.get("primary_links", []))
        self.backup_links = Path(kwargs.get("backup_links", []))
        self.current_path = Path(kwargs.get("current_path", []))
        self.failover_path = Path(kwargs.get("failover_path", []))
        self.primary_path = Path(kwargs.get("primary_path", []))
        self.backup_path = Path(kwargs.get("backup_path", []))
        self.dynamic_backup_path = kwargs.get("dynamic_backup_path", False)
        self.primary_constraints = kwargs.get("primary_constraints", {})
        self.secondary_constraints = kwargs.get("secondary_constraints", {})
        self.creation_time = get_time(kwargs.get("creation_time")) or now()
        self.owner = kwargs.get("owner", None)
        self.sb_priority = kwargs.get("sb_priority", None) or kwargs.get(
            "priority", None
        )
        self.service_level = kwargs.get("service_level", 0)
        self.circuit_scheduler = kwargs.get("circuit_scheduler", [])
        self.flow_removed_at = get_time(kwargs.get("flow_removed_at")) or None
        self.updated_at = get_time(kwargs.get("updated_at")) or now()
        self.execution_rounds = kwargs.get("execution_rounds", 0)
        self.current_links_cache = set()
        self.primary_links_cache = set()
        self.backup_links_cache = set()
        self.affected_by_link_at = get_time("0001-01-01T00:00:00")
        self.old_path = Path([])

        self.lock = Lock()

        self.archived = kwargs.get("archived", False)

        self.metadata = kwargs.get("metadata", {})

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

        # Special cases: No tag, any, untagged
        self.special_cases = {None, "4096/4096", 0}
        self.table_group = kwargs.get("table_group")

    def sync(self, keys: set = None):
        """Sync this EVC in the MongoDB."""
        self.updated_at = now()
        if keys:
            self._mongo_controller.update_evc(self.as_dict(keys))
            return
        self._mongo_controller.upsert_evc(self.as_dict())

    def _get_unis_use_tags(self, **kwargs) -> tuple[UNI, UNI]:
        """Obtain both UNIs (uni_a, uni_z).
        If a UNI is changing, verify tags"""
        uni_a = kwargs.get("uni_a", None)
        uni_a_flag = False
        if uni_a and uni_a != self.uni_a:
            uni_a_flag = True
            self._use_uni_vlan(uni_a, uni_dif=self.uni_a)

        uni_z = kwargs.get("uni_z", None)
        if uni_z and uni_z != self.uni_z:
            try:
                self._use_uni_vlan(uni_z, uni_dif=self.uni_z)
                self.make_uni_vlan_available(self.uni_z, uni_dif=uni_z)
            except KytosTagError as err:
                if uni_a_flag:
                    self.make_uni_vlan_available(uni_a, uni_dif=self.uni_a)
                raise err
        else:
            uni_z = self.uni_z

        if uni_a_flag:
            self.make_uni_vlan_available(self.uni_a, uni_dif=uni_a)
        else:
            uni_a = self.uni_a
        return uni_a, uni_z

    def update(self, **kwargs):
        """Update evc attributes.

        This method will raises an error trying to change the following
        attributes: [creation_time, active, current_path, failover_path,
        _id, archived]
        [name, uni_a and uni_z]

        Returns:
            the values for enable and a redeploy attribute, if exists and None
            otherwise
        Raises:
            ValueError: message with error detail.

        """
        enable, redeploy = (None, None)
        if not self._tag_lists_equal(**kwargs):
            raise ValueError(
                "UNI_A and UNI_Z tag lists should be the same."
            )
        uni_a, uni_z = self._get_unis_use_tags(**kwargs)
        check_disabled_component(uni_a, uni_z)
        self._validate_has_primary_or_dynamic(
            primary_path=kwargs.get("primary_path"),
            dynamic_backup_path=kwargs.get("dynamic_backup_path"),
            uni_a=uni_a,
            uni_z=uni_z,
        )
        for attribute, value in kwargs.items():
            if attribute not in self.updatable_attributes:
                raise ValueError(f"{attribute} can't be updated.")
            if attribute in ("primary_path", "backup_path"):
                try:
                    value.is_valid(
                        uni_a.interface.switch, uni_z.interface.switch
                    )
                except InvalidPath as exception:
                    raise ValueError(  # pylint: disable=raise-missing-from
                        f"{attribute} is not a " f"valid path: {exception}"
                    )
        for attribute, value in kwargs.items():
            if attribute == "enabled":
                if value:
                    self.enable()
                else:
                    self.disable()
                enable = value
            else:
                setattr(self, attribute, value)
                if attribute in self.attributes_requiring_redeploy:
                    redeploy = True
        self.sync(set(kwargs.keys()))
        return enable, redeploy

    def set_flow_removed_at(self):
        """Update flow_removed_at attribute."""
        self.flow_removed_at = now()

    def has_recent_removed_flow(self, setting=settings):
        """Check if any flow has been removed from the evc"""
        if self.flow_removed_at is None:
            return False
        res_seconds = (now() - self.flow_removed_at).seconds
        return res_seconds < setting.TIME_RECENT_DELETED_FLOWS

    def is_recent_updated(self, setting=settings):
        """Check if the evc has been updated recently"""
        res_seconds = (now() - self.updated_at).seconds
        return res_seconds < setting.TIME_RECENT_UPDATED

    def __repr__(self):
        """Repr method."""
        return f"EVC({self._id}, {self.name})"

    def _validate(self, **kwargs):
        """Do Basic validations.

        Verify required attributes: name, uni_a, uni_z

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

    def _tag_lists_equal(self, **kwargs):
        """Verify that tag lists are the same."""
        uni_a = kwargs.get("uni_a") or self.uni_a
        uni_z = kwargs.get("uni_z") or self.uni_z
        uni_a_list = uni_z_list = False
        if (uni_a.user_tag and isinstance(uni_a.user_tag, TAGRange)):
            uni_a_list = True
        if (uni_z.user_tag and isinstance(uni_z.user_tag, TAGRange)):
            uni_z_list = True
        if uni_a_list and uni_z_list:
            return uni_a.user_tag.value == uni_z.user_tag.value
        return uni_a_list == uni_z_list

    def _validate_has_primary_or_dynamic(
        self,
        primary_path=None,
        dynamic_backup_path=None,
        uni_a=None,
        uni_z=None,
    ) -> None:
        """Validate that it must have a primary path or allow dynamic paths."""
        primary_path = (
            primary_path
            if primary_path is not None
            else self.primary_path
        )
        dynamic_backup_path = (
            dynamic_backup_path
            if dynamic_backup_path is not None
            else self.dynamic_backup_path
        )
        uni_a = uni_a if uni_a is not None else self.uni_a
        uni_z = uni_z if uni_z is not None else self.uni_z
        if (
            not primary_path
            and not dynamic_backup_path
            and uni_a and uni_z
            and uni_a.interface.switch != uni_z.interface.switch
        ):
            msg = "The EVC must have a primary path or allow dynamic paths."
            raise ValueError(msg)

    def __eq__(self, other):
        """Override the default implementation."""
        if not isinstance(other, EVC):
            return False

        attrs_to_compare = ["name", "uni_a", "uni_z", "owner", "bandwidth"]
        for attribute in attrs_to_compare:
            if getattr(other, attribute) != getattr(self, attribute):
                return False
        return True

    def is_intra_switch(self):
        """Check if the UNIs are in the same switch."""
        return self.uni_a.interface.switch == self.uni_z.interface.switch

    def check_no_tag_duplicate(self, other_uni: UNI):
        """Check if a no tag UNI is duplicated."""
        if other_uni in (self.uni_a, self.uni_z):
            msg = f"UNI with interface {other_uni.interface.id} is"\
                  f" duplicated with {self}."
            raise DuplicatedNoTagUNI(msg)

    def as_dict(self, keys: set = None):
        """Return a dictionary representing an EVC object.
            keys: Only fields on this variable will be
                  returned in the dictionary"""
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
        evc_dict["failover_path"] = self.failover_path.as_dict()
        evc_dict["primary_path"] = self.primary_path.as_dict()
        evc_dict["backup_path"] = self.backup_path.as_dict()
        evc_dict["dynamic_backup_path"] = self.dynamic_backup_path
        evc_dict["metadata"] = self.metadata

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
        evc_dict["sb_priority"] = self.sb_priority
        evc_dict["service_level"] = self.service_level
        evc_dict["primary_constraints"] = self.primary_constraints
        evc_dict["secondary_constraints"] = self.secondary_constraints
        evc_dict["flow_removed_at"] = self.flow_removed_at
        evc_dict["updated_at"] = self.updated_at

        if keys:
            selected = {}
            for key in keys:
                selected[key] = evc_dict[key]
            selected["id"] = evc_dict["id"]
            return selected
        return evc_dict

    @property
    def id(self):  # pylint: disable=invalid-name
        """Return this EVC's ID."""
        return self._id

    def archive(self):
        """Archive this EVC on deletion."""
        self.archived = True

    def _use_uni_vlan(
        self,
        uni: UNI,
        uni_dif: Union[None, UNI] = None
    ):
        """Use tags from UNI"""
        if uni.user_tag is None:
            return
        tag = uni.user_tag.value
        tag_type = uni.user_tag.tag_type
        if (uni_dif and isinstance(tag, list) and
                isinstance(uni_dif.user_tag.value, list)):
            tag = range_difference(tag, uni_dif.user_tag.value)
            if not tag:
                return
        uni.interface.use_tags(
            self._controller, tag, tag_type, use_lock=True, check_order=False
        )

    def make_uni_vlan_available(
        self,
        uni: UNI,
        uni_dif: Union[None, UNI] = None,
    ):
        """Make available tag from UNI"""
        if uni.user_tag is None:
            return
        tag = uni.user_tag.value
        tag_type = uni.user_tag.tag_type
        if (uni_dif and isinstance(tag, list) and
                isinstance(uni_dif.user_tag.value, list)):
            tag = range_difference(tag, uni_dif.user_tag.value)
            if not tag:
                return
        try:
            conflict = uni.interface.make_tags_available(
                self._controller, tag, tag_type, use_lock=True,
                check_order=False
            )
        except KytosTagError as err:
            log.error(f"Error in {self}: {err}")
            return
        if conflict:
            intf = uni.interface.id
            log.warning(f"Tags {conflict} was already available in {intf}")

    def remove_uni_tags(self):
        """Remove both UNI usage of a tag"""
        self.make_uni_vlan_available(self.uni_a)
        self.make_uni_vlan_available(self.uni_z)


# pylint: disable=fixme, too-many-public-methods
class EVCDeploy(EVCBase):
    """Class to handle the deploy procedures."""

    def create(self):
        """Create a EVC."""

    def discover_new_paths(self):
        """Discover new paths to satisfy this circuit and deploy it."""
        return DynamicPathManager.get_best_paths(self,
                                                 **self.primary_constraints)

    def get_failover_path_candidates(self):
        """Get failover paths to satisfy this EVC."""
        # in the future we can return primary/backup paths as well
        # we just have to properly handle link_up and failover paths
        # if (
        #     self.is_using_primary_path() and
        #     self.backup_path.status is EntityStatus.UP
        # ):
        #     yield self.backup_path
        return DynamicPathManager.get_disjoint_paths(self, self.current_path)

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

    def is_failover_path_affected_by_link(self, link):
        """Return True if this EVC has the given link on its failover path."""
        return link in self.failover_path

    def is_eligible_for_failover_path(self):
        """Verify if this EVC is eligible for failover path (EP029)"""
        # In the future this function can be augmented to consider
        # primary/backup, primary/dynamic, and other path combinations
        return (
            self.dynamic_backup_path and
            not self.primary_path and not self.backup_path
        )

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

    def deploy_to_backup_path(self, old_path_dict: dict = None):
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
            success = self.deploy_to_path(self.backup_path, old_path_dict)

        if success:
            return True

        if self.dynamic_backup_path or self.is_intra_switch():
            return self.deploy_to_path(old_path_dict=old_path_dict)

        return False

    def deploy_to_primary_path(self, old_path_dict: dict = None):
        """Deploy the primary path into the datapaths of this circuit.

        If the primary_path attribute is valid and up, this method will try to
        deploy this primary_path.
        """
        # TODO: Remove flows from current (cookies)
        if self.is_using_primary_path():
            # TODO: Log to say that cannot move primary to primary
            return True

        if self.primary_path.status is EntityStatus.UP:
            return self.deploy_to_path(self.primary_path, old_path_dict)
        return False

    def deploy(self, old_path_dict: dict = None):
        """Deploy EVC to best path.

        Best path can be the primary path, if available. If not, the backup
        path, and, if it is also not available, a dynamic path.
        """
        if self.archived:
            return False
        self.enable()
        success = self.deploy_to_primary_path(old_path_dict)
        if not success:
            success = self.deploy_to_backup_path(old_path_dict)

        if success:
            emit_event(self._controller, "deployed",
                       content=map_evc_event_content(self))
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
        self.remove_current_flows(sync=False)
        self.remove_failover_flows(sync=False)
        self.disable()
        self.sync()
        emit_event(self._controller, "undeployed",
                   content=map_evc_event_content(self))

    def remove_failover_flows(self, exclude_uni_switches=True,
                              force=True, sync=True) -> None:
        """Remove failover_flows.

        By default, it'll exclude UNI switches, if mef_eline has already
        called remove_current_flows before then this minimizes the number
        of FlowMods and IO.
        """
        if not self.failover_path:
            return
        switches, cookie, excluded = OrderedDict(), self.get_cookie(), set()
        links = set()
        if exclude_uni_switches:
            excluded.add(self.uni_a.interface.switch.id)
            excluded.add(self.uni_z.interface.switch.id)
        for link in self.failover_path:
            if link.endpoint_a.switch.id not in excluded:
                switches[link.endpoint_a.switch.id] = link.endpoint_a.switch
                links.add(link)
            if link.endpoint_b.switch.id not in excluded:
                switches[link.endpoint_b.switch.id] = link.endpoint_b.switch
                links.add(link)
        for switch in switches.values():
            try:
                self._send_flow_mods(
                    switch.id,
                    [
                        {
                            "cookie": cookie,
                            "cookie_mask": int(0xffffffffffffffff),
                            "owner": "mef_eline",
                        }
                    ],
                    "delete",
                    force=force,
                )
            except FlowModException as err:
                log.error(f"Error deleting path in {switch.id}, {err}")
                break
        try:
            self.failover_path.make_vlans_available(self._controller)
        except KytosTagError as err:
            log.error(f"Error when removing failover flows: {err}")
        self.failover_path = Path([])
        if sync:
            self.sync()

    def remove_current_flows(
        self,
        current_path=None,
        force=True,
        sync=True,
        return_path=False,
    ):
        """Remove all flows from current path or path intended for
         current path if exists."""
        switches, old_path_dict = set(), {}
        current_path = self.current_path if not current_path else current_path
        if not current_path and not self.is_intra_switch():
            return {}
        
        if return_path:
            for link in current_path:
                s_vlan = link.metadata.get("s_vlan")
                if s_vlan:
                    old_path_dict[link.id] = s_vlan.value

        for link in current_path:
            switches.add(link.endpoint_a.switch)
            switches.add(link.endpoint_b.switch)
        switches.add(self.uni_a.interface.switch)
        switches.add(self.uni_z.interface.switch)
        match = {
            "cookie": self.get_cookie(),
            "cookie_mask": int(0xffffffffffffffff),
            "owner": "mef_eline",
        }

        for switch in switches:
            try:
                self._send_flow_mods(switch.id, [match], 'delete', force=force)
            except FlowModException as err:
                log.error(f"Error deleting current_path in {switch.id}, {err}")
                break
        try:
            current_path.make_vlans_available(self._controller)
        except KytosTagError as err:
            log.error(f"Error when removing current path flows: {err}")
        self.current_path = Path([])
        self.deactivate()
        if sync:
            self.sync()
        return old_path_dict

    def remove_path_flows(
        self, path=None, force=True
    ) -> dict[str, list[dict]]:
        """Remove all flows from path, and return the removed flows."""
        dpid_flows_match: dict[str, list[dict]] = {}

        if not path:
            return dpid_flows_match

        try:
            nni_flows = self._prepare_nni_flows(path)
        # pylint: disable=broad-except
        except Exception:
            err = traceback.format_exc().replace("\n", ", ")
            log.error(f"Fail to remove NNI failover flows for {self}: {err}")
            nni_flows = {}

        for dpid, flows in nni_flows.items():
            dpid_flows_match.setdefault(dpid, [])
            for flow in flows:
                dpid_flows_match[dpid].append({
                    "cookie": flow["cookie"],
                    "match": flow["match"],
                    "owner": "mef_eline",
                    "cookie_mask": int(0xffffffffffffffff)
                })

        try:
            uni_flows = self._prepare_uni_flows(path, skip_in=True)
        # pylint: disable=broad-except
        except Exception:
            err = traceback.format_exc().replace("\n", ", ")
            log.error(f"Fail to remove UNI failover flows for {self}: {err}")
            uni_flows = {}

        for dpid, flows in uni_flows.items():
            dpid_flows_match.setdefault(dpid, [])
            for flow in flows:
                dpid_flows_match[dpid].append({
                    "cookie": flow["cookie"],
                    "match": flow["match"],
                    "owner": "mef_eline",
                    "cookie_mask": int(0xffffffffffffffff)
                })

        for dpid, flows in dpid_flows_match.items():
            try:
                self._send_flow_mods(dpid, flows, 'delete', force=force)
            except FlowModException as err:
                log.error(f"Error deleting path in {dpid}, {err}")
                break
        try:
            path.make_vlans_available(self._controller)
        except KytosTagError as err:
            log.error(f"Error when removing path flows: {err}")

        return dpid_flows_match

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

    @staticmethod
    def is_uni_interface_active(
        *interfaces: Interface
    ) -> tuple[bool, dict]:
        """Whether UNIs are active and their status & status_reason."""
        active = True
        bad_interfaces = [
            interface
            for interface in interfaces
            if interface.status != EntityStatus.UP
        ]
        if bad_interfaces:
            active = False
            interfaces = bad_interfaces
        return active, {
            interface.id: {
                'status': interface.status.value,
                'status_reason': interface.status_reason,
            }
            for interface in interfaces
        }

    def try_to_activate(self) -> bool:
        """Try to activate the EVC."""
        if self.is_intra_switch():
            return self._try_to_activate_intra_evc()
        return self._try_to_activate_inter_evc()

    def _try_to_activate_intra_evc(self) -> bool:
        """Try to activate intra EVC."""
        intf_a, intf_z = self.uni_a.interface, self.uni_z.interface
        is_active, reason = self.is_uni_interface_active(intf_a, intf_z)
        if not is_active:
            raise ActivationError(
                f"Won't be able to activate {self} due to UNIs: {reason}"
            )
        self.activate()
        return True

    def _try_to_activate_inter_evc(self) -> bool:
        """Try to activate inter EVC."""
        intf_a, intf_z = self.uni_a.interface, self.uni_z.interface
        is_active, reason = self.is_uni_interface_active(intf_a, intf_z)
        if not is_active:
            raise ActivationError(
                f"Won't be able to activate {self} due to UNIs: {reason}"
            )
        if self.current_path.status != EntityStatus.UP:
            raise ActivationError(
                f"Won't be able to activate {self} due to current_path "
                f"status {self.current_path.status}"
            )
        self.activate()
        return True

    # pylint: disable=too-many-branches, too-many-statements
    def deploy_to_path(self, path=None, old_path_dict: dict = None):
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
        self.remove_current_flows(sync=False)
        use_path = path or Path([])
        if not old_path_dict:
            old_path_dict = {}
        tag_errors = []
        if self.should_deploy(use_path):
            try:
                use_path.choose_vlans(self._controller, old_path_dict)
            except KytosNoTagAvailableError as e:
                tag_errors.append(str(e))
                use_path = None
        else:
            for use_path in self.discover_new_paths():
                if use_path is None:
                    continue
                try:
                    use_path.choose_vlans(self._controller, old_path_dict)
                    break
                except KytosNoTagAvailableError as e:
                    tag_errors.append(str(e))
            else:
                use_path = None

        try:
            if use_path:
                self._install_nni_flows(use_path)
                self._install_uni_flows(use_path)
            elif self.is_intra_switch():
                use_path = Path()
                self._install_direct_uni_flows()
            else:
                msg = f"{self} was not deployed. No available path was found."
                if tag_errors:
                    msg = self.add_tag_errors(msg, tag_errors)
                    log.error(msg)
                else:
                    log.warning(msg)
                return False
        except EVCPathNotInstalled as err:
            log.error(
                f"Error deploying EVC {self} when calling flow_manager: {err}"
            )
            self.remove_current_flows(use_path, sync=True)
            return False

        self.current_path = use_path
        msg = f"{self} was deployed."
        try:
            self.try_to_activate()
        except ActivationError as exc:
            msg = f"{msg} {str(exc)}"
        self.sync()
        log.info(msg)
        return True

    def try_setup_failover_path(self, wait=settings.DEPLOY_EVCS_INTERVAL):
        """Try setup failover_path whenever possible."""
        if (
                self.failover_path or not self.current_path
                or not self.is_active()
                ):
            return
        if (now() - self.affected_by_link_at).seconds >= wait:
            with self.lock:
                self.setup_failover_path()

    # pylint: disable=too-many-statements
    def setup_failover_path(self):
        """Install flows for the failover path of this EVC.

        Procedures to deploy:

        0. Remove flows currently installed for failover_path (if any)
        1. Discover a disjoint path from current_path
        2. Choose vlans
        3. Install NNI flows
        4. Install UNI egress flows
        5. Update failover_path
        """
        # Intra-switch EVCs have no failover_path
        if self.is_intra_switch():
            return False

        # For not only setup failover path for totally dynamic EVCs
        if not self.is_eligible_for_failover_path():
            return False

        out_new_flows: dict[str, list[dict]] = {}
        reason = ""
        tag_errors = []
        out_removed_flows = self.remove_path_flows(self.failover_path)
        self.failover_path = Path([])

        for use_path in self.get_failover_path_candidates():
            if not use_path:
                continue
            try:
                use_path.choose_vlans(self._controller)
                break
            except KytosNoTagAvailableError as e:
                tag_errors.append(str(e))
        else:
            use_path = Path([])
            reason = "No available path was found"

        try:
            if use_path:
                _nni_flows = self._install_nni_flows(use_path)
                out_new_flows = merge_flow_dicts(out_new_flows, _nni_flows)
                _uni_flows = self._install_uni_flows(use_path, skip_in=True)
                out_new_flows = merge_flow_dicts(out_new_flows, _uni_flows)
        except EVCPathNotInstalled as err:
            reason = "Error deploying failover path"
            log.error(
                f"{reason} for {self}. FlowManager error: {err}"
            )
            _rmed_flows = self.remove_path_flows(use_path)
            out_removed_flows = merge_flow_dicts(
                out_removed_flows, _rmed_flows
            )
            use_path = Path([])

        self.failover_path = use_path
        self.sync()

        if out_new_flows or out_removed_flows:
            emit_event(self._controller, "failover_deployed", content={
                self.id: map_evc_event_content(
                    self,
                    flows=deepcopy(out_new_flows),
                    removed_flows=deepcopy(out_removed_flows),
                    error_reason=reason,
                    current_path=self.current_path.as_dict(),
                )
            })

        if not use_path:
            msg = f"Failover path for {self} was not deployed: {reason}."
            if tag_errors:
                msg = self.add_tag_errors(msg, tag_errors)
                log.error(msg)
            else:
                log.warning(msg)
            return False
        log.info(f"Failover path for {self} was deployed.")
        return True

    @staticmethod
    def add_tag_errors(msg: str, tag_errors: list):
        """Add to msg the tag errors ecountered when chossing path."""
        path = ['path', 'paths']
        was = ['was', 'were']
        message = ['message', 'messages']

        # Choose either singular(0) or plural(1) words
        n = 1
        if len(tag_errors) == 1:
            n = 0

        msg += f" {len(tag_errors)} {path[n]} {was[n]} rejected"
        msg += f" with {message[n]}: {tag_errors}"
        return msg

    def get_failover_flows(self):
        """Return the flows needed to make the failover path active, i.e. the
        flows for ingress forwarding.

        Return:
            dict: A dict of flows indexed by the switch_id will be returned, or
                an empty dict if no failover_path is available.
        """
        if not self.failover_path:
            return {}
        return self._prepare_uni_flows(self.failover_path, skip_out=True)

    # pylint: disable=too-many-branches
    def _prepare_direct_uni_flows(self):
        """Prepare flows connecting two UNIs for intra-switch EVC."""
        vlan_a = self._get_value_from_uni_tag(self.uni_a)
        vlan_z = self._get_value_from_uni_tag(self.uni_z)

        flow_mod_az = self._prepare_flow_mod(
            self.uni_a.interface, self.uni_z.interface,
            self.queue_id, vlan_a
        )
        flow_mod_za = self._prepare_flow_mod(
            self.uni_z.interface, self.uni_a.interface,
            self.queue_id, vlan_z
        )

        if not isinstance(vlan_z, list) and vlan_z not in self.special_cases:
            flow_mod_az["actions"].insert(
                0, {"action_type": "set_vlan", "vlan_id": vlan_z}
            )
            if not vlan_a:
                flow_mod_az["actions"].insert(
                    0, {"action_type": "push_vlan", "tag_type": "c"}
                )
            if vlan_a == 0:
                flow_mod_za["actions"].insert(0, {"action_type": "pop_vlan"})
        elif vlan_a == 0 and vlan_z == "4096/4096":
            flow_mod_za["actions"].insert(0, {"action_type": "pop_vlan"})

        if not isinstance(vlan_a, list) and vlan_a not in self.special_cases:
            flow_mod_za["actions"].insert(
                    0, {"action_type": "set_vlan", "vlan_id": vlan_a}
                )
            if not vlan_z:
                flow_mod_za["actions"].insert(
                    0, {"action_type": "push_vlan", "tag_type": "c"}
                )
            if vlan_z == 0:
                flow_mod_az["actions"].insert(0, {"action_type": "pop_vlan"})
        elif vlan_a == "4096/4096" and vlan_z == 0:
            flow_mod_az["actions"].insert(0, {"action_type": "pop_vlan"})

        flows = []
        if isinstance(vlan_a, list):
            for mask_a in vlan_a:
                flow_aux = deepcopy(flow_mod_az)
                flow_aux["match"]["dl_vlan"] = mask_a
                flows.append(flow_aux)
        else:
            if vlan_a is not None:
                flow_mod_az["match"]["dl_vlan"] = vlan_a
            flows.append(flow_mod_az)

        if isinstance(vlan_z, list):
            for mask_z in vlan_z:
                flow_aux = deepcopy(flow_mod_za)
                flow_aux["match"]["dl_vlan"] = mask_z
                flows.append(flow_aux)
        else:
            if vlan_z is not None:
                flow_mod_za["match"]["dl_vlan"] = vlan_z
            flows.append(flow_mod_za)
        return (
            self.uni_a.interface.switch.id, flows
        )

    def _install_direct_uni_flows(self):
        """Install flows connecting two UNIs.

        This case happens when the circuit is between UNIs in the
        same switch.
        """
        (dpid, flows) = self._prepare_direct_uni_flows()
        try:
            self._send_flow_mods(dpid, flows)
        except FlowModException as err:
            raise EVCPathNotInstalled(f"In {dpid}, {err}") from err

    def _prepare_nni_flows(self, path=None):
        """Prepare NNI flows."""
        nni_flows = OrderedDict()
        previous = self.uni_a.interface.switch.dpid
        for incoming, outcoming in self.links_zipped(path):
            in_vlan = incoming.get_metadata("s_vlan").value
            out_vlan = outcoming.get_metadata("s_vlan").value
            in_endpoint = self.get_endpoint_by_id(incoming, previous, ne)
            out_endpoint = self.get_endpoint_by_id(
                outcoming, in_endpoint.switch.id, eq
            )

            flows = []
            # Flow for one direction
            flows.append(
                self._prepare_nni_flow(
                    in_endpoint,
                    out_endpoint,
                    in_vlan,
                    out_vlan,
                    queue_id=self.queue_id,
                )
            )

            # Flow for the other direction
            flows.append(
                self._prepare_nni_flow(
                    out_endpoint,
                    in_endpoint,
                    out_vlan,
                    in_vlan,
                    queue_id=self.queue_id,
                )
            )
            previous = in_endpoint.switch.id
            nni_flows[in_endpoint.switch.id] = flows
        return nni_flows

    def _install_nni_flows(
        self, path=None
    ) -> dict[str, list[dict]]:
        """Install NNI flows."""
        nni_flows = self._prepare_nni_flows(path)
        try:
            for dpid, flows in nni_flows.items():
                self._send_flow_mods(dpid, flows)
        except FlowModException as err:
            raise EVCPathNotInstalled(f"In {dpid}, {err}") from err
        return nni_flows

    @staticmethod
    def _get_value_from_uni_tag(uni: UNI):
        """Returns the value from tag. In case of any and untagged
        it should return 4096/4096 and 0 respectively"""
        special = {"any": "4096/4096", "untagged": 0}
        if uni.user_tag:
            value = uni.user_tag.value
            if isinstance(value, list):
                return uni.user_tag.mask_list
            return special.get(value, value)
        return None

    # pylint: disable=too-many-locals
    def _prepare_uni_flows(self, path=None, skip_in=False, skip_out=False):
        """Prepare flows to install UNIs."""
        uni_flows = {}
        if not path:
            log.info("install uni flows without path.")
            return uni_flows

        # Determine VLANs
        in_vlan_a = self._get_value_from_uni_tag(self.uni_a)
        out_vlan_a = path[0].get_metadata("s_vlan").value

        in_vlan_z = self._get_value_from_uni_tag(self.uni_z)
        out_vlan_z = path[-1].get_metadata("s_vlan").value

        # Get endpoints from path
        endpoint_a = self.get_endpoint_by_id(
            path[0], self.uni_a.interface.switch.id, eq
        )
        endpoint_z = self.get_endpoint_by_id(
            path[-1], self.uni_z.interface.switch.id, eq
        )

        # Flows for the first UNI
        flows_a = []

        # Flow for one direction, pushing the service tag
        if not skip_in:
            if isinstance(in_vlan_a, list):
                for in_mask_a in in_vlan_a:
                    push_flow = self._prepare_push_flow(
                        self.uni_a.interface,
                        endpoint_a,
                        in_mask_a,
                        out_vlan_a,
                        in_vlan_z,
                        queue_id=self.queue_id,
                    )
                    flows_a.append(push_flow)
            else:
                push_flow = self._prepare_push_flow(
                    self.uni_a.interface,
                    endpoint_a,
                    in_vlan_a,
                    out_vlan_a,
                    in_vlan_z,
                    queue_id=self.queue_id,
                )
                flows_a.append(push_flow)

        # Flow for the other direction, popping the service tag
        if not skip_out:
            pop_flow = self._prepare_pop_flow(
                endpoint_a,
                self.uni_a.interface,
                out_vlan_a,
                queue_id=self.queue_id,
            )
            flows_a.append(pop_flow)

        uni_flows[self.uni_a.interface.switch.id] = flows_a

        # Flows for the second UNI
        flows_z = []

        # Flow for one direction, pushing the service tag
        if not skip_in:
            if isinstance(in_vlan_z, list):
                for in_mask_z in in_vlan_z:
                    push_flow = self._prepare_push_flow(
                        self.uni_z.interface,
                        endpoint_z,
                        in_mask_z,
                        out_vlan_z,
                        in_vlan_a,
                        queue_id=self.queue_id,
                    )
                    flows_z.append(push_flow)
            else:
                push_flow = self._prepare_push_flow(
                    self.uni_z.interface,
                    endpoint_z,
                    in_vlan_z,
                    out_vlan_z,
                    in_vlan_a,
                    queue_id=self.queue_id,
                )
                flows_z.append(push_flow)

        # Flow for the other direction, popping the service tag
        if not skip_out:
            pop_flow = self._prepare_pop_flow(
                endpoint_z,
                self.uni_z.interface,
                out_vlan_z,
                queue_id=self.queue_id,
            )
            flows_z.append(pop_flow)

        uni_flows[self.uni_z.interface.switch.id] = flows_z

        return uni_flows

    def _install_uni_flows(
        self, path=None, skip_in=False, skip_out=False
    ) -> dict[str, list[dict]]:
        """Install UNI flows."""
        uni_flows = self._prepare_uni_flows(path, skip_in, skip_out)
        try:
            for (dpid, flows) in uni_flows.items():
                self._send_flow_mods(dpid, flows)
        except FlowModException as err:
            raise EVCPathNotInstalled(f"In {dpid}, {err}") from err

        return uni_flows

    @staticmethod
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_combine(wait_fixed(3), wait_random(min=2, max=7)),
        retry=retry_if_exception_type(FlowModException),
        before_sleep=before_sleep,
        reraise=True,
    )
    def _send_flow_mods(dpid, flow_mods, command='flows', force=False):
        """Send a flow_mod list to a specific switch.

        Args:
            dpid(str): The target of flows (i.e. Switch.id).
            flow_mods(dict): Python dictionary with flow_mods.
            command(str): By default is 'flows'. To remove a flow is 'remove'.
            force(bool): True to send via consistency check in case of errors

        """
        endpoint = f"{settings.MANAGER_URL}/{command}/{dpid}"

        data = {"flows": flow_mods, "force": force}
        try:
            res = httpx.post(endpoint, json=data, timeout=30)
        except httpx.RequestError as err:
            raise FlowModException(str(err)) from err
        if res.is_server_error or res.status_code >= 400:
            raise FlowModException(res.text)

    def get_cookie(self):
        """Return the cookie integer from evc id."""
        return int(self.id, 16) + (settings.COOKIE_PREFIX << 56)

    @staticmethod
    def get_id_from_cookie(cookie):
        """Return the evc id given a cookie value."""
        evc_id = cookie - (settings.COOKIE_PREFIX << 56)
        return f"{evc_id:x}".zfill(14)

    def set_flow_table_group_id(self, flow_mod: dict, vlan) -> dict:
        """Set table_group and table_id"""
        table_group = "epl" if vlan is None else "evpl"
        flow_mod["table_group"] = table_group
        flow_mod["table_id"] = self.table_group[table_group]
        return flow_mod

    @staticmethod
    def get_priority(vlan):
        """Return priority value depending on vlan value"""
        if isinstance(vlan, list):
            return settings.EVPL_SB_PRIORITY
        if vlan not in {None, "4096/4096", 0}:
            return settings.EVPL_SB_PRIORITY
        if vlan == 0:
            return settings.UNTAGGED_SB_PRIORITY
        if vlan == "4096/4096":
            return settings.ANY_SB_PRIORITY
        return settings.EPL_SB_PRIORITY

    def _prepare_flow_mod(self, in_interface, out_interface,
                          queue_id=None, vlan=True):
        """Prepare a common flow mod."""
        default_actions = [
            {"action_type": "output", "port": out_interface.port_number}
        ]
        queue_id = settings.QUEUE_ID if queue_id == -1 else queue_id
        if queue_id is not None:
            default_actions.append(
                {"action_type": "set_queue", "queue_id": queue_id}
            )

        flow_mod = {
            "match": {"in_port": in_interface.port_number},
            "cookie": self.get_cookie(),
            "actions": default_actions,
            "owner": "mef_eline",
        }

        self.set_flow_table_group_id(flow_mod, vlan)
        if self.sb_priority:
            flow_mod["priority"] = self.sb_priority
        else:
            flow_mod["priority"] = self.get_priority(vlan)
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
            in_vlan(int,str,None): Vlan input.
            out_vlan(str): Vlan output.
            new_c_vlan(int,str,list,None): New client vlan.

        Return:
            dict: An python dictionary representing a FlowMod

        """
        # assign all arguments
        in_interface, out_interface, in_vlan, out_vlan, new_c_vlan = args
        vlan_pri = in_vlan if not isinstance(new_c_vlan, list) else new_c_vlan
        flow_mod = self._prepare_flow_mod(
            in_interface, out_interface, queue_id, vlan_pri
        )
        # the service tag must be always pushed
        new_action = {"action_type": "set_vlan", "vlan_id": out_vlan}
        flow_mod["actions"].insert(0, new_action)

        new_action = {"action_type": "push_vlan", "tag_type": "s"}
        flow_mod["actions"].insert(0, new_action)

        if in_vlan is not None:
            # if in_vlan is set, it must be included in the match
            flow_mod["match"]["dl_vlan"] = in_vlan

        if (not isinstance(new_c_vlan, list) and in_vlan != new_c_vlan and
                new_c_vlan not in self.special_cases):
            # new_in_vlan is an integer but zero, action to set is required
            new_action = {"action_type": "set_vlan", "vlan_id": new_c_vlan}
            flow_mod["actions"].insert(0, new_action)

        if in_vlan not in self.special_cases and new_c_vlan == 0:
            # # new_in_vlan is an integer but zero and new_c_vlan does not
            # a pop action is required
            new_action = {"action_type": "pop_vlan"}
            flow_mod["actions"].insert(0, new_action)

        elif in_vlan == "4096/4096" and new_c_vlan == 0:
            # if in_vlan match with any tags and new_c_vlan does not
            # a pop action is required
            new_action = {"action_type": "pop_vlan"}
            flow_mod["actions"].insert(0, new_action)

        elif (not in_vlan and
                (not isinstance(new_c_vlan, list) and
                 new_c_vlan not in self.special_cases)):
            # new_in_vlan is an integer but zero and in_vlan is not set
            # then it is set now
            new_action = {"action_type": "push_vlan", "tag_type": "c"}
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
    def run_bulk_sdntraces(
        uni_list: list[tuple[Interface, Union[str, int, None]]]
    ) -> dict:
        """Run SDN traces on control plane starting from EVC UNIs."""
        endpoint = f"{settings.SDN_TRACE_CP_URL}/traces"
        data = []
        for interface, tag_value in uni_list:
            data_uni = {
                "trace": {
                            "switch": {
                                "dpid": interface.switch.dpid,
                                "in_port": interface.port_number,
                            }
                        }
                }
            if tag_value:
                uni_dl_vlan = map_dl_vlan(tag_value)
                if uni_dl_vlan:
                    data_uni["trace"]["eth"] = {
                                            "dl_type": 0x8100,
                                            "dl_vlan": uni_dl_vlan,
                                            }
            data.append(data_uni)
        try:
            response = httpx.put(endpoint, json=data, timeout=30)
        except httpx.TimeoutException as exception:
            log.error(f"Request has timed out: {exception}")
            return {"result": []}
        if response.status_code >= 400:
            log.error(f"Failed to run sdntrace-cp: {response.text}")
            return {"result": []}
        return response.json()

    # pylint: disable=too-many-return-statements, too-many-arguments
    @staticmethod
    def check_trace(
        evc_id: str,
        evc_name: str,
        tag_a: Union[None, int, str],
        tag_z: Union[None, int, str],
        interface_a: Interface,
        interface_z: Interface,
        current_path: list,
        trace_a: list,
        trace_z: list
    ) -> bool:
        """Auxiliar function to check an individual trace"""
        if (
            len(trace_a) != len(current_path) + 1
            or not compare_uni_out_trace(tag_z, interface_z, trace_a[-1])
        ):
            log.warning(f"From EVC({evc_id}) named '{evc_name}'. "
                        f"Invalid trace from uni_a: {trace_a}")
            return False
        if (
            len(trace_z) != len(current_path) + 1
            or not compare_uni_out_trace(tag_a, interface_a, trace_z[-1])
        ):
            log.warning(f"From EVC({evc_id}) named '{evc_name}'. "
                        f"Invalid trace from uni_z: {trace_z}")
            return False

        if not current_path:
            return True

        first_link, trace_path_begin, trace_path_end = current_path[0], [], []
        if (
            first_link.endpoint_a.switch.id == trace_a[0]["dpid"]
        ):
            trace_path_begin, trace_path_end = trace_a, trace_z
        elif (
            first_link.endpoint_a.switch.id == trace_z[0]["dpid"]
        ):
            trace_path_begin, trace_path_end = trace_z, trace_a
        else:
            msg = (
                f"first link {first_link} endpoint_a didn't match the first "
                f"step of trace_a {trace_a} or trace_z {trace_z}"
            )
            log.warning(msg)
            return False

        for link, trace1, trace2 in zip(current_path,
                                        trace_path_begin[1:],
                                        trace_path_end[:0:-1]):
            metadata_vlan = None
            if link.metadata:
                metadata_vlan = glom(link.metadata, 's_vlan.value')
            if compare_endpoint_trace(
                                        link.endpoint_a,
                                        metadata_vlan,
                                        trace2
                                    ) is False:
                log.warning(f"From EVC({evc_id}) named '{evc_name}'. "
                            f"Invalid trace from uni_a: {trace_a}")
                return False
            if compare_endpoint_trace(
                                        link.endpoint_b,
                                        metadata_vlan,
                                        trace1
                                    ) is False:
                log.warning(f"From EVC({evc_id}) named '{evc_name}'. "
                            f"Invalid trace from uni_z: {trace_z}")
                return False

        return True

    @staticmethod
    def check_range(circuit, traces: list) -> bool:
        """Check traces when for UNI with TAGRange"""
        check = True
        for i, mask in enumerate(circuit.uni_a.user_tag.mask_list):
            trace_a = traces[i*2]
            trace_z = traces[i*2+1]
            check &= EVCDeploy.check_trace(
                circuit.id, circuit.name,
                mask, mask,
                circuit.uni_a.interface,
                circuit.uni_z.interface,
                circuit.current_path,
                trace_a, trace_z,
            )
        return check

    @staticmethod
    def check_list_traces(list_circuits: list) -> dict:
        """Check if current_path is deployed comparing with SDN traces."""
        if not list_circuits:
            return {}
        uni_list = make_uni_list(list_circuits)
        traces = EVCDeploy.run_bulk_sdntraces(uni_list)["result"]

        if not traces:
            return {}

        try:
            circuits_checked = {}
            i = 0
            for circuit in list_circuits:
                if isinstance(circuit.uni_a.user_tag, TAGRange):
                    length = len(circuit.uni_a.user_tag.mask_list)
                    circuits_checked[circuit.id] = EVCDeploy.check_range(
                        circuit, traces[i:i+length*2]
                    )
                    i += length*2
                else:
                    trace_a = traces[i]
                    trace_z = traces[i+1]
                    tag_a = None
                    if circuit.uni_a.user_tag:
                        tag_a = circuit.uni_a.user_tag.value
                    tag_z = None
                    if circuit.uni_z.user_tag:
                        tag_z = circuit.uni_z.user_tag.value
                    circuits_checked[circuit.id] = EVCDeploy.check_trace(
                        circuit.id, circuit.name,
                        tag_a, tag_z,
                        circuit.uni_a.interface,
                        circuit.uni_z.interface,
                        circuit.current_path,
                        trace_a, trace_z
                    )
                    i += 2
        except IndexError as err:
            log.error(
                f"Bulk sdntraces returned fewer items than expected."
                f"Error = {err}"
            )
            return {}

        return circuits_checked

    @staticmethod
    def get_endpoint_by_id(
        link: Link,
        id_: str,
        operator: Union[eq, ne]
    ) -> Interface:
        """Return endpoint from link
        either equal(eq) or not equal(ne) to id"""
        if operator(link.endpoint_a.switch.id, id_):
            return link.endpoint_a
        return link.endpoint_b


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

    def handle_link_up(self, link):
        """Handle circuit when link up.

        Args:
            link(Link): Link affected by link.up event.

        """
        condition_pairs = [
            (
                lambda me: me.is_using_primary_path(),
                lambda _: (True, 'nothing')
            ),
            (
                lambda me: me.is_intra_switch(),
                lambda _: (True, 'nothing')
            ),
            (
                lambda me: me.primary_path.is_affected_by_link(link),
                lambda me: (me.deploy_to_primary_path(), 'redeploy')
            ),
            # We tried to deploy(primary_path) without success.
            # And in this case is up by some how. Nothing to do.
            (
                lambda me: me.is_using_backup_path(),
                lambda _: (True, 'nothing')
            ),
            (
                lambda me:  me.is_using_dynamic_path(),
                lambda _: (True, 'nothing')
            ),
            # In this case, probably the circuit is not being used and
            # we can move to backup
            (
                lambda me: me.backup_path.is_affected_by_link(link),
                lambda me: (me.deploy_to_backup_path(), 'redeploy')
            ),
            # In this case, the circuit is not being used and we should
            # try a dynamic path
            (
                lambda me: me.dynamic_backup_path and not me.is_active(),
                lambda me: (me.deploy_to_path(), 'redeploy')
            )
        ]
        for predicate, action in condition_pairs:
            if not predicate(self):
                continue
            success, succcess_type = action(self)
            if success:
                if succcess_type == 'redeploy':
                    emit_event(
                        self._controller,
                        "redeployed_link_up",
                        content=map_evc_event_content(self)
                    )
                return True
        return False

    def handle_link_down(self):
        """Handle circuit when link down.

        Returns:
            bool: True if the re-deploy was successly otherwise False.

        """
        success = False
        if self.is_using_primary_path():
            success = self.deploy_to_backup_path()
        elif self.is_using_backup_path():
            success = self.deploy_to_primary_path()

        if not success and self.dynamic_backup_path:
            success = self.deploy_to_path()

        if success:
            log.debug(f"{self} deployed after link down.")
        else:
            self.remove_current_flows(sync=False)
            self.deactivate()
            self.sync()
            log.debug(f"Failed to re-deploy {self} after link down.")

        return success

    @staticmethod
    def get_interface_from_switch(uni: UNI, switches: dict) -> Interface:
        """Get interface from switch by uni"""
        switch = switches[uni.interface.switch.dpid]
        interface = switch.interfaces[uni.interface.port_number]
        return interface

    def are_unis_active(self, switches: dict) -> bool:
        """Determine whether this EVC should be active"""
        interface_a = self.get_interface_from_switch(self.uni_a, switches)
        interface_z = self.get_interface_from_switch(self.uni_z, switches)
        active, _ = self.is_uni_interface_active(interface_a, interface_z)
        return active

    def try_to_handle_uni_as_link_up(self, interface: Interface) -> bool:
        """Try to handle UNI as link_up to trigger deployment."""
        if (
            self.current_path.status != EntityStatus.UP
            and not self.is_intra_switch()
        ):
            succeeded = self.handle_link_up(interface)
            if succeeded:
                msg = (
                    f"Activated {self} due to successful "
                    f"deployment triggered by {interface}"
                )
            else:
                msg = (
                    f"Couldn't activate {self} due to unsuccessful "
                    f"deployment triggered by {interface}"
                )
            log.info(msg)
            return True
        return False

    def handle_interface_link_up(self, interface: Interface):
        """
        Handler for interface link_up events
        """
        if self.is_active():
            return
        interfaces = (self.uni_a.interface, self.uni_z.interface)
        if interface not in interfaces:
            return
        down_interfaces = [
            interface
            for interface in interfaces
            if interface.status != EntityStatus.UP
        ]
        if down_interfaces:
            return
        if self.try_to_handle_uni_as_link_up(interface):
            return

        interface_dicts = {
            interface.id: {
                'status': interface.status.value,
                'status_reason': interface.status_reason,
            }
            for interface in interfaces
        }
        try:
            self.try_to_activate()
            log.info(
                f"Activating {self}. Interfaces: "
                f"{interface_dicts}."
            )
            emit_event(self._controller, "uni_active_updated",
                       content=map_evc_event_content(self))
            self.sync()
        except ActivationError as exc:
            # On this ctx, no ActivationError isn't expected since the
            # activation pre-requisites states were checked, so handled as err
            log.error(f"ActivationError: {str(exc)} when handling {interface}")

    def handle_interface_link_down(self, interface):
        """
        Handler for interface link_down events
        """
        if not self.is_active():
            return
        interfaces = (self.uni_a.interface, self.uni_z.interface)
        if interface not in interfaces:
            return
        down_interfaces = [
            interface
            for interface in interfaces
            if interface.status != EntityStatus.UP
        ]
        if not down_interfaces:
            return
        interface_dicts = {
            interface.id: {
                'status': interface.status.value,
                'status_reason': interface.status_reason,
            }
            for interface in down_interfaces
        }
        self.deactivate()
        log.info(
            f"Deactivating {self}. Interfaces: "
            f"{interface_dicts}."
        )
        emit_event(self._controller, "uni_active_updated",
                   content=map_evc_event_content(self))
        self.sync()


class EVC(LinkProtection):
    """Class that represents a E-Line Virtual Connection."""
