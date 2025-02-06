"""Module to test the Path class."""
import sys
from unittest.mock import call, patch, Mock, MagicMock
import pytest
from napps.kytos.mef_eline import settings
from httpx import TimeoutException, ConnectError
from kytos.core.common import EntityStatus
from kytos.core.link import Link
from kytos.core.switch import Switch

# pylint: disable=wrong-import-position,ungrouped-imports,no-member

sys.path.insert(0, "/var/lib/kytos/napps/..")
# pylint: enable=wrong-import-position
from napps.kytos.mef_eline.exceptions import InvalidPath  # NOQA pycodestyle
from napps.kytos.mef_eline.models import (  # NOQA pycodestyle
    DynamicPathManager, Path)
from napps.kytos.mef_eline.tests.helpers import (  # NOQA pycodestyle
    MockResponse, get_link_mocked, id_to_interface_mock)


class TestPath():
    """Class to test path methods."""

    def test_is_affected_by_link_1(self):
        """Test method is affected by link."""
        path = Path()
        assert path.is_affected_by_link() is False

    def test_link_affected_by_interface_1(self):
        """Test method to get the link using an interface."""
        link1 = Mock()
        link1.endpoint_a = "a"
        link1.endpoint_b = "b"
        link2 = Mock()
        link2.endpoint_a = "c"
        link2.endpoint_b = "d"
        path = Path([link1, link2])
        assert path.link_affected_by_interface() is None

    def test_link_affected_by_interface_2(self):
        """Test method to get the link using an interface."""
        link1 = Mock()
        link1.endpoint_a = "a"
        link1.endpoint_b = "b"
        link2 = Mock()
        link2.endpoint_a = "c"
        link2.endpoint_b = "d"
        path = Path([link1, link2])
        assert path.link_affected_by_interface("a") == link1

    def test_status_case_1(self):
        """Test if empty link is DISABLED."""
        current_path = Path()
        assert current_path.status == EntityStatus.DISABLED

    def test_status_case_2(self):
        """Test if link status is DOWN."""
        link1 = get_link_mocked()
        link2 = get_link_mocked()
        link1.id = "def"
        link2.id = "abc"
        links = [link1, link2]
        current_path = Path(links)
        assert current_path.status == EntityStatus.DOWN

    def test_status_case_3(self):
        """Test if link status is DISABLED."""
        links = []
        current_path = Path(links)
        assert current_path.status == EntityStatus.DISABLED

    # This method will be used by the mock to replace httpx.get
    def _mocked_httpx_get_status_case_4(self):
        return MockResponse(
            {
                "links": {
                    "abc": {"active": True, "enabled": True},
                    "def": {"active": True, "enabled": True},
                }
            },
            200,
        )

    def test_status_case_4(self):
        """Test if link status is UP."""
        link1 = get_link_mocked(status=EntityStatus.UP)
        link2 = get_link_mocked(status=EntityStatus.UP)
        link1.id = "def"
        link2.id = "abc"
        links = [link1, link2]
        current_path = Path(links)
        assert current_path.status == EntityStatus.UP

    def test_status_case_5(self):
        """Test if link status is UP."""
        link1 = get_link_mocked(status=EntityStatus.UP)
        link2 = get_link_mocked(status=EntityStatus.DISABLED)
        link1.id = "def"
        link2.id = "abc"
        links = [link1, link2]
        current_path = Path(links)
        assert current_path.status == EntityStatus.DISABLED

    def test_status_case_6(self):
        """Test if link status is UP."""
        link1 = get_link_mocked(status=EntityStatus.DISABLED)
        link2 = get_link_mocked(status=EntityStatus.UP)
        link1.id = "def"
        link2.id = "abc"
        links = [link1, link2]
        current_path = Path(links)
        assert current_path.status == EntityStatus.DISABLED

    def test_status_case_7(self):
        """Test if link status is DOWN if has one link down."""
        link1 = get_link_mocked(status=EntityStatus.UP)
        link2 = get_link_mocked(status=EntityStatus.DOWN)
        link1.id = "def"
        link2.id = "abc"
        links = [link1, link2]
        current_path = Path(links)
        assert current_path.status == EntityStatus.DOWN

    def test_status_case_8(self):
        """Test if status is DOWN if has one endpoint link is mismatched."""
        link1 = get_link_mocked(status=EntityStatus.UP)
        link1.endpoint_a.link = None
        link2 = get_link_mocked(status=EntityStatus.UP)
        link1.id = "def"
        link2.id = "abc"
        links = [link1, link2]
        current_path = Path(links)
        assert current_path.status == EntityStatus.DOWN

    def test_compare_same_paths(self):
        """Test compare paths with same links."""
        links = [
            get_link_mocked(
                endpoint_a_port=9, endpoint_b_port=10, metadata={"s_vlan": 5}
            ),
            get_link_mocked(
                endpoint_a_port=11, endpoint_b_port=12, metadata={"s_vlan": 6}
            ),
        ]

        path_1 = Path(links)
        path_2 = Path(links)
        assert path_1 == path_2

    def test_compare_different_paths(self):
        """Test compare paths with different links."""
        links_1 = [
            get_link_mocked(
                endpoint_a_port=9, endpoint_b_port=10, metadata={"s_vlan": 5}
            ),
            get_link_mocked(
                endpoint_a_port=11, endpoint_b_port=12, metadata={"s_vlan": 6}
            ),
        ]
        links_2 = [
            get_link_mocked(
                endpoint_a_port=12, endpoint_b_port=11, metadata={"s_vlan": 5}
            ),
            get_link_mocked(
                endpoint_a_port=14, endpoint_b_port=16, metadata={"s_vlan": 11}
            ),
        ]

        path_1 = Path(links_1)
        path_2 = Path(links_2)
        assert path_1 != path_2

    def test_as_dict(self):
        """Test path as dict."""
        links = [
            get_link_mocked(link_dict={"id": 3}),
            get_link_mocked(link_dict={"id": 2}),
        ]

        current_path = Path(links)
        expected_dict = [{"id": 3}, {"id": 2}]
        assert expected_dict == current_path.as_dict()

    def test_empty_is_valid(self) -> None:
        """Test empty path is valid."""
        path = Path([])
        assert path.is_valid(MagicMock(), MagicMock(), False)

    def test_is_valid(self):
        """Test is_valid method."""
        switch1 = Switch("00:00:00:00:00:00:00:01")
        switch2 = Switch("00:00:00:00:00:00:00:02")
        switch3 = Switch("00:00:00:00:00:00:00:03")
        switch4 = Switch("00:00:00:00:00:00:00:04")
        switch5 = Switch("00:00:00:00:00:00:00:05")
        switch6 = Switch("00:00:00:00:00:00:00:06")
        # Links connected
        links = [
            get_link_mocked(switch_a=switch5, switch_b=switch6),
            get_link_mocked(switch_a=switch4, switch_b=switch5),
            get_link_mocked(switch_a=switch3, switch_b=switch4),
            get_link_mocked(switch_a=switch2, switch_b=switch3),
            get_link_mocked(switch_a=switch1, switch_b=switch2),
        ]
        path = Path(links)
        assert path.is_valid(switch6, switch1) is True

    def test_is_valid_diconnected(self):
        """Test is_valid with disconnected path"""
        switch1 = Switch("00:00:00:00:00:00:00:01")
        switch2 = Switch("00:00:00:00:00:00:00:02")
        switch3 = Switch("00:00:00:00:00:00:00:03")
        switch4 = Switch("00:00:00:00:00:00:00:04")
        links = [
            get_link_mocked(switch_a=switch1, switch_b=switch2),
            get_link_mocked(switch_a=switch3, switch_b=switch4),
            get_link_mocked(switch_a=switch2, switch_b=switch4),
        ]
        path = Path(links)
        with pytest.raises(InvalidPath):
            path.is_valid(switch1, switch4)

    def test_is_valid_with_loop(self):
        """Test is_valid with a loop"""
        switch1 = Switch("00:00:00:00:00:00:00:01")
        switch2 = Switch("00:00:00:00:00:00:00:02")
        switch3 = Switch("00:00:00:00:00:00:00:03")
        switch4 = Switch("00:00:00:00:00:00:00:04")
        switch5 = Switch("00:00:00:00:00:00:00:05")
        links = [
            get_link_mocked(switch_a=switch1, switch_b=switch2),
            get_link_mocked(switch_a=switch2, switch_b=switch3),
            get_link_mocked(switch_a=switch3, switch_b=switch4),
            get_link_mocked(switch_a=switch2, switch_b=switch4),
            get_link_mocked(switch_a=switch2, switch_b=switch5),
        ]
        path = Path(links)
        with pytest.raises(InvalidPath):
            path.is_valid(switch1, switch5)

    def test_is_valid_invalid(self):
        """Test is_valid when path is invalid
        UNI_Z is not connected"""
        switch1 = Switch("00:00:00:00:00:00:00:01")
        switch2 = Switch("00:00:00:00:00:00:00:02")
        switch3 = Switch("00:00:00:00:00:00:00:03")
        switch4 = Switch("00:00:00:00:00:00:00:04")
        switch5 = Switch("00:00:00:00:00:00:00:05")
        switch6 = Switch("00:00:00:00:00:00:00:06")
        links = [
            get_link_mocked(switch_a=switch5, switch_b=switch6),
            get_link_mocked(switch_a=switch4, switch_b=switch5),
            get_link_mocked(switch_a=switch3, switch_b=switch4),
            get_link_mocked(switch_a=switch2, switch_b=switch3),
            get_link_mocked(switch_a=switch1, switch_b=switch2),
        ]
        path = Path(links)
        with pytest.raises(InvalidPath):
            path.is_valid(switch3, switch6)


