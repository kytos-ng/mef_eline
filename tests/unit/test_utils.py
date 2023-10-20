"""Module to test the utls.py file."""
from unittest.mock import MagicMock
import pytest


from kytos.core.common import EntityStatus
from napps.kytos.mef_eline.exceptions import DisabledSwitch
from napps.kytos.mef_eline.utils import (check_disabled_component,
                                         compare_endpoint_trace,
                                         compare_uni_out_trace,
                                         get_vlan_tags_and_masks, map_dl_vlan)


# pylint: disable=too-many-public-methods, too-many-lines
class TestUtils():
    """Test utility functions."""

    @pytest.mark.parametrize(
        "switch,expected",
        [
            (
                MagicMock(dpid="1234"),
                True
            ),
            (
                MagicMock(dpid="2345"),
                False
            )
        ]
    )
    def test_compare_endpoint_trace(self, switch, expected):
        """Test method compare_endpoint_trace"""
        trace = {"dpid": "1234", "port": 2, "vlan": 123}

        endpoint = MagicMock()
        endpoint.port_number = 2
        vlan = 123
        endpoint.switch = switch
        assert compare_endpoint_trace(endpoint, vlan, trace) == expected
        assert compare_endpoint_trace(endpoint, None, trace) == expected

    def test_compare_uni_out_trace(self):
        """Test compare_uni_out_trace method."""
        # case1: trace without 'out' info, should return True
        uni = MagicMock()
        assert compare_uni_out_trace(uni, {})

        # case2: trace with valid port and VLAN, should return True
        uni.interface.port_number = 1
        uni.user_tag.value = 123
        trace = {"out": {"port": 1, "vlan": 123}}
        assert compare_uni_out_trace(uni, trace)

        # case3: UNI has VLAN but trace dont have, should return False
        trace = {"out": {"port": 1}}
        assert compare_uni_out_trace(uni, trace) is False

        # case4: UNI and trace dont have VLAN should return True
        uni.user_tag = None
        assert compare_uni_out_trace(uni, trace)

        # case5: UNI dont have VLAN but trace has, should return False
        trace = {"out": {"port": 1, "vlan": 123}}
        assert compare_uni_out_trace(uni, trace) is False

    def test_map_dl_vlan(self):
        """Test map_dl_vlan"""
        cases = {0: None, "untagged": None, "any": 1, "4096/4096": 1, 10: 10}
        for value, mapped in cases.items():
            result = map_dl_vlan(value)
            assert result == mapped

    @pytest.mark.parametrize(
        "vlan_range,expected",
        [
            (
                [[101, 200]],
                [
                    "101/4095",
                    "102/4094",
                    "104/4088",
                    "112/4080",
                    "128/4032",
                    "192/4088",
                    "200/4095",
                ]
            ),
            (
                [[101, 90]],
                []
            ),
            (
                [[34, 34]],
                ["34/4095"]
            )
        ]
    )
    def test_get_vlan_tags_and_masks(self, vlan_range, expected):
        """Test get_vlan_tags_and_masks"""
        assert get_vlan_tags_and_masks(vlan_range) == expected

    def test_check_disabled_component(self):
        """Test check disabled component"""
        uni_a = MagicMock()
        switch = MagicMock()
        switch.status = EntityStatus.DISABLED
        uni_a.interface.switch = switch

        uni_z = MagicMock()
        uni_z.interface.switch = switch

        # Switch disabled
        with pytest.raises(DisabledSwitch):
            check_disabled_component(uni_a, uni_z)

        # Uni_a interface disabled
        switch.status = EntityStatus.UP
        uni_a.interface.status = EntityStatus.DISABLED
        with pytest.raises(DisabledSwitch):
            check_disabled_component(uni_a, uni_z)

        # Uni_z interface disabled
        uni_a.interface.status = EntityStatus.UP
        uni_z.interface.status = EntityStatus.DISABLED
        with pytest.raises(DisabledSwitch):
            check_disabled_component(uni_a, uni_z)

        # There is no disabled component
        uni_z.interface.status = EntityStatus.UP
        check_disabled_component(uni_a, uni_z)
