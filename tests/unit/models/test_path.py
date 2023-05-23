"""Module to test the Path class."""
import sys
from unittest import TestCase
from unittest.mock import call, patch, Mock, MagicMock

from kytos.core.common import EntityStatus
from kytos.core.link import Link
from kytos.core.switch import Switch

# pylint: disable=wrong-import-position

sys.path.insert(0, "/var/lib/kytos/napps/..")
# pylint: enable=wrong-import-position
from napps.kytos.mef_eline.exceptions import DisabledSwitch, InvalidPath  # NOQA pycodestyle
from napps.kytos.mef_eline.models import Path, DynamicPathManager  # NOQA pycodestyle
from napps.kytos.mef_eline.tests.helpers import (
    MockResponse,
    id_to_interface_mock,
    get_link_mocked,
    get_mocked_requests,
)  # NOQA pycodestyle


class TestPath(TestCase):
    """Class to test path methods."""

    def test_is_affected_by_link_1(self):
        """Test method is affected by link."""
        path = Path()
        self.assertIs(path.is_affected_by_link(), False)

    def test_link_affected_by_interface_1(self):
        """Test method to get the link using an interface."""
        link1 = Mock()
        link1.endpoint_a = "a"
        link1.endpoint_b = "b"
        link2 = Mock()
        link2.endpoint_a = "c"
        link2.endpoint_b = "d"
        path = Path([link1, link2])
        self.assertIsNone(path.link_affected_by_interface())

    def test_link_affected_by_interface_2(self):
        """Test method to get the link using an interface."""
        link1 = Mock()
        link1.endpoint_a = "a"
        link1.endpoint_b = "b"
        link2 = Mock()
        link2.endpoint_a = "c"
        link2.endpoint_b = "d"
        path = Path([link1, link2])
        self.assertEqual(path.link_affected_by_interface("a"), link1)

    def test_status_case_1(self):
        """Test if empty link is DISABLED."""
        current_path = Path()
        self.assertEqual(current_path.status, EntityStatus.DISABLED)

    @patch("requests.get", side_effect=get_mocked_requests)
    def test_status_case_2(self, requests_mocked):
        # pylint: disable=unused-argument
        """Test if link status is DOWN."""
        link1 = get_link_mocked()
        link2 = get_link_mocked()
        link1.id = "def"
        link2.id = "abc"
        links = [link1, link2]
        current_path = Path(links)
        self.assertEqual(current_path.status, EntityStatus.DOWN)

    def test_status_case_3(self):
        """Test if link status is DISABLED."""
        links = []
        current_path = Path(links)
        self.assertEqual(current_path.status, EntityStatus.DISABLED)

    # This method will be used by the mock to replace requests.get
    def _mocked_requests_get_status_case_4(self):
        return MockResponse(
            {
                "links": {
                    "abc": {"active": True, "enabled": True},
                    "def": {"active": True, "enabled": True},
                }
            },
            200,
        )

    @patch("requests.get", side_effect=_mocked_requests_get_status_case_4)
    def test_status_case_4(self, requests_mocked):
        # pylint: disable=unused-argument
        """Test if link status is UP."""
        link1 = get_link_mocked()
        link2 = get_link_mocked()
        link1.id = "def"
        link2.id = "abc"
        links = [link1, link2]
        current_path = Path(links)
        self.assertEqual(current_path.status, EntityStatus.UP)

    # This method will be used by the mock to replace requests.get
    def _mocked_requests_get_status_case_5(self):
        return MockResponse(
            {
                "links": {
                    "abc": {"active": True, "enabled": True},
                    "def": {"active": False, "enabled": False},
                }
            },
            200,
        )

    @patch("requests.get", side_effect=_mocked_requests_get_status_case_5)
    def test_status_case_5(self, requests_mocked):
        # pylint: disable=unused-argument
        """Test if link status is UP."""
        link1 = get_link_mocked()
        link2 = get_link_mocked()
        link1.id = "def"
        link2.id = "abc"
        links = [link1, link2]
        current_path = Path(links)
        self.assertEqual(current_path.status, EntityStatus.DISABLED)

    # This method will be used by the mock to replace requests.get
    def _mocked_requests_get_status_case_6(self):
        return MockResponse(
            {
                "links": {
                    "abc": {"active": False, "enabled": False},
                    "def": {"active": False, "enabled": True},
                }
            },
            200,
        )

    @patch("requests.get", side_effect=_mocked_requests_get_status_case_6)
    def test_status_case_6(self, requests_mocked):
        # pylint: disable=unused-argument
        """Test if link status is UP."""
        link1 = get_link_mocked()
        link2 = get_link_mocked()
        link1.id = "def"
        link2.id = "abc"
        links = [link1, link2]
        current_path = Path(links)
        self.assertEqual(current_path.status, EntityStatus.DISABLED)

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
        self.assertEqual(path_1, path_2)

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
        self.assertNotEqual(path_1, path_2)

    def test_as_dict(self):
        """Test path as dict."""
        links = [
            get_link_mocked(link_dict={"id": 3}),
            get_link_mocked(link_dict={"id": 2}),
        ]

        current_path = Path(links)
        expected_dict = [{"id": 3}, {"id": 2}]
        self.assertEqual(expected_dict, current_path.as_dict())

    def test_empty_is_valid(self) -> None:
        """Test empty path is valid."""
        path = Path([])
        self.assertEqual(path.is_valid(MagicMock(), MagicMock(), False), True)

    def test_is_valid(self):
        """Test is_valid method."""
        switch1 = Switch("00:00:00:00:00:00:00:01")
        switch2 = Switch("00:00:00:00:00:00:00:02")
        switch3 = Switch("00:00:00:00:00:00:00:03")
        switch4 = Switch("00:00:00:00:00:00:00:04")
        switch5 = Switch("00:00:00:00:00:00:00:05")
        switch6 = Switch("00:00:00:00:00:00:00:06")
        switch1.enable()
        switch2.enable()
        switch3.enable()
        switch4.enable()
        switch5.enable()
        switch6.enable()

        links1 = [
            get_link_mocked(switch_a=switch1, switch_b=switch2),
            get_link_mocked(switch_a=switch2, switch_b=switch3),
            get_link_mocked(switch_a=switch3, switch_b=switch4),
            get_link_mocked(switch_a=switch4, switch_b=switch5),
            get_link_mocked(switch_a=switch5, switch_b=switch6),
        ]

        links2 = [
            get_link_mocked(switch_a=switch1, switch_b=switch2),
            get_link_mocked(switch_a=switch3, switch_b=switch2),
            get_link_mocked(switch_a=switch3, switch_b=switch4),
        ]

        for links, switch_a, switch_z, expected in (
            (links1, switch1, switch6, True),
            (links2, switch1, switch4, False),
            (links1, switch2, switch6, False),
        ):
            with self.subTest(
                links=links,
                switch_a=switch_a,
                switch_z=switch_z,
                expected=expected,
            ):
                path = Path(links)
                if expected:
                    self.assertEqual(
                        path.is_valid(switch_a, switch_z), expected
                    )
                else:
                    with self.assertRaises(InvalidPath):
                        path.is_valid(switch_a, switch_z)

    def test_is_valid_disabled_switch(self):
        """Test is_valid method with DisabledSwitch."""
        switch1 = Switch("00:00:00:00:00:00:00:01")
        switch2 = Switch("00:00:00:00:00:00:00:02")
        switch1.enable()

        links1 = [
            get_link_mocked(switch_a=switch1, switch_b=switch2),
        ]

        path = Path(links1)
        with self.assertRaises(DisabledSwitch):
            path.is_valid(switch1, switch2)


