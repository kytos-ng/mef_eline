"""Classes related to paths"""
import httpx
from tenacity import (retry, retry_if_exception_type, stop_after_attempt,
                      wait_combine, wait_fixed, wait_random)

from kytos.core import log
from kytos.core.common import EntityStatus, GenericEntity
from kytos.core.interface import TAG
from kytos.core.link import Link
from kytos.core.retry import before_sleep
from napps.kytos.mef_eline import settings
from napps.kytos.mef_eline.exceptions import InvalidPath, PathFinderException


class Path(list[Link], GenericEntity):
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

    def choose_vlans(self, controller, old_path_dict: dict = None):
        """Choose the VLANs to be used for the circuit."""
        old_path_dict = old_path_dict if old_path_dict else {}
        for link in self:
            tag_value = link.get_next_available_tag(
                controller, link.id,
                try_avoid_value=old_path_dict.get(link.id)
            )
            tag = TAG('vlan', tag_value)
            link.add_metadata("s_vlan", tag)

    def make_vlans_available(self, controller):
        """Make the VLANs used in a path available when undeployed."""
        for link in self:
            tag = link.get_metadata("s_vlan")
            conflict_a, conflict_b = link.make_tags_available(
                controller, tag.value, link.id, tag.tag_type,
                check_order=False
            )
            if conflict_a:
                log.error(f"Tags {conflict_a} was already available in"
                          f"{link.endpoint_a.id}")
            if conflict_b:
                log.error(f"Tags {conflict_b} was already available in"
                          f"{link.endpoint_b.id}")
            link.remove_metadata("s_vlan")

    def is_valid(self, switch_a, switch_z, is_scheduled=False):
        """Check if this is a valid path."""
        if not self:
            return True
        previous = visited = {switch_a}
        for link in self:
            current = {link.endpoint_a.switch, link.endpoint_b.switch} \
                      - previous
            if len(current) != 1:
                raise InvalidPath(
                    f"Previous switch {previous} is not connected to "
                    f"current link with switches {current}."
                )
            if current & visited:
                raise InvalidPath(
                    f"Loop detected in path, switch {current} was visited"
                    f" more than once."
                )
            if is_scheduled is False and (
                link.endpoint_a.link is None
                or link.endpoint_a.link != link
                or link.endpoint_b.link is None
                or link.endpoint_b.link != link
            ):
                raise InvalidPath(f"Link {link} is not available.")
            previous = current
            visited |= current
        if previous & {switch_z}:
            return True
        raise InvalidPath("Last link does not contain uni_z switch")

    @property
    def status(self) -> EntityStatus:
        """Check for the  status of a path.

        Each endpoint link is checked instead to have the same object
        ref as topology. If any link in this path isn't UP,
        the path isn't considered UP.
        """
        if not self:
            return EntityStatus.DISABLED

        for path_link in self:
            link = path_link.endpoint_a.link
            if not link or link != path_link.endpoint_b.link:
                return EntityStatus.DOWN
            if (status := link.status) != EntityStatus.UP:
                return status
        return EntityStatus.UP

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
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_combine(wait_fixed(3), wait_random(min=0, max=5)),
        retry=retry_if_exception_type(PathFinderException),
        before_sleep=before_sleep,
        reraise=True
    )
    def get_paths(circuit, max_paths=2, **kwargs) -> list[dict]:
        """Get a valid path for the circuit from the Pathfinder."""
        endpoint = settings.PATHFINDER_URL
        spf_attribute = kwargs.get("spf_attribute") or settings.SPF_ATTRIBUTE
        request_data = {
            "source": circuit.uni_a.interface.id,
            "destination": circuit.uni_z.interface.id,
            "spf_max_paths": max_paths,
            "spf_attribute": spf_attribute
        }
        request_data.update(kwargs)
        try:
            api_reply = httpx.post(endpoint, json=request_data, timeout=10)
        except httpx.RequestError as err:
            raise PathFinderException(str(err)) from err

        if api_reply.status_code >= 400:
            raise PathFinderException(api_reply.text)
        reply_data = api_reply.json()
        return reply_data.get("paths", [])

    @staticmethod
    def _clear_path(path: list[str]) -> list[str]:
        """Remove switches from a path, returning only interfaces."""
        return [endpoint for endpoint in path if len(endpoint) > 23]

    @staticmethod
    def _valid_path(clean_path: list[str]) -> bool:
        """Check is a path is valid by verifying a in and out interface.
         Returns False if the path is invalid."""
        # if len is not even
        if len(clean_path) % 2:
            return False

        # Check interfaces in pairs, they should be from the same switch
        for i in range(0, len(clean_path), 2):
            if (clean_path[i].split(":")[:8]
                    != clean_path[i + 1].split(":")[:8]):
                return False
        return True

    @classmethod
    def get_best_paths(cls, circuit, **kwargs):
        """Return the best paths available for a circuit, if they exist."""
        try:
            for path in cls.get_paths(circuit, **kwargs):
                yield cls.create_path(path["hops"])
        except PathFinderException as err:
            log.error(
                f"{circuit} failed to get paths from pathfinder. Error {err}"
            )
            return
            yield

    @classmethod
    def get_disjoint_paths(
        cls, circuit, unwanted_path, cutoff=settings.DISJOINT_PATH_CUTOFF
    ):
        """Computes the maximum disjoint paths from the unwanted_path for a EVC

        Maximum disjoint paths from the unwanted_path are the paths from the
        source node to the target node that share the minimum number of links
        and switches contained in unwanted_path. In other words, unwanted_path
        is the path we want to avoid: we want the maximum possible disjoint
        path from it. The disjointness of a path in regards to unwanted_path
        is calculated by the complementary percentage of shared links and
        switches between them. As an example, if the unwanted_path has 3
        links and 2 switches, a given path P1 has 1 link shared with
        unwanted_path, and a given path P2 has 2 links and 1 switch shared
        with unwanted_path, then the disjointness of P1 is 0.8 and the
        disjointness of P2 is 0.4. In this example, P1 is preferable over P2
        because it offers a better disjoint path. When two paths have the same
        disjointness they are ordered by 'cost' attributed as returned from
        Pathfinder. When the disjointness of a path is equal to 0 (i.e., it
        shares all the links with unwanted_path), that particular path is not
        considered a candidate.

        Parameters:
        -----------

        circuit : EVC
            The EVC providing source node (uni_a) and target node (uni_z)

        unwanted_path : Path
            The Path which we want to avoid.

        cutoff: int
            Maximum number of paths to consider when calculating the disjoint
            paths (number of paths to request from pathfinder)

        Returns:
        --------
        paths : generator
            Generator of unwanted_path disjoint paths. If unwanted_path is
            not provided or empty, we return an empty list.
        """
        unwanted_links = [
            (link.endpoint_a.id, link.endpoint_b.id) for link in unwanted_path
        ]
        unwanted_switches = set()
        for link in unwanted_path:
            unwanted_switches.add(link.endpoint_a.switch.id)
            unwanted_switches.add(link.endpoint_b.switch.id)
        unwanted_switches.discard(circuit.uni_a.interface.switch.id)
        unwanted_switches.discard(circuit.uni_z.interface.switch.id)

        length_unwanted = (len(unwanted_links) + len(unwanted_switches))
        if not unwanted_links:
            return None

        try:
            paths = cls.get_paths(circuit, max_paths=cutoff,
                                  **circuit.secondary_constraints)
        except PathFinderException as err:
            log.error(
                f"{circuit} failed to get disjointed paths from pathfinder."
                f" Error {err}"
            )
            return None

        for path in paths:
            links_n, switches_n = cls.get_shared_components(
                path, unwanted_links, unwanted_switches
            )
            shared_components = links_n + switches_n
            path["disjointness"] = 1 - shared_components / length_unwanted
        paths = sorted(paths, key=lambda x: (-x['disjointness'], x['cost']))
        for path in paths:
            if path["disjointness"] == 0:
                continue
            yield cls.create_path(path["hops"])
        return None

    @staticmethod
    def get_shared_components(
        path: Path,
        unwanted_links: list[tuple[str, str]],
        unwanted_switches: set[str]
    ) -> tuple[int, int]:
        """Return the number of shared links
        and switches found in path."""
        head = path["hops"][:-1]
        tail = path["hops"][1:]
        shared_links = 0
        for (endpoint_a, endpoint_b) in unwanted_links:
            if ((endpoint_a, endpoint_b) in zip(head, tail)) or (
                (endpoint_b, endpoint_a) in zip(head, tail)
            ):
                shared_links += 1
        copy_switches = unwanted_switches.copy()
        shared_switches = 0
        for component in path["hops"]:
            if component in copy_switches:
                shared_switches += 1
                copy_switches.remove(component)
        return shared_links, shared_switches

    @classmethod
    def create_path(cls, path):
        """Return the path containing only the interfaces."""
        new_path = Path()
        clean_path = cls._clear_path(path)
        if not cls._valid_path(clean_path):
            return None

        for link in zip(clean_path[1:-1:2], clean_path[2::2]):
            interface_a = cls.controller.get_interface_by_id(link[0])
            interface_b = cls.controller.get_interface_by_id(link[1])
            if interface_a is None or interface_b is None:
                return None
            new_path.append(Link(interface_a, interface_b))

        return new_path
