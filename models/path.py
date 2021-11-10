"""Classes related to paths"""
import requests

from kytos.core import log
from kytos.core.common import EntityStatus, GenericEntity
from kytos.core.link import Link
from napps.kytos.mef_eline import settings
from napps.kytos.mef_eline.exceptions import InvalidPath


class Path(list, GenericEntity):
    """Class to represent a Path."""

    def __eq__(self, other=None):
        """Compare paths."""
        if not other or not isinstance(other, Path):
            return False
        return super().__eq__(other)

    def is_affected_by_link(self, link=None):
        """Verify if the current path is affected by link."""
        if not link:
            return False
        return link in self

    def link_affected_by_interface(self, interface=None):
        """Return the link using this interface, if any, or None otherwise."""
        if not interface:
            return None
        for link in self:
            if interface in (link.endpoint_a, link.endpoint_b):
                return link
        return None

    def choose_vlans(self):
        """Choose the VLANs to be used for the circuit."""
        for link in self:
            tag = link.get_next_available_tag()
            link.add_metadata('s_vlan', tag)

    def make_vlans_available(self):
        """Make the VLANs used in a path available when undeployed."""
        for link in self:
            link.make_tag_available(link.get_metadata('s_vlan'))
            link.remove_metadata('s_vlan')

    def is_valid(self, switch_a, switch_z, is_scheduled=False):
        """Check if this is a valid path."""
        previous = switch_a
        for link in self:
            if link.endpoint_a.switch != previous:
                raise InvalidPath(f'{link.endpoint_a} switch is different'
                                  f' from previous.')
            if is_scheduled is False and (
                link.endpoint_a.link is None or
                link.endpoint_a.link != link or
                link.endpoint_b.link is None or
                link.endpoint_b.link != link
            ):
                raise InvalidPath(f'Link {link} is not available.')
            previous = link.endpoint_b.switch
        if previous == switch_z:
            return True
        raise InvalidPath(f'Last endpoint is different from uni_z')

    @property
    def status(self):
        """Check for the  status of a path.

        If any link in this path is down, the path is considered down.
        """
        if not self:
            return EntityStatus.DISABLED

        endpoint = '%s/%s' % (settings.TOPOLOGY_URL, 'links')
        api_reply = requests.get(endpoint)
        if api_reply.status_code != getattr(requests.codes, 'ok'):
            log.error('Failed to get links at %s. Returned %s',
                      endpoint, api_reply.status_code)
            return None
        links = api_reply.json()['links']
        return_status = EntityStatus.UP
        for path_link in self:
            try:
                link = links[path_link.id]
            except KeyError:
                return EntityStatus.DISABLED
            if link['enabled'] is False:
                return EntityStatus.DISABLED
            if link['active'] is False:
                return_status = EntityStatus.DOWN
        return return_status

    def as_dict(self):
        """Return list comprehension of links as_dict."""
        return [link.as_dict() for link in self if link]


class DynamicPathManager:
    """Class to handle and create paths."""

    controller = None

    @classmethod
    def set_controller(cls, controller=None):
        """Set the controller to discovery news paths."""
        cls.controller = controller

    @staticmethod
    def get_paths(circuit):
        """Get a valid path for the circuit from the Pathfinder."""
        endpoint = settings.PATHFINDER_URL
        request_data = {"source": circuit.uni_a.interface.id,
                        "destination": circuit.uni_z.interface.id}
        api_reply = requests.post(endpoint, json=request_data)

        if api_reply.status_code != getattr(requests.codes, 'ok'):
            log.error("Failed to get paths at %s. Returned %s",
                      endpoint, api_reply.status_code)
            return None
        reply_data = api_reply.json()
        return reply_data.get('paths')

    @staticmethod
    def _clear_path(path):
        """Remove switches from a path, returning only interfaces."""
        return [endpoint for endpoint in path if len(endpoint) > 23]

    @classmethod
    def get_best_path(cls, circuit):
        """Return the best path available for a circuit, if exists."""
        paths = cls.get_paths(circuit)
        if paths:
            return cls.create_path(cls.get_paths(circuit)[0]['hops'])
        return None

    @classmethod
    def get_best_paths(cls, circuit):
        """Return the best paths available for a circuit, if they exist."""
        for path in cls.get_paths(circuit):
            yield cls.create_path(path['hops'])

    @classmethod
    def create_path(cls, path):
        """Return the path containing only the interfaces."""
        new_path = Path()
        clean_path = cls._clear_path(path)

        if len(clean_path) % 2:
            return None

        for link in zip(clean_path[1:-1:2], clean_path[2::2]):
            interface_a = cls.controller.get_interface_by_id(link[0])
            interface_b = cls.controller.get_interface_by_id(link[1])
            if interface_a is None or interface_b is None:
                return None
            new_path.append(Link(interface_a, interface_b))

        return new_path