class TestDynamicPathManager(TestCase):
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
        self.assertEqual(DynamicPathManager._clear_path(path), expected_path)

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
        self.assertIsNone(DynamicPathManager.create_path(path))

    @patch("requests.post")
    def test_get_best_path(self, mock_requests_post):
        """Test get_best_path method."""
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
            ]
        }

        expected_path = [
            Link(
                id_to_interface_mock("00:00:00:00:00:00:00:01:2"),
                id_to_interface_mock("00:00:00:00:00:00:00:02:2")
            ),
        ]

        # test success case
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = paths1
        mock_requests_post.return_value = mock_response

        res_paths = list(DynamicPathManager.get_best_path(MagicMock()))
        self.assertEqual(
            [link.id for link in res_paths],
            [link.id for link in expected_path]
        )

        # test failure when controller dont find the interface on create_path
        controller.get_interface_by_id.side_effect = [
            id_to_interface_mock("00:00:00:00:00:00:00:01:2"),
            None
        ]
        self.assertIsNone(DynamicPathManager.get_best_path(MagicMock()))

        mock_response.status_code = 400
        mock_response.json.return_value = {}
        mock_requests_post.return_value = mock_response

        res_paths = DynamicPathManager.get_best_path(MagicMock())
        self.assertIsNone(res_paths)

    @patch("requests.post")
    def test_get_best_paths(self, mock_requests_post):
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
        mock_requests_post.return_value = mock_response
        kwargs = {
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
        self.assertEqual(
            [link.id for link in res_paths[0]],
            [link.id for link in expected_paths_0]
        )
        self.assertEqual(
            [link.id for link in res_paths[1]],
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
        )
        mock_requests_post.assert_has_calls([expected_call])

    @patch("requests.post")
    def test_get_disjoint_paths(self, mock_requests_post):
        """Test get_disjoint_paths method."""

        controller = MagicMock()
        controller.get_interface_by_id.side_effect = id_to_interface_mock
        DynamicPathManager.set_controller(controller)

        evc = MagicMock()
        evc.secondary_constraints = {
            "spf_max_path_cost": 20,
            "mandatory_metrics": {
                "ownership": "red"
            }
        }
        evc.uni_a.interface.id = "1"
        evc.uni_z.interface.id = "2"

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
        mock_requests_post.return_value = mock_response
        disjoint_paths = list(DynamicPathManager.get_disjoint_paths(evc, []))
        self.assertEqual(disjoint_paths, [])

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

        # only one path available from pathfinder (precesilly the
        # current_path), so the maximum disjoint path will be empty
        mock_response.json.return_value = {"paths": paths1["paths"][0:1]}
        mock_requests_post.return_value = mock_response
        paths = list(DynamicPathManager.get_disjoint_paths(evc, current_path))
        self.assertEqual(len(paths), 0)

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
        mock_requests_post.return_value = mock_response
        paths = list(DynamicPathManager.get_disjoint_paths(evc, current_path))
        self.assertEqual(len(paths), 4)
        # for more information on the paths please refer to EP029
        self.assertEqual(len(paths[0]), 4)  # path S-Z-W-I-D
        self.assertEqual(len(paths[1]), 5)  # path S-Z-W-I-J-D
        self.assertEqual(len(paths[2]), 3)  # path S-Z-W-D
        self.assertEqual(len(paths[3]), 4)  # path S-X-W-I-D
        self.assertEqual(
            [link.id for link in paths[0]],
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
        )
        assert mock_requests_post.call_count >= 1
        # If secondary_constraints are set they are expected to be parametrized
        mock_requests_post.assert_has_calls([expected_call])

        # EP029 Topo2
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
        mock_requests_post.return_value = mock_response
        paths = list(DynamicPathManager.get_disjoint_paths(evc, current_path))
        self.assertEqual(len(paths), 1)
        self.assertEqual(
            [link.id for link in paths[0]],
            [link.id for link in expected_disjoint_path]
        )
