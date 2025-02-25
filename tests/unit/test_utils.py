"""Module to test the utls.py file."""
from unittest.mock import MagicMock, Mock
import pytest

from kytos.core.common import EntityStatus
from napps.kytos.mef_eline.exceptions import DisabledSwitch
from napps.kytos.mef_eline.utils import (check_disabled_component,
                                         compare_endpoint_trace,
                                         compare_uni_out_trace,
                                         get_vlan_tags_and_masks, map_dl_vlan,
                                         merge_flow_dicts, prepare_delete_flow,
                                         _does_uni_affect_evc)


# pylint: disable=too-many-public-methods, too-many-lines
class TestUtils:
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
        interface = MagicMock()
        assert compare_uni_out_trace(None, interface, {})

        # case2: trace with valid port and VLAN, should return True
        interface.port_number = 1
        tag_value = 123
        trace = {"out": {"port": 1, "vlan": 123}}
        assert compare_uni_out_trace(tag_value, interface, trace)

        # case3: UNI has VLAN but trace dont have, should return False
        trace = {"out": {"port": 1}}
        assert compare_uni_out_trace(tag_value, interface, trace) is False

        # case4: UNI and trace dont have VLAN should return True
        assert compare_uni_out_trace(None, interface, trace)

        # case5: UNI dont have VLAN but trace has, should return False
        trace = {"out": {"port": 1, "vlan": 123}}
        assert compare_uni_out_trace(None, interface, trace) is False

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
                    101,
                    "102/4094",
                    "104/4088",
                    "112/4080",
                    "128/4032",
                    "192/4088",
                    200,
                ]
            ),
            (
                [[101, 90]],
                []
            ),
            (
                [[34, 34]],
                [34]
            ),
            (
                [
                    [34, 34],
                    [128, 128],
                    [130, 135]
                ],
                [
                    34,
                    128,
                    "130/4094",
                    "132/4092"
                ]
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

    @pytest.mark.parametrize(
        "src1,src2,src3,expected",
        [
            (
                {"dpida": [10, 11, 12]},
                {"dpida": [11, 20, 21]},
                {"dpidb": [30, 31, 32]},
                {"dpida": [10, 11, 12, 11, 20, 21], "dpidb": [30, 31, 32]},
            ),
            (
                {"dpida": [10, 11, 12]},
                {"dpida": [11, 20, 21], "dpidb": [40, 41, 42]},
                {"dpidb": [30, 31, 32]},
                {"dpida": [10, 11, 12, 11, 20, 21],
                 "dpidb": [40, 41, 42, 30, 31, 32]},
            ),
        ]
    )
    def test_merge_flow_dicts(self, src1, src2, src3, expected) -> None:
        """test merge flow dicts."""
        assert merge_flow_dicts({}, src1, src2, src3) == expected

    def test_prepare_delete_flow(self):
        """Test prepare_delete_flow"""
        cookie_mask = int(0xffffffffffffffff)
        flow_mod = {'00:01': [
            {
                'match': {'in_port': 1, 'dl_vlan': 22},
                'cookie': 12275899796742638400,
                'actions': [{'action_type': 'pop_vlan'}],
                'owner': 'mef_eline',
                'table_group': 'evpl',
                'table_id': 0,
                'priority': 20000
            },
            {
                'match': {'in_port': 3, 'dl_vlan': 1},
                'cookie': 12275899796742638400,
                'actions': [{'action_type': 'pop_vlan'}],
                'owner': 'mef_eline',
                'table_group': 'evpl',
                'table_id': 0,
                'priority': 20000
            }
        ]}
        actual_flows = prepare_delete_flow(flow_mod)
        assert '00:01' in actual_flows
        for i in range(len(actual_flows['00:01'])):
            assert (actual_flows['00:01'][i]['cookie'] ==
                    flow_mod["00:01"][i]['cookie'])
            assert (actual_flows['00:01'][i]['match'] ==
                    flow_mod["00:01"][i]['match'])
            assert actual_flows['00:01'][i]['cookie_mask'] == cookie_mask

    # pylint: disable=too-many-arguments
    @pytest.mark.parametrize(
        "intf_a_status, intf_z_status, is_active, is_uni, event, expected",
        [
            # link_DOWN
            (
                EntityStatus.DOWN, EntityStatus.DOWN,
                True, True, 'down', True
            ),
            (
                EntityStatus.UP, EntityStatus.UP,
                True, True, 'down', False
            ),
            (
                EntityStatus.DOWN, EntityStatus.UP,
                False, True, 'down', False
            ),
            (
                EntityStatus.UP, EntityStatus.UP,
                False, True, 'down', False
            ),
            (  # Not UNI
                EntityStatus.DOWN, EntityStatus.DOWN,
                True, False, 'down', False
            ),
            # link_up
            (
                EntityStatus.DOWN, EntityStatus.DOWN,
                True, True, 'up', False
            ),
            (
                EntityStatus.UP, EntityStatus.UP,
                True, True, 'up', False
            ),
            (
                EntityStatus.DOWN, EntityStatus.UP,
                False, True, 'up', False
            ),
            (
                EntityStatus.UP, EntityStatus.UP,
                False, True, 'up', True
            ),
            (  # Not UNI
                EntityStatus.UP, EntityStatus.UP,
                False, False, 'up', False
            ),
        ]
    )
    def test_does_uni_affect_evc(
        self,
        intf_a_status,
        intf_z_status,
        is_active,
        is_uni,
        event,
        expected
    ):
        """Test _does_uni_affect_evc when interface."""
        evc = Mock()
        evc.uni_a.interface.status = intf_a_status
        evc.uni_z.interface.status = intf_z_status
        if is_uni:
            interface = evc.uni_a.interface
        else:
            interface = Mock()
        evc.is_active.return_value = is_active
        assert _does_uni_affect_evc(evc, interface, event) is expected
