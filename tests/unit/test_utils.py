"""Module to test the utls.py file."""
from unittest import TestCase
from unittest.mock import MagicMock

from napps.kytos.mef_eline.utils import (
    compare_endpoint_trace, compare_uni_out_trace
)


# pylint: disable=too-many-public-methods, too-many-lines
class TestUtils(TestCase):
    """Test utility functions."""

    def test_compare_endpoint_trace(self):
        """Test method compare_endpoint_trace"""

        trace = {"dpid": "1234", "port": 2, "vlan": 123}

        switch1 = MagicMock()
        switch1.dpid = "1234"
        switch2 = MagicMock()
        switch2.dpid = "2345"

        endpoint = MagicMock()
        endpoint.port_number = 2
        vlan = 123

        for switch, expected in ((switch1, True), (switch2, False)):
            with self.subTest(switch=switch, expected=expected):
                endpoint.switch = switch
                self.assertEqual(
                    compare_endpoint_trace(endpoint, vlan, trace), expected
                )
                self.assertEqual(
                    compare_endpoint_trace(endpoint, None, trace), expected
                )

    def test_compare_uni_out_trace(self):
        """Test compare_uni_out_trace method."""
        # case1: trace without 'out' info, should return True
        uni = MagicMock()
        self.assertTrue(compare_uni_out_trace(uni, {}))

        # case2: trace with valid port and VLAN, should return True
        uni.interface.port_number = 1
        uni.user_tag.value = 123
        trace = {"out": {"port": 1, "vlan": 123}}
        self.assertTrue(compare_uni_out_trace(uni, trace))

        # case3: UNI has VLAN but trace dont have, should return False
        trace = {"out": {"port": 1}}
        self.assertFalse(compare_uni_out_trace(uni, trace))

        # case4: UNI and trace dont have VLAN should return True
        uni.user_tag = None
        self.assertTrue(compare_uni_out_trace(uni, trace))

        # case5: UNI dont have VLAN but trace has, should return False
        trace = {"out": {"port": 1, "vlan": 123}}
        self.assertFalse(compare_uni_out_trace(uni, trace))
