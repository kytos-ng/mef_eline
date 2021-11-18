"""Module to test the utls.py file."""
from unittest import TestCase
from unittest.mock import MagicMock

from napps.kytos.mef_eline.utils import compare_endpoint_trace


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