class TestDynamicPathManager():
    """Tests for the DynamicPathManager class"""

    def test_clear_path(self):
        """Test _clear_path method"""
        path = [
            '00:00:00:00:00:00:00:01:1',
            '00:00:00:00:00:00:00:02:3',
            '00:00:00:00:00:00:00:02',
            '00:00:00:00:00:00:00:02:4',
            '00:00:00:00:00:00:00:03:2',
            '00:00:00:00:00:00:00:03',
            '00:00:00:00:00:00:00:03:1',
            '00:00:00:00:00:00:00:04:1'
        ]
        expected_path = [
            '00:00:00:00:00:00:00:01:1',
            '00:00:00:00:00:00:00:02:3',
            '00:00:00:00:00:00:00:02:4',
            '00:00:00:00:00:00:00:03:2',
            '00:00:00:00:00:00:00:03:1',
            '00:00:00:00:00:00:00:04:1'
        ]
        # pylint: disable=protected-access
        assert DynamicPathManager._clear_path(path) == expected_path

    def test_valid_path_invalid(self):
        """Test _valid_path for invalid paths."""
        invalid_a = [
            "00:00:00:00:00:00:00:02:3",
            "00:00:00:00:00:00:00:03:2",
            "00:00:00:00:00:00:00:03:3",
            "00:00:00:00:00:00:00:04:2"
        ]
        assert DynamicPathManager._valid_path(invalid_a) is False

        invalid_b = [
            "00:00:00:00:00:00:00:01:2",
            "00:00:00:00:00:00:00:02:2",
            "00:00:00:00:00:00:00:02:3",
            "00:00:00:00:00:00:00:03:2",
            "00:00:00:00:00:00:00:03:5",
        ]
        assert DynamicPathManager._valid_path(invalid_b) is False

        invalid_c = [
            "00:00:00:00:00:00:00:02:2",
            "00:00:00:00:00:00:00:02:3",
            "00:00:00:00:00:00:00:03:2",
            "00:00:00:00:00:00:00:03:3",
            "00:00:00:00:00:00:00:04:2"
        ]
        assert DynamicPathManager._valid_path(invalid_c) is False

    def test_create_path_invalid(self):
        """Test create_path method"""
        path = [
            '00:00:00:00:00:00:00:01:1',
            '00:00:00:00:00:00:00:02:3',
            '00:00:00:00:00:00:00:02',
            '00:00:00:00:00:00:00:02:4',
            '00:00:00:00:00:00:00:03:2',
            '00:00:00:00:00:00:00:03',
            '00:00:00:00:00:00:00:03:1',
        ]
        assert DynamicPathManager.create_path(path) is None

    @patch("httpx.post")
    def test_get_best_paths(self, mock_httpx_post):
        """Test get_best_paths method."""
        controller = MagicMock()
        controller.get_interface_by_id.side_effect = id_to_interface_mock
        DynamicPathManager.set_controller(controller)

        paths1 = {
            "paths": [
                {
                    "cost": 5,
                    "hops": [
                        "00:00:00:00:00:00:00:01:1",
                        "00:00:00:00:00:00:00:01",
                        "00:00:00:00:00:00:00:01:2",
                        "00:00:00:00:00:00:00:02:2",
                        "00:00:00:00:00:00:00:02",
                        "00:00:00:00:00:00:00:02:1"
                        ]
                },
                {
                    "cost": 11,
                    "hops": [
                        "00:00:00:00:00:00:00:01:1",
                        "00:00:00:00:00:00:00:01",
                        "00:00:00:00:00:00:00:01:2",
                        "00:00:00:00:00:00:00:02:2",
                        "00:00:00:00:00:00:00:02",
                        "00:00:00:00:00:00:00:02:3",
                        "00:00:00:00:00:00:00:03:3",
                        "00:00:00:00:00:00:00:03",
                        "00:00:00:00:00:00:00:03:4",
                        "00:00:00:00:00:00:00:04:4",
                        "00:00:00:00:00:00:00:04",
                        "00:00:00:00:00:00:00:04:1"
                        ]
                },
            ]
        }

        expected_paths_0 = [
            Link(
                id_to_interface_mock("00:00:00:00:00:00:00:01:2"),
                id_to_interface_mock("00:00:00:00:00:00:00:02:2")
            ),
        ]

        expected_paths_1 = [
            Link(
                id_to_interface_mock("00:00:00:00:00:00:00:01:2"),
                id_to_interface_mock("00:00:00:00:00:00:00:02:2")
            ),
            Link(
                id_to_interface_mock("00:00:00:00:00:00:00:02:3"),
                id_to_interface_mock("00:00:00:00:00:00:00:03:3")
            ),
            Link(
                id_to_interface_mock("00:00:00:00:00:00:00:03:4"),
                id_to_interface_mock("00:00:00:00:00:00:00:04:4")
            ),
        ]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = paths1
        mock_httpx_post.return_value = mock_response
        kwargs = {
            "spf_attribute": settings.SPF_ATTRIBUTE,
            "spf_max_path_cost": 8,
            "mandatory_metrics": {
                "ownership": "red"
            }
        }
        circuit = MagicMock()
        circuit.uni_a.interface.id = "1"
        circuit.uni_z.interface.id = "2"
        max_paths = 2
        res_paths = list(DynamicPathManager.get_best_paths(circuit,
                         max_paths=max_paths, **kwargs))
        assert (
            [link.id for link in res_paths[0]] ==
            [link.id for link in expected_paths_0]
        )
        assert (
            [link.id for link in res_paths[1]] ==
            [link.id for link in expected_paths_1]
        )
        expected_call = call(
            "http://localhost:8181/api/kytos/pathfinder/v3/",
            json={
                **{
                    "source": circuit.uni_a.interface.id,
                    "destination": circuit.uni_z.interface.id,
                    "spf_max_paths": max_paths,
                },
                **kwargs
            },
            timeout=10,
        )
        mock_httpx_post.assert_has_calls([expected_call])

    @patch('time.sleep')
    @patch("napps.kytos.mef_eline.models.path.log")
    @patch("httpx.post")
    def test_get_best_paths_error(self, mock_httpx_post, mock_log, _):
        """Test get_best_paths method."""
        controller = MagicMock()
        DynamicPathManager.set_controller(controller)
        circuit = MagicMock()
        circuit.id = "id"
        circuit.uni_a.interface.id = "1"
        circuit.uni_z.interface.id = "2"
        circuit.name = "some_name"

        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.json.return_value = {}
        mock_httpx_post.return_value = mock_response

        res_paths = list(DynamicPathManager.get_best_paths(circuit))
        assert not res_paths
        assert isinstance(res_paths, list)
        assert mock_log.error.call_count == 1

    # pylint: disable=too-many-statements, too-many-locals
    @patch.object(
        DynamicPathManager,
        "get_shared_components",
        side_effect=DynamicPathManager.get_shared_components
    )
    @patch("httpx.post")
    def test_get_disjoint_paths(self, mock_httpx_post, mock_shared):
        """Test get_disjoint_paths method."""

        controller = MagicMock()
        controller.get_interface_by_id.side_effect = id_to_interface_mock
        DynamicPathManager.set_controller(controller)

        evc = MagicMock()
        evc.secondary_constraints = {
            "spf_attribute": "hop",
            "spf_max_path_cost": 20,
            "mandatory_metrics": {
                "ownership": "red"
            }
        }
        evc.uni_a.interface.id = "1"
        evc.uni_z.interface.id = "2"
        evc.uni_a.interface.switch.id = "00:00:00:00:00:00:00:01"
        evc.uni_z.interface.switch.id = "00:00:00:00:00:00:00:05"

        # Topo0
        paths1 = {
            "paths": [
                {
                    "cost": 11,
                    "hops": [
                        "00:00:00:00:00:00:00:01:1",
                        "00:00:00:00:00:00:00:01",
                        "00:00:00:00:00:00:00:01:2",
                        "00:00:00:00:00:00:00:02:2",
                        "00:00:00:00:00:00:00:02",
                        "00:00:00:00:00:00:00:02:3",
                        "00:00:00:00:00:00:00:04:2",
                        "00:00:00:00:00:00:00:04",
                        "00:00:00:00:00:00:00:04:3",
                        "00:00:00:00:00:00:00:05:2",
                        "00:00:00:00:00:00:00:05",
                        "00:00:00:00:00:00:00:05:1"
                        ]
                },
                {
                    "cost": 11,
                    "hops": [
                        "00:00:00:00:00:00:00:01:1",
                        "00:00:00:00:00:00:00:01",
                        "00:00:00:00:00:00:00:01:3",
                        "00:00:00:00:00:00:00:03:2",
                        "00:00:00:00:00:00:00:03",
                        "00:00:00:00:00:00:00:03:3",
                        "00:00:00:00:00:00:00:04:4",
                        "00:00:00:00:00:00:00:04",
                        "00:00:00:00:00:00:00:04:3",
                        "00:00:00:00:00:00:00:05:2",
                        "00:00:00:00:00:00:00:05",
                        "00:00:00:00:00:00:00:05:1"
                        ]
                },
                {
                    "cost": 14,
                    "hops": [
                        "00:00:00:00:00:00:00:01:1",
                        "00:00:00:00:00:00:00:01",
                        "00:00:00:00:00:00:00:01:2",
                        "00:00:00:00:00:00:00:02:2",
                        "00:00:00:00:00:00:00:02",
                        "00:00:00:00:00:00:00:02:3",
                        "00:00:00:00:00:00:00:04:2",
                        "00:00:00:00:00:00:00:04",
                        "00:00:00:00:00:00:00:04:5",
                        "00:00:00:00:00:00:00:06:2",
                        "00:00:00:00:00:00:00:06",
                        "00:00:00:00:00:00:00:06:3",
                        "00:00:00:00:00:00:00:05:3",
                        "00:00:00:00:00:00:00:05",
                        "00:00:00:00:00:00:00:05:1"
                    ]
                },
                {
                    "cost": 14,
                    "hops": [
                        "00:00:00:00:00:00:00:01:1",
                        "00:00:00:00:00:00:00:01",
                        "00:00:00:00:00:00:00:01:3",
                        "00:00:00:00:00:00:00:03:2",
                        "00:00:00:00:00:00:00:03",
                        "00:00:00:00:00:00:00:03:3",
                        "00:00:00:00:00:00:00:04:4",
                        "00:00:00:00:00:00:00:04",
                        "00:00:00:00:00:00:00:04:5",
                        "00:00:00:00:00:00:00:06:2",
                        "00:00:00:00:00:00:00:06",
                        "00:00:00:00:00:00:00:06:3",
                        "00:00:00:00:00:00:00:05:3",
                        "00:00:00:00:00:00:00:05",
                        "00:00:00:00:00:00:00:05:1"
                    ]
                },
                {
                    "cost": 17,
                    "hops": [
                        "00:00:00:00:00:00:00:01:1",
                        "00:00:00:00:00:00:00:01",
                        "00:00:00:00:00:00:00:01:3",
                        "00:00:00:00:00:00:00:03:2",
                        "00:00:00:00:00:00:00:03",
                        "00:00:00:00:00:00:00:03:3",
                        "00:00:00:00:00:00:00:04:4",
                        "00:00:00:00:00:00:00:04",
                        "00:00:00:00:00:00:00:04:5",
                        "00:00:00:00:00:00:00:06:2",
                        "00:00:00:00:00:00:00:06",
                        "00:00:00:00:00:00:00:06:4",
                        "00:00:00:00:00:00:00:07:2",
                        "00:00:00:00:00:00:00:07",
                        "00:00:00:00:00:00:00:07:3",
                        "00:00:00:00:00:00:00:05:4",
                        "00:00:00:00:00:00:00:05",
                        "00:00:00:00:00:00:00:05:1"
                    ]
                },
            ]
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = paths1

        # when we dont have the current_path
        mock_httpx_post.return_value = mock_response
        disjoint_paths = list(DynamicPathManager.get_disjoint_paths(evc, []))
        assert not disjoint_paths

        current_path = [
            Link(
                id_to_interface_mock("00:00:00:00:00:00:00:01:2"),
                id_to_interface_mock("00:00:00:00:00:00:00:02:2")
            ),
            Link(
                id_to_interface_mock("00:00:00:00:00:00:00:02:3"),
                id_to_interface_mock("00:00:00:00:00:00:00:04:2")
            ),
            Link(
                id_to_interface_mock("00:00:00:00:00:00:00:04:3"),
                id_to_interface_mock("00:00:00:00:00:00:00:05:2")
            ),
        ]
        path_links = [
            ("00:00:00:00:00:00:00:01:2", "00:00:00:00:00:00:00:02:2"),
            ("00:00:00:00:00:00:00:02:3", "00:00:00:00:00:00:00:04:2"),
            ("00:00:00:00:00:00:00:04:3", "00:00:00:00:00:00:00:05:2")
        ]
        path_switches = {
            "00:00:00:00:00:00:00:04",
            "00:00:00:00:00:00:00:02"
        }

        # only one path available from pathfinder (precesilly the
        # current_path), so the maximum disjoint path will be empty
        mock_response.json.return_value = {"paths": paths1["paths"][0:1]}
        mock_httpx_post.return_value = mock_response
        paths = list(DynamicPathManager.get_disjoint_paths(evc, current_path))
        args = mock_shared.call_args[0]
        assert args[0] == paths1["paths"][0]
        assert args[1] == path_links
        assert args[2] == path_switches
        assert len(paths) == 0

        expected_disjoint_path = [
            Link(
                id_to_interface_mock("00:00:00:00:00:00:00:01:3"),
                id_to_interface_mock("00:00:00:00:00:00:00:03:2")
            ),
            Link(
                id_to_interface_mock("00:00:00:00:00:00:00:03:3"),
                id_to_interface_mock("00:00:00:00:00:00:00:04:4")
            ),
            Link(
                id_to_interface_mock("00:00:00:00:00:00:00:04:5"),
                id_to_interface_mock("00:00:00:00:00:00:00:06:2")
            ),
            Link(
                id_to_interface_mock("00:00:00:00:00:00:00:06:3"),
                id_to_interface_mock("00:00:00:00:00:00:00:05:3")
            ),
        ]

        # there are one alternative path
        mock_response.json.return_value = paths1
        mock_httpx_post.return_value = mock_response
        paths = list(DynamicPathManager.get_disjoint_paths(evc, current_path))
        args = mock_shared.call_args[0]
        assert args[0] == paths1["paths"][-1]
        assert args[1] == path_links
        assert args[2] == {
            "00:00:00:00:00:00:00:04",
            "00:00:00:00:00:00:00:02"
        }
        assert len(paths) == 4
        # for more information on the paths please refer to EP029
        assert len(paths[0]) == 4  # path S-Z-W-I-D
        assert len(paths[1]) == 5  # path S-Z-W-I-J-D
        assert len(paths[2]) == 3  # path S-Z-W-D
        assert len(paths[3]) == 4  # path S-X-W-I-D
        assert (
            [link.id for link in paths[0]] ==
            [link.id for link in expected_disjoint_path]
        )

        max_paths = 10
        expected_call = call(
            "http://localhost:8181/api/kytos/pathfinder/v3/",
            json={
                **{
                    "source": evc.uni_a.interface.id,
                    "destination": evc.uni_z.interface.id,
                    "spf_max_paths": max_paths,
                },
                **evc.secondary_constraints
            },
            timeout=10,
        )
        assert mock_httpx_post.call_count >= 1
        # If secondary_constraints are set they are expected to be parametrized
        mock_httpx_post.assert_has_calls([expected_call])

        # EP029 Topo2
        evc.uni_a.interface.switch.id = "00:00:00:00:00:00:00:01"
        evc.uni_z.interface.switch.id = "00:00:00:00:00:00:00:07"
        paths2 = {
            "paths": [
                {
                    "cost": 14,
                    "hops": [
                        "00:00:00:00:00:00:00:01:1",
                        "00:00:00:00:00:00:00:01",
                        "00:00:00:00:00:00:00:01:2",
                        "00:00:00:00:00:00:00:02:1",
                        "00:00:00:00:00:00:00:02",
                        "00:00:00:00:00:00:00:02:2",
                        "00:00:00:00:00:00:00:03:1",
                        "00:00:00:00:00:00:00:03",
                        "00:00:00:00:00:00:00:03:2",
                        "00:00:00:00:00:00:00:04:1",
                        "00:00:00:00:00:00:00:04",
                        "00:00:00:00:00:00:00:04:2",
                        "00:00:00:00:00:00:00:07:2",
                        "00:00:00:00:00:00:00:07",
                        "00:00:00:00:00:00:00:07:1"
                    ]
                },
                {
                    "cost": 17,
                    "hops": [
                        "00:00:00:00:00:00:00:01:1",
                        "00:00:00:00:00:00:00:01",
                        "00:00:00:00:00:00:00:01:2",
                        "00:00:00:00:00:00:00:02:1",
                        "00:00:00:00:00:00:00:02",
                        "00:00:00:00:00:00:00:02:3",
                        "00:00:00:00:00:00:00:05:1",
                        "00:00:00:00:00:00:00:05",
                        "00:00:00:00:00:00:00:05:2",
                        "00:00:00:00:00:00:00:06:1",
                        "00:00:00:00:00:00:00:06",
                        "00:00:00:00:00:00:00:06:2",
                        "00:00:00:00:00:00:00:04:3",
                        "00:00:00:00:00:00:00:04",
                        "00:00:00:00:00:00:00:04:2",
                        "00:00:00:00:00:00:00:07:2",
                        "00:00:00:00:00:00:00:07",
                        "00:00:00:00:00:00:00:07:1"
                    ]
                }
            ]
        }

        current_path = [
            Link(
                id_to_interface_mock("00:00:00:00:00:00:00:01:2"),
                id_to_interface_mock("00:00:00:00:00:00:00:02:1")
            ),
            Link(
                id_to_interface_mock("00:00:00:00:00:00:00:02:2"),
                id_to_interface_mock("00:00:00:00:00:00:00:03:1")
            ),
            Link(
                id_to_interface_mock("00:00:00:00:00:00:00:03:2"),
                id_to_interface_mock("00:00:00:00:00:00:00:04:1")
            ),
            Link(
                id_to_interface_mock("00:00:00:00:00:00:00:04:2"),
                id_to_interface_mock("00:00:00:00:00:00:00:07:2")
            ),
        ]
        path_interfaces = [
            ("00:00:00:00:00:00:00:01:2", "00:00:00:00:00:00:00:02:1"),
            ("00:00:00:00:00:00:00:02:2", "00:00:00:00:00:00:00:03:1"),
            ("00:00:00:00:00:00:00:03:2", "00:00:00:00:00:00:00:04:1"),
            ("00:00:00:00:00:00:00:04:2", "00:00:00:00:00:00:00:07:2")
        ]
        path_switches = {
            "00:00:00:00:00:00:00:02",
            "00:00:00:00:00:00:00:03",
            "00:00:00:00:00:00:00:04"
        }

        expected_disjoint_path = [
            Link(
                id_to_interface_mock("00:00:00:00:00:00:00:01:2"),
                id_to_interface_mock("00:00:00:00:00:00:00:02:1")
            ),
            Link(
                id_to_interface_mock("00:00:00:00:00:00:00:02:3"),
                id_to_interface_mock("00:00:00:00:00:00:00:05:1")
            ),
            Link(
                id_to_interface_mock("00:00:00:00:00:00:00:05:2"),
                id_to_interface_mock("00:00:00:00:00:00:00:06:1")
            ),
            Link(
                id_to_interface_mock("00:00:00:00:00:00:00:06:2"),
                id_to_interface_mock("00:00:00:00:00:00:00:04:3")
            ),
            Link(
                id_to_interface_mock("00:00:00:00:00:00:00:04:2"),
                id_to_interface_mock("00:00:00:00:00:00:00:07:2")
            ),
        ]

        mock_response.json.return_value = {"paths": paths2["paths"]}
        mock_httpx_post.return_value = mock_response
        paths = list(DynamicPathManager.get_disjoint_paths(evc, current_path))
        args = mock_shared.call_args[0]
        assert args[0] == paths2["paths"][-1]
        assert args[1] == path_interfaces
        assert args[2] == path_switches
        assert len(paths) == 1
        assert (
            [link.id for link in paths[0]] ==
            [link.id for link in expected_disjoint_path]
        )

    @patch("httpx.post")
    def test_get_disjoint_paths_simple_evc(self, mock_httpx_post):
        """Test get_disjoint_paths method for simple EVCs."""
        controller = MagicMock()
        controller.get_interface_by_id.side_effect = id_to_interface_mock
        DynamicPathManager.set_controller(controller)

        evc = MagicMock()
        evc.secondary_constraints = {
            "spf_attribute": "hop",
            "spf_max_path_cost": 20,
            "mandatory_metrics": {
                "ownership": "red"
            }
        }
        evc.uni_a.interface.id = "1"
        evc.uni_z.interface.id = "2"
        evc.uni_a.interface.switch.id = "00:00:00:00:00:00:00:01"
        evc.uni_z.interface.switch.id = "00:00:00:00:00:00:00:05"

        mock_paths = {
            "paths": [
                {
                    "cost": 5,
                    "hops": [
                        "00:00:00:00:00:00:00:01:1",
                        "00:00:00:00:00:00:00:01",
                        "00:00:00:00:00:00:00:01:3",
                        "00:00:00:00:00:00:00:02:2",
                        "00:00:00:00:00:00:00:02",
                        "00:00:00:00:00:00:00:02:1"
                        ]
                },
                {
                    "cost": 8,
                    "hops": [
                        "00:00:00:00:00:00:00:01:1",
                        "00:00:00:00:00:00:00:01",
                        "00:00:00:00:00:00:00:01:4",
                        "00:00:00:00:00:00:00:03:3",
                        "00:00:00:00:00:00:00:03",
                        "00:00:00:00:00:00:00:03:2",
                        "00:00:00:00:00:00:00:02:3",
                        "00:00:00:00:00:00:00:02",
                        "00:00:00:00:00:00:00:02:1"
                        ]
                },
            ]
        }
        current_path = [
            Link(
                id_to_interface_mock("00:00:00:00:00:00:00:01:3"),
                id_to_interface_mock("00:00:00:00:00:00:00:02:2")
            ),
        ]
        expected_disjoint_path = [
            Link(
                id_to_interface_mock("00:00:00:00:00:00:00:01:4"),
                id_to_interface_mock("00:00:00:00:00:00:00:03:3")
            ),
            Link(
                id_to_interface_mock("00:00:00:00:00:00:00:02:3"),
                id_to_interface_mock("00:00:00:00:00:00:00:03:2")
            ),
        ]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_paths
        mock_httpx_post.return_value = mock_response
        paths = list(DynamicPathManager.get_disjoint_paths(evc, current_path))
        assert len(paths) == 1
        assert (
            [link.id for link in paths[0]] ==
            [link.id for link in expected_disjoint_path]
        )

    @patch("httpx.post")
    @patch("napps.kytos.mef_eline.models.path.log")
    @patch("time.sleep")
    def test_get_disjoint_paths_error(self, _, mock_log, mock_post):
        """Test get_disjoint_paths with reported errors. These are caught under
        httpx.RequestError."""
        mock_post.side_effect = TimeoutException('mock')
        unwanted_path = [
            Link(
                id_to_interface_mock("00:00:00:00:00:00:00:01:4"),
                id_to_interface_mock("00:00:00:00:00:00:00:03:3")
            ),
        ]
        evc = MagicMock()
        evc.secondary_constraints = {
            "spf_attribute": "hop",
            "spf_max_path_cost": 20,
            "mandatory_metrics": {
                "ownership": "red"
            }
        }
        evc.uni_a.interface.id = "1"
        evc.uni_z.interface.id = "2"
        evc.uni_a.interface.switch.id = "00:00:00:00:00:00:00:01"
        evc.uni_z.interface.switch.id = "00:00:00:00:00:00:00:05"
        path = DynamicPathManager.get_disjoint_paths(evc, unwanted_path)
        assert len(list(path)) == 0
        assert mock_log.error.call_count == 1

        mock_post.side_effect = ConnectError('mock')
        path = DynamicPathManager.get_disjoint_paths(evc, unwanted_path)
        assert len(list(path)) == 0
        assert mock_log.error.call_count == 2

    def test_get_shared_components(self):
        """Test get_shared_components"""
        mock_path = {"hops": [
            '00:00:00:00:00:00:00:01:1',
            '00:00:00:00:00:00:00:01',
            '00:00:00:00:00:00:00:01:4',
            '00:00:00:00:00:00:00:05:2',
            '00:00:00:00:00:00:00:05',
            '00:00:00:00:00:00:00:05:3',
            '00:00:00:00:00:00:00:02:4',
            '00:00:00:00:00:00:00:02',
            '00:00:00:00:00:00:00:02:3',
            '00:00:00:00:00:00:00:03:2',
            '00:00:00:00:00:00:00:03',
            '00:00:00:00:00:00:00:03:1'
        ]}
        mock_links = [
            ("00:00:00:00:00:00:00:01:2", "00:00:00:00:00:00:00:02:2"),
            ("00:00:00:00:00:00:00:02:3", "00:00:00:00:00:00:00:03:2")
        ]
        mock_switches = {"00:00:00:00:00:00:00:02"}
        actual_lk, actual_sw = DynamicPathManager.get_shared_components(
            mock_path, mock_links, mock_switches
        )
        assert actual_lk == 1
        assert actual_sw == 1
