"""Module to test the Path class."""
import sys
from unittest import TestCase
from unittest.mock import patch, Mock

from kytos.core.common import EntityStatus

# pylint: disable=wrong-import-position
sys.path.insert(0, '/var/lib/kytos/napps/..')
# pylint: enable=wrong-import-position
from napps.kytos.mef_eline.exceptions import InvalidPath  # NOQA pycodestyle
from napps.kytos.mef_eline.models import Path  # NOQA pycodestyle
from napps.kytos.mef_eline.tests.helpers import MockResponse, get_link_mocked  # NOQA pycodestyle


class TestPath(TestCase):
    """Class to test path methods."""

    def test_is_affected_by_link_1(self):
        """Test method is affected by link."""
        path = Path()
        self.assertIs(path.is_affected_by_link(), False)

    def test_link_affected_by_interface_1(self):
        """Test method to get the link using an interface."""
        link1 = Mock()
        link1.endpoint_a = 'a'
        link1.endpoint_b = 'b'
        link2 = Mock()
        link2.endpoint_a = 'c'
        link2.endpoint_b = 'd'
        path = Path([link1, link2])
        self.assertIsNone(path.link_affected_by_interface())

    def test_link_affected_by_interface_2(self):
        """Test method to get the link using an interface."""
        link1 = Mock()
        link1.endpoint_a = 'a'
        link1.endpoint_b = 'b'
        link2 = Mock()
        link2.endpoint_a = 'c'
        link2.endpoint_b = 'd'
        path = Path([link1, link2])
        self.assertEqual(path.link_affected_by_interface('a'), link1)

    def test_status_case_1(self):
        """Test if empty link is DISABLED."""
        current_path = Path()
        self.assertEqual(current_path.status, EntityStatus.DISABLED)

    # This method will be used by the mock to replace requests.get
    def _mocked_requests_get_status_case_2(self):
        # pylint: disable=no-self-use
        return MockResponse({'links': {'abc': {'active': False,
                                               'enabled': True},
                                       'def': {'active': True,
                                               'enabled': True}}}, 200)

    @patch('requests.get', side_effect=_mocked_requests_get_status_case_2)
    def test_status_case_2(self, requests_mocked):
        # pylint: disable=unused-argument
        """Test if link status is DOWN."""
        link1 = get_link_mocked()
        link2 = get_link_mocked()
        link1.id = 'def'
        link2.id = 'abc'
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
        # pylint: disable=no-self-use
        return MockResponse({'links': {'abc': {'active': True,
                                               'enabled': True},
                                       'def': {'active': True,
                                               'enabled': True}}}, 200)

    @patch('requests.get', side_effect=_mocked_requests_get_status_case_4)
    def test_status_case_4(self, requests_mocked):
        # pylint: disable=unused-argument
        """Test if link status is UP."""
        link1 = get_link_mocked()
        link2 = get_link_mocked()
        link1.id = 'def'
        link2.id = 'abc'
        links = [link1, link2]
        current_path = Path(links)
        self.assertEqual(current_path.status, EntityStatus.UP)

    # This method will be used by the mock to replace requests.get
    def _mocked_requests_get_status_case_5(self):
        # pylint: disable=no-self-use
        return MockResponse({'links': {'abc': {'active': True,
                                               'enabled': True},
                                       'def': {'active': False,
                                               'enabled': False}}}, 200)

    @patch('requests.get', side_effect=_mocked_requests_get_status_case_5)
    def test_status_case_5(self, requests_mocked):
        # pylint: disable=unused-argument
        """Test if link status is UP."""
        link1 = get_link_mocked()
        link2 = get_link_mocked()
        link1.id = 'def'
        link2.id = 'abc'
        links = [link1, link2]
        current_path = Path(links)
        self.assertEqual(current_path.status, EntityStatus.DISABLED)

    # This method will be used by the mock to replace requests.get
    def _mocked_requests_get_status_case_6(self):
        # pylint: disable=no-self-use
        return MockResponse({'links': {'abc': {'active': False,
                                               'enabled': False},
                                       'def': {'active': False,
                                               'enabled': True}}}, 200)

    @patch('requests.get', side_effect=_mocked_requests_get_status_case_6)
    def test_status_case_6(self, requests_mocked):
        # pylint: disable=unused-argument
        """Test if link status is UP."""
        link1 = get_link_mocked()
        link2 = get_link_mocked()
        link1.id = 'def'
        link2.id = 'abc'
        links = [link1, link2]
        current_path = Path(links)
        self.assertEqual(current_path.status, EntityStatus.DISABLED)

    def test_compare_same_paths(self):
        """Test compare paths with same links."""
        links = [
                get_link_mocked(endpoint_a_port=9, endpoint_b_port=10,
                                metadata={"s_vlan": 5}),
                get_link_mocked(endpoint_a_port=11, endpoint_b_port=12,
                                metadata={"s_vlan": 6})
            ]

        path_1 = Path(links)
        path_2 = Path(links)
        self.assertEqual(path_1, path_2)

    def test_compare_different_paths(self):
        """Test compare paths with different links."""
        links_1 = [
                get_link_mocked(endpoint_a_port=9, endpoint_b_port=10,
                                metadata={"s_vlan": 5}),
                get_link_mocked(endpoint_a_port=11, endpoint_b_port=12,
                                metadata={"s_vlan": 6})
            ]
        links_2 = [
                get_link_mocked(endpoint_a_port=12, endpoint_b_port=11,
                                metadata={"s_vlan": 5}),
                get_link_mocked(endpoint_a_port=14, endpoint_b_port=16,
                                metadata={"s_vlan": 11})
            ]

        path_1 = Path(links_1)
        path_2 = Path(links_2)
        self.assertNotEqual(path_1, path_2)

    def test_as_dict(self):
        """Test path as dict."""
        links = [
                get_link_mocked(link_dict={"id": 3}),
                get_link_mocked(link_dict={"id": 2})
            ]

        current_path = Path(links)
        expected_dict = [{"id": 3}, {"id": 2}]
        self.assertEqual(expected_dict, current_path.as_dict())

    def test_is_valid(self):
        """Test is_valid method."""
        switch1 = '00:00:00:00:00:00:00:01'
        switch2 = '00:00:00:00:00:00:00:02'
        switch3 = '00:00:00:00:00:00:00:03'
        switch4 = '00:00:00:00:00:00:00:04'
        switch5 = '00:00:00:00:00:00:00:05'
        switch6 = '00:00:00:00:00:00:00:06'

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
            get_link_mocked(switch_a=switch3, switch_b=switch4)
        ]

        for links, switch_a, switch_z, expected in (
                (links1, switch1, switch6, True),
                (links2, switch1, switch4, False),
                (links1, switch2, switch6, False)
                ):
            with self.subTest(links=links, switch_a=switch_a,
                              switch_z=switch_z, expected=expected):
                path = Path(links)
                if expected:
                    self.assertEqual(path.is_valid(switch_a, switch_z),
                                     expected)
                else:
                    with self.assertRaises(InvalidPath):
                        path.is_valid(switch_a, switch_z)
