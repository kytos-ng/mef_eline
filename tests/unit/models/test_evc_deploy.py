"""Method to thest EVCDeploy class."""
import sys
from unittest.mock import MagicMock, Mock, call, patch
import operator
import pytest
from kytos.lib.helpers import get_controller_mock

from kytos.core.common import EntityStatus
from kytos.core.exceptions import KytosNoTagAvailableError
from kytos.core.interface import Interface
from kytos.core.switch import Switch

# pylint: disable=wrong-import-position
sys.path.insert(0, "/var/lib/kytos/napps/..")
# pylint: enable=wrong-import-position

from napps.kytos.mef_eline.exceptions import FlowModException  # NOQA
from napps.kytos.mef_eline.models import EVC, EVCDeploy, Path  # NOQA
from napps.kytos.mef_eline.settings import (ANY_SB_PRIORITY,  # NOQA
                                            EPL_SB_PRIORITY, EVPL_SB_PRIORITY,
                                            MANAGER_URL, SDN_TRACE_CP_URL,
                                            UNTAGGED_SB_PRIORITY)
from napps.kytos.mef_eline.tests.helpers import (get_link_mocked,  # NOQA
                                                 get_uni_mocked)


# pylint: disable=too-many-public-methods, too-many-lines
class TestEVC():
    """Tests to verify EVC class."""

    def setup_method(self):
        """Setup method"""
        attributes = {
            "controller": get_controller_mock(),
            "name": "circuit_for_tests",
            "uni_a": get_uni_mocked(is_valid=True),
            "uni_z": get_uni_mocked(is_valid=True),
        }
        self.evc_deploy = EVCDeploy(**attributes)

    def test_primary_links_zipped(self):
        """Test primary links zipped method."""

    @staticmethod
    @patch("napps.kytos.mef_eline.models.evc.log")
    def test_should_deploy_case1(log_mock):
        """Test should deploy method without primary links."""
        log_mock.debug.return_value = True
        attributes = {
            "controller": get_controller_mock(),
            "name": "custom_name",
            "uni_a": get_uni_mocked(is_valid=True),
            "uni_z": get_uni_mocked(is_valid=True),
        }

        evc = EVC(**attributes)
        evc.should_deploy()
        log_mock.debug.assert_called_with("Path is empty.")

    @patch("napps.kytos.mef_eline.models.evc.log")
    def test_should_deploy_case2(self, log_mock):
        """Test should deploy method with disable circuit."""
        log_mock.debug.return_value = True
        attributes = {
            "controller": get_controller_mock(),
            "name": "custom_name",
            "uni_a": get_uni_mocked(is_valid=True),
            "uni_z": get_uni_mocked(is_valid=True),
            "primary_links": [get_link_mocked(), get_link_mocked()],
        }
        evc = EVC(**attributes)

        assert evc.should_deploy(attributes["primary_links"]) is False
        log_mock.debug.assert_called_with(f"{evc} is disabled.")

    @patch("napps.kytos.mef_eline.models.evc.log")
    def test_should_deploy_case3(self, log_mock):
        """Test should deploy method with enabled and not active circuit."""
        log_mock.debug.return_value = True
        attributes = {
            "controller": get_controller_mock(),
            "name": "custom_name",
            "uni_a": get_uni_mocked(is_valid=True),
            "uni_z": get_uni_mocked(is_valid=True),
            "primary_links": [get_link_mocked(), get_link_mocked()],
            "enabled": True,
        }
        evc = EVC(**attributes)
        assert evc.should_deploy(attributes["primary_links"]) is True
        log_mock.debug.assert_called_with(f"{evc} will be deployed.")

    @patch("napps.kytos.mef_eline.models.evc.log")
    def test_should_deploy_case4(self, log_mock):
        """Test should deploy method with enabled and active circuit."""
        log_mock.debug.return_value = True
        attributes = {
            "controller": get_controller_mock(),
            "name": "custom_name",
            "uni_a": get_uni_mocked(is_valid=True),
            "uni_z": get_uni_mocked(is_valid=True),
            "primary_links": [get_link_mocked(), get_link_mocked()],
            "enabled": True,
            "active": True,
        }
        evc = EVC(**attributes)
        assert evc.should_deploy(attributes["primary_links"]) is False

    @patch("napps.kytos.mef_eline.models.evc.requests")
    def test_send_flow_mods_case1(self, requests_mock):
        """Test if you are sending flow_mods."""
        flow_mods = {"id": 20}
        switch = Mock(spec=Switch, id=1)

        response = MagicMock()
        response.status_code = 201
        requests_mock.post.return_value = response

        # pylint: disable=protected-access
        EVC._send_flow_mods(switch.id, flow_mods)

        expected_endpoint = f"{MANAGER_URL}/flows/{switch.id}"
        expected_data = {"flows": flow_mods, "force": False}
        assert requests_mock.post.call_count == 1
        requests_mock.post.assert_called_once_with(
            expected_endpoint, json=expected_data
        )

    @patch("napps.kytos.mef_eline.models.evc.requests")
    def test_send_flow_mods_case2(self, requests_mock):
        """Test if you are sending flow_mods."""
        flow_mods = {"id": 20}
        switch = Mock(spec=Switch, id=1)
        response = MagicMock()
        response.status_code = 201
        requests_mock.post.return_value = response

        # pylint: disable=protected-access
        EVC._send_flow_mods(switch.id, flow_mods, command='delete', force=True)

        expected_endpoint = f"{MANAGER_URL}/delete/{switch.id}"
        expected_data = {"flows": flow_mods, "force": True}
        assert requests_mock.post.call_count == 1
        requests_mock.post.assert_called_once_with(
            expected_endpoint, json=expected_data
        )

    @patch("napps.kytos.mef_eline.models.evc.requests")
    def test_send_flow_mods_error(self, requests_mock):
        """Test flow_manager call fails."""
        flow_mods = {"id": 20}
        switch = Mock(spec=Switch, id=1)
        response = MagicMock()
        response.status_code = 415
        requests_mock.post.return_value = response

        # pylint: disable=protected-access
        with pytest.raises(FlowModException):
            EVC._send_flow_mods(
                switch.id,
                flow_mods,
                command='delete',
                force=True
            )

    def test_prepare_flow_mod(self):
        """Test prepare flow_mod method."""
        interface_a = Interface("eth0", 1, Mock(spec=Switch))
        interface_z = Interface("eth1", 3, Mock(spec=Switch))
        attributes = {
            "table_group": {"epl": 0, "evpl": 0},
            "controller": get_controller_mock(),
            "name": "custom_name",
            "uni_a": get_uni_mocked(is_valid=True),
            "uni_z": get_uni_mocked(is_valid=True),
            "primary_links": [get_link_mocked(), get_link_mocked()],
            "enabled": True,
            "active": True,
        }
        evc = EVC(**attributes)

        # pylint: disable=protected-access
        flow_mod = evc._prepare_flow_mod(interface_a, interface_z)
        expected_flow_mod = {
            "match": {"in_port": interface_a.port_number},
            "cookie": evc.get_cookie(),
            "owner": "mef_eline",
            "actions": [
                {"action_type": "output", "port": interface_z.port_number}
            ],
            "priority": EVPL_SB_PRIORITY,
            "table_group": "evpl",
            "table_id": 0,
        }
        assert expected_flow_mod == flow_mod

    def test_prepare_pop_flow(self):
        """Test prepare pop flow  method."""
        attributes = {
            "table_group": {"epl": 0, "evpl": 0},
            "controller": get_controller_mock(),
            "name": "custom_name",
            "uni_a": get_uni_mocked(interface_port=1, is_valid=True),
            "uni_z": get_uni_mocked(interface_port=2, is_valid=True),
        }
        evc = EVC(**attributes)
        interface_a = evc.uni_a.interface
        interface_z = evc.uni_z.interface
        in_vlan = 10

        # pylint: disable=protected-access
        flow_mod = evc._prepare_pop_flow(
            interface_a, interface_z, in_vlan
        )

        expected_flow_mod = {
            "match": {"in_port": interface_a.port_number,
                      "dl_vlan": in_vlan},
            "cookie": evc.get_cookie(),
            "owner": "mef_eline",
            "actions": [
                {"action_type": "pop_vlan"},
                {"action_type": "output", "port": interface_z.port_number},
            ],
            "priority": EVPL_SB_PRIORITY,
            "table_group": "evpl",
            "table_id": 0,
        }
        assert expected_flow_mod == flow_mod

    # pylint: disable=too-many-branches
    @pytest.mark.parametrize(
        "in_vlan_a,in_vlan_z",
        [
            (100, 50),
            (100, 100),
            (100, "4096/4096"),
            (100, 0),
            (100, None),
            ("4096/4096", 50),
            ("4096/4096", "4096/4096"),
            ("4096/4096", 0),
            ("4096/4096", None),
            (0, 50),
            (0, "4096/4096"),
            (0, 0),
            (0, None),
            (None, 50),
            (None, "4096/4096"),
            (None, 0),
            (None, None),
        ]
    )
    def test_prepare_push_flow(self, in_vlan_a, in_vlan_z):
        """Test prepare push flow method."""
        attributes = {
            "table_group": {"evpl": 3, "epl": 4},
            "controller": get_controller_mock(),
            "name": "custom_name",
            "uni_a": get_uni_mocked(interface_port=1, is_valid=True),
            "uni_z": get_uni_mocked(interface_port=2, is_valid=True),
        }
        evc = EVC(**attributes)
        interface_a = evc.uni_a.interface
        interface_z = evc.uni_z.interface
        out_vlan_a = 20

        # pylint: disable=protected-access
        flow_mod = evc._prepare_push_flow(interface_a, interface_z,
                                          in_vlan_a, out_vlan_a,
                                          in_vlan_z)
        expected_flow_mod = {
            'match': {'in_port': interface_a.port_number},
            'cookie': evc.get_cookie(),
            'owner': 'mef_eline',
            'table_id': 3,
            'table_group': 'evpl',
            'actions': [
                {'action_type': 'push_vlan', 'tag_type': 's'},
                {'action_type': 'set_vlan', 'vlan_id': out_vlan_a},
                {
                    'action_type': 'output',
                    'port': interface_z.port_number
                }
            ],
            "priority": EVPL_SB_PRIORITY,
        }
        expected_flow_mod["priority"] = evc.get_priority(in_vlan_a)
        if in_vlan_a is not None:
            expected_flow_mod['match']['dl_vlan'] = in_vlan_a
        if in_vlan_z not in evc.special_cases and in_vlan_a != in_vlan_z:
            new_action = {"action_type": "set_vlan",
                          "vlan_id": in_vlan_z}
            expected_flow_mod["actions"].insert(0, new_action)
        if in_vlan_a not in evc.special_cases:
            if in_vlan_z == 0:
                new_action = {"action_type": "pop_vlan"}
                expected_flow_mod["actions"].insert(0, new_action)
        elif in_vlan_a == "4096/4096":
            if in_vlan_z == 0:
                new_action = {"action_type": "pop_vlan"}
                expected_flow_mod["actions"].insert(0, new_action)
        elif not in_vlan_a:
            if in_vlan_a is None:
                expected_flow_mod["table_group"] = "epl"
                expected_flow_mod["table_id"] = 4
            if in_vlan_z not in evc.special_cases:
                new_action = {"action_type": "push_vlan",
                              "tag_type": "c"}
                expected_flow_mod["actions"].insert(0, new_action)
        assert expected_flow_mod == flow_mod

    @staticmethod
    @patch("napps.kytos.mef_eline.models.evc.EVC._send_flow_mods")
    def test_install_uni_flows(send_flow_mods_mock):
        """Test install uni flows method.

        This test will verify the flows send to the send_flow_mods method.
        """
        evc = TestEVC.create_evc_inter_switch()

        # pylint: disable=protected-access
        evc._install_uni_flows()
        send_flow_mods_mock.assert_not_called()

        # pylint: disable=protected-access
        evc._install_uni_flows(evc.primary_links)

        expected_flow_mod_a = [
            {
                "match": {
                    "in_port": evc.uni_a.interface.port_number,
                    "dl_vlan": evc.uni_a.user_tag.value,
                },
                "cookie": evc.get_cookie(),
                "owner": "mef_eline",
                "table_group": "evpl",
                "table_id": 0,
                "actions": [
                    {
                        "action_type": "set_vlan",
                        "vlan_id": evc.uni_z.user_tag.value
                    },
                    {"action_type": "push_vlan", "tag_type": "s"},
                    {
                        "action_type": "set_vlan",
                        "vlan_id": evc.primary_links[0]
                        .get_metadata("s_vlan")
                        .value,
                    },
                    {
                        "action_type": "output",
                        "port": evc.primary_links[0].endpoint_a.port_number,
                    },
                ],
                "priority": EVPL_SB_PRIORITY,
            },
            {
                "match": {
                    "in_port": evc.primary_links[0].endpoint_a.port_number,
                    "dl_vlan": evc.primary_links[0]
                    .get_metadata("s_vlan")
                    .value,
                },
                "cookie": evc.get_cookie(),
                "owner": "mef_eline",
                "table_group": "evpl",
                "table_id": 0,
                "actions": [
                    {"action_type": "pop_vlan"},
                    {
                        "action_type": "output",
                        "port": evc.uni_a.interface.port_number,
                    },
                ],
                "priority": EVPL_SB_PRIORITY,
            },
        ]

        send_flow_mods_mock.assert_any_call(
            evc.uni_a.interface.switch.id, expected_flow_mod_a
        )

        expected_flow_mod_z = [
            {
                "match": {
                    "in_port": evc.uni_z.interface.port_number,
                    "dl_vlan": evc.uni_z.user_tag.value,
                },
                "cookie": evc.get_cookie(),
                "owner": "mef_eline",
                "table_group": "evpl",
                "table_id": 0,
                "actions": [
                    {
                        "action_type": "set_vlan",
                        "vlan_id": evc.uni_a.user_tag.value
                    },
                    {"action_type": "push_vlan", "tag_type": "s"},
                    {
                        "action_type": "set_vlan",
                        "vlan_id": evc.primary_links[-1]
                        .get_metadata("s_vlan")
                        .value,
                    },
                    {
                        "action_type": "output",
                        "port": evc.primary_links[-1].endpoint_b.port_number,
                    },
                ],
                "priority": EVPL_SB_PRIORITY,
            },
            {
                "match": {
                    "in_port": evc.primary_links[-1].endpoint_b.port_number,
                    "dl_vlan": evc.primary_links[-1]
                    .get_metadata("s_vlan")
                    .value,
                },
                "cookie": evc.get_cookie(),
                "owner": "mef_eline",
                "table_group": "evpl",
                "table_id": 0,
                "actions": [
                    {"action_type": "pop_vlan"},
                    {
                        "action_type": "output",
                        "port": evc.uni_z.interface.port_number,
                    },
                ],
                "priority": EVPL_SB_PRIORITY,
            },
        ]

        send_flow_mods_mock.assert_any_call(
            evc.uni_z.interface.switch.id, expected_flow_mod_z
        )

    @staticmethod
    def create_evc_inter_switch(tag_value_a=82, tag_value_z=83):
        """Create inter-switch EVC with two links in the path"""
        uni_a = get_uni_mocked(
            interface_port=2,
            tag_value=tag_value_a,
            switch_id=1,
            switch_dpid=1,
            is_valid=True,
        )
        uni_z = get_uni_mocked(
            interface_port=3,
            tag_value=tag_value_z,
            switch_id=3,
            switch_dpid=3,
            is_valid=True,
        )

        attributes = {
            "controller": get_controller_mock(),
            "name": "custom_name",
            "id": "1",
            "uni_a": uni_a,
            "uni_z": uni_z,
            "primary_links": [
                get_link_mocked(
                    switch_a=Switch(1),
                    switch_b=Switch(2),
                    endpoint_a_port=9,
                    endpoint_b_port=10,
                    metadata={"s_vlan": 5},
                ),
                get_link_mocked(
                    switch_a=Switch(2),
                    switch_b=Switch(3),
                    endpoint_a_port=11,
                    endpoint_b_port=12,
                    metadata={"s_vlan": 6},
                ),
            ],
            "table_group": {"epl": 0, "evpl": 0}
        }
        return EVC(**attributes)

    @staticmethod
    @patch("napps.kytos.mef_eline.models.evc.EVC._send_flow_mods")
    def test_install_nni_flows(send_flow_mods_mock):
        """Test install nni flows method.

        This test will verify the flows send to the send_flow_mods method.
        """
        evc = TestEVC.create_evc_inter_switch()

        # pylint: disable=protected-access
        evc._install_nni_flows(evc.primary_links)

        in_vlan = evc.primary_links[0].get_metadata("s_vlan").value
        out_vlan = evc.primary_links[-1].get_metadata("s_vlan").value

        in_port = evc.primary_links[0].endpoint_b.port_number
        out_port = evc.primary_links[-1].endpoint_a.port_number

        expected_flow_mods = [
            {
                "match": {"in_port": in_port, "dl_vlan": in_vlan},
                "cookie": evc.get_cookie(),
                "owner": "mef_eline",
                "table_group": "evpl",
                "table_id": 0,
                "actions": [
                    {"action_type": "set_vlan", "vlan_id": out_vlan},
                    {"action_type": "output", "port": out_port},
                ],
                "priority": EVPL_SB_PRIORITY
            },
            {
                "match": {"in_port": out_port, "dl_vlan": out_vlan},
                "cookie": evc.get_cookie(),
                "owner": "mef_eline",
                "table_group": "evpl",
                "table_id": 0,
                "actions": [
                    {"action_type": "set_vlan", "vlan_id": in_vlan},
                    {"action_type": "output", "port": in_port},
                ],
                "priority": EVPL_SB_PRIORITY,
            },
        ]

        dpid = evc.primary_links[0].endpoint_b.switch.id
        send_flow_mods_mock.assert_called_once_with(dpid, expected_flow_mods)

    @patch("requests.post")
    @patch("napps.kytos.mef_eline.controllers.ELineController.upsert_evc")
    @patch("napps.kytos.mef_eline.models.evc.log")
    @patch("napps.kytos.mef_eline.models.path.Path.choose_vlans")
    @patch("napps.kytos.mef_eline.models.evc.EVC._install_nni_flows")
    @patch("napps.kytos.mef_eline.models.evc.EVC._install_uni_flows")
    @patch("napps.kytos.mef_eline.models.evc.EVC._install_direct_uni_flows")
    @patch("napps.kytos.mef_eline.models.evc.EVC.activate")
    @patch("napps.kytos.mef_eline.models.evc.EVC.should_deploy")
    def test_deploy_successfully(self, *args):
        """Test if all methods to deploy are called."""
        # pylint: disable=too-many-locals
        (
            should_deploy_mock,
            activate_mock,
            install_direct_uni_flows_mock,
            install_uni_flows_mock,
            install_nni_flows,
            chose_vlans_mock,
            log_mock,
            _,
            requests_mock,
        ) = args

        response = MagicMock()
        response.status_code = 201
        requests_mock.return_value = response

        should_deploy_mock.return_value = True
        evc = self.create_evc_inter_switch()
        deployed = evc.deploy_to_path(evc.primary_links)

        assert should_deploy_mock.call_count == 1
        assert activate_mock.call_count == 1
        assert install_uni_flows_mock.call_count == 1
        assert install_nni_flows.call_count == 1
        assert chose_vlans_mock.call_count == 1
        log_mock.info.assert_called_with(f"{evc} was deployed.")
        assert deployed is True

        # intra switch EVC
        evc = self.create_evc_intra_switch()
        assert evc.deploy_to_path(evc.primary_links) is True
        assert install_direct_uni_flows_mock.call_count == 1
        assert activate_mock.call_count == 2
        assert log_mock.info.call_count == 2
        log_mock.info.assert_called_with(f"{evc} was deployed.")

    @patch("requests.post")
    @patch("napps.kytos.mef_eline.models.evc.log")
    @patch("napps.kytos.mef_eline.models.evc.EVC.discover_new_paths")
    @patch("napps.kytos.mef_eline.models.path.Path.choose_vlans")
    @patch("napps.kytos.mef_eline.models.evc.EVC._install_nni_flows")
    @patch("napps.kytos.mef_eline.models.evc.EVC._install_uni_flows")
    @patch("napps.kytos.mef_eline.models.evc.EVC.activate")
    @patch("napps.kytos.mef_eline.models.evc.EVC.should_deploy")
    @patch("napps.kytos.mef_eline.models.EVC.sync")
    def test_deploy_fail(self, *args):
        """Test if all methods is ignored when the should_deploy is false."""
        # pylint: disable=too-many-locals
        (
            sync_mock,
            should_deploy_mock,
            activate_mock,
            install_uni_flows_mock,
            install_nni_flows,
            choose_vlans_mock,
            discover_new_paths_mock,
            log_mock,
            requests_mock,
        ) = args

        response = MagicMock()
        response.status_code = 201
        requests_mock.return_value = response

        evc = self.create_evc_inter_switch()
        should_deploy_mock.return_value = False
        discover_new_paths_mock.return_value = []
        deployed = evc.deploy_to_path()

        assert discover_new_paths_mock.call_count == 1
        assert should_deploy_mock.call_count == 1
        assert activate_mock.call_count == 0
        assert install_uni_flows_mock.call_count == 0
        assert install_nni_flows.call_count == 0
        assert choose_vlans_mock.call_count == 0
        assert log_mock.info.call_count == 0
        assert sync_mock.call_count == 1
        assert deployed is False

        # NoTagAvailable on static path
        should_deploy_mock.return_value = True
        choose_vlans_mock.side_effect = KytosNoTagAvailableError("error")
        assert evc.deploy_to_path(evc.primary_links) is False

        # NoTagAvailable on dynamic path
        should_deploy_mock.return_value = False
        discover_new_paths_mock.return_value = [Path(['a', 'b'])]
        choose_vlans_mock.side_effect = KytosNoTagAvailableError("error")
        assert evc.deploy_to_path(evc.primary_links) is False

    @patch("napps.kytos.mef_eline.models.evc.log")
    @patch(
        "napps.kytos.mef_eline.models.evc.EVC.discover_new_paths",
        return_value=[],
    )
    @patch("napps.kytos.mef_eline.models.path.Path.choose_vlans")
    @patch("napps.kytos.mef_eline.models.evc.EVC._install_nni_flows")
    @patch("napps.kytos.mef_eline.models.evc.EVC.should_deploy")
    @patch("napps.kytos.mef_eline.models.evc.EVC.remove_current_flows")
    @patch("napps.kytos.mef_eline.models.evc.EVC.sync")
    def test_deploy_error(self, *args):
        """Test if all methods is ignored when the should_deploy is false."""
        # pylint: disable=too-many-locals
        (
            sync_mock,
            remove_current_flows,
            should_deploy_mock,
            install_nni_flows,
            choose_vlans_mock,
            discover_new_paths,
            log_mock,
        ) = args

        install_nni_flows.side_effect = FlowModException
        should_deploy_mock.return_value = True
        uni_a = get_uni_mocked(
            interface_port=2,
            tag_value=82,
            switch_id="switch_uni_a",
            is_valid=True,
        )
        uni_z = get_uni_mocked(
            interface_port=3,
            tag_value=83,
            switch_id="switch_uni_z",
            is_valid=True,
        )

        primary_links = [
            get_link_mocked(
                endpoint_a_port=9, endpoint_b_port=10, metadata={"s_vlan": 5}
            ),
            get_link_mocked(
                endpoint_a_port=11, endpoint_b_port=12, metadata={"s_vlan": 6}
            ),
        ]

        attributes = {
            "controller": get_controller_mock(),
            "name": "custom_name",
            "uni_a": uni_a,
            "uni_z": uni_z,
            "primary_links": primary_links,
            "queue_id": 5,
        }
        # Setup path to deploy
        path = Path()
        path.append(primary_links[0])
        path.append(primary_links[1])

        evc = EVC(**attributes)

        deployed = evc.deploy_to_path(path)

        assert discover_new_paths.call_count == 0
        assert should_deploy_mock.call_count == 1
        assert install_nni_flows.call_count == 1
        assert choose_vlans_mock.call_count == 1
        assert log_mock.error.call_count == 1
        assert sync_mock.call_count == 0
        assert remove_current_flows.call_count == 2
        assert deployed is False

    @patch("napps.kytos.mef_eline.models.evc.EVC.get_failover_path_candidates")
    @patch("napps.kytos.mef_eline.models.evc.EVC._install_nni_flows")
    @patch("napps.kytos.mef_eline.models.evc.EVC._install_uni_flows")
    @patch("napps.kytos.mef_eline.models.evc.EVC.remove_path_flows")
    @patch("napps.kytos.mef_eline.models.EVC.sync")
    def test_setup_failover_path(self, *args):
        """Test setup_failover_path method."""
        (
            sync_mock,
            remove_path_flows_mock,
            install_uni_flows_mock,
            install_nni_flows_mock,
            get_failover_path_candidates_mock,
        ) = args

        # case1: early return intra switch
        evc1 = self.create_evc_intra_switch()

        assert evc1.setup_failover_path() is False
        assert sync_mock.call_count == 0

        # case2: early return not eligible for path failover
        evc2 = self.create_evc_inter_switch()
        evc2.is_eligible_for_failover_path = MagicMock(return_value=False)

        assert evc2.setup_failover_path() is False
        assert sync_mock.call_count == 0

        # case3: success failover_path setup
        evc2.is_eligible_for_failover_path = MagicMock(return_value=True)
        evc2.failover_path = ["link1", "link2"]
        path_mock = MagicMock()
        path_mock.__iter__.return_value = ["link3"]
        get_failover_path_candidates_mock.return_value = [None, path_mock]

        assert evc2.setup_failover_path() is True
        remove_path_flows_mock.assert_called_with(["link1", "link2"])
        path_mock.choose_vlans.assert_called()
        install_nni_flows_mock.assert_called_with(path_mock)
        install_uni_flows_mock.assert_called_with(path_mock, skip_in=True)
        assert evc2.failover_path == path_mock
        assert sync_mock.call_count == 1

        # case 4: failed to setup failover_path - No Tag available
        evc2.failover_path = []
        path_mock.choose_vlans.side_effect = KytosNoTagAvailableError("error")
        sync_mock.call_count = 0

        assert evc2.setup_failover_path() is False
        assert len(list(evc2.failover_path)) == 0
        assert sync_mock.call_count == 1

        # case 5: failed to setup failover_path - FlowMod exception
        evc2.failover_path = []
        path_mock.choose_vlans.side_effect = None
        install_nni_flows_mock.side_effect = FlowModException("error")
        sync_mock.call_count = 0

        assert evc2.setup_failover_path() is False
        assert len(list(evc2.failover_path)) == 0
        assert sync_mock.call_count == 1
        remove_path_flows_mock.assert_called_with(path_mock)

    @patch("napps.kytos.mef_eline.models.evc.EVC.deploy_to_path")
    @patch("napps.kytos.mef_eline.models.evc.EVC.discover_new_paths")
    def test_deploy_to_backup_path1(
        self, discover_new_paths_mocked, deploy_to_path_mocked
    ):
        """Test deployment when dynamic_backup_path is False in same switch"""
        uni_a = get_uni_mocked(interface_port=2, tag_value=82, is_valid=True)
        uni_z = get_uni_mocked(interface_port=3, tag_value=83, is_valid=True)

        switch = Mock(spec=Switch)
        uni_a.interface.switch = switch
        uni_z.interface.switch = switch

        attributes = {
            "controller": get_controller_mock(),
            "name": "custom_name",
            "uni_a": uni_a,
            "uni_z": uni_z,
            "enabled": True,
            "dynamic_backup_path": False,
        }

        evc = EVC(**attributes)
        discover_new_paths_mocked.return_value = []
        deploy_to_path_mocked.return_value = True

        deployed = evc.deploy_to_backup_path()

        deploy_to_path_mocked.assert_called_once_with()
        assert deployed is True

    @patch("requests.post")
    @patch("napps.kytos.mef_eline.controllers.ELineController.upsert_evc")
    @patch("napps.kytos.mef_eline.models.evc.log")
    @patch("napps.kytos.mef_eline.models.path.Path.choose_vlans")
    @patch("napps.kytos.mef_eline.models.evc.EVC._install_nni_flows")
    @patch("napps.kytos.mef_eline.models.evc.EVC._install_uni_flows")
    @patch("napps.kytos.mef_eline.models.evc.EVC.activate")
    @patch("napps.kytos.mef_eline.models.evc.EVC.should_deploy")
    @patch("napps.kytos.mef_eline.models.evc.EVC.discover_new_paths")
    def test_deploy_without_path_case1(self, *args):
        """Test if not path is found a dynamic path is used."""
        # pylint: disable=too-many-locals
        (
            discover_new_paths_mocked,
            should_deploy_mock,
            activate_mock,
            install_uni_flows_mock,
            install_nni_flows,
            chose_vlans_mock,
            log_mock,
            _,
            requests_mock,
        ) = args

        response = MagicMock()
        response.status_code = 201
        requests_mock.return_value = response

        should_deploy_mock.return_value = False
        uni_a = get_uni_mocked(
            interface_port=2,
            tag_value=82,
            switch_id="switch_uni_a",
            is_valid=True,
        )
        uni_z = get_uni_mocked(
            interface_port=3,
            tag_value=83,
            switch_id="switch_uni_z",
            is_valid=True,
        )

        attributes = {
            "controller": get_controller_mock(),
            "name": "custom_name",
            "uni_a": uni_a,
            "uni_z": uni_z,
            "enabled": True,
            "dynamic_backup_path": False,
        }

        dynamic_backup_path = Path(
            [
                get_link_mocked(
                    endpoint_a_port=9,
                    endpoint_b_port=10,
                    metadata={"s_vlan": 5},
                ),
                get_link_mocked(
                    endpoint_a_port=11,
                    endpoint_b_port=12,
                    metadata={"s_vlan": 6},
                ),
            ]
        )

        evc = EVC(**attributes)
        discover_new_paths_mocked.return_value = [dynamic_backup_path]

        deployed = evc.deploy_to_path()

        assert should_deploy_mock.call_count == 1
        assert discover_new_paths_mocked.call_count == 1
        assert activate_mock.call_count == 1
        assert install_uni_flows_mock.call_count == 1
        assert install_nni_flows.call_count == 1
        assert chose_vlans_mock.call_count == 1
        log_mock.info.assert_called_with(f"{evc} was deployed.")
        assert deployed is True

    @patch("napps.kytos.mef_eline.models.evc.EVCDeploy.deploy_to_primary_path")
    @patch("napps.kytos.mef_eline.models.evc.EVCDeploy.deploy_to_backup_path")
    @patch("napps.kytos.mef_eline.models.evc.emit_event")
    def test_deploy(self, *args):
        """Test method deploy"""
        (emit_event_mock, deploy_primary_mock, deploy_backup_mock) = args

        # case 1: deploy to primary
        self.evc_deploy.archived = False
        deploy_primary_mock.return_value = True
        assert self.evc_deploy.deploy()
        assert emit_event_mock.call_count == 1

        # case 2: deploy to backup
        deploy_primary_mock.return_value = False
        deploy_backup_mock.return_value = True
        assert self.evc_deploy.deploy()
        assert emit_event_mock.call_count == 2

        # case 3: fail to deploy to primary and backup
        deploy_backup_mock.return_value = False
        assert self.evc_deploy.deploy() is False
        assert emit_event_mock.call_count == 2

        # case 4: archived
        self.evc_deploy.archived = True
        assert self.evc_deploy.deploy() is False
        assert emit_event_mock.call_count == 2

    @patch("napps.kytos.mef_eline.models.evc.EVCDeploy.remove_current_flows")
    @patch("napps.kytos.mef_eline.models.evc.EVCDeploy.sync")
    @patch("napps.kytos.mef_eline.models.evc.emit_event")
    def test_remove(self, *args):
        """Test method remove"""
        (emit_event_mock, sync_mock, remove_flows_mock) = args
        self.evc_deploy.remove()
        remove_flows_mock.assert_called()
        sync_mock.assert_called()
        emit_event_mock.assert_called()
        assert self.evc_deploy.is_enabled() is False

    @patch("napps.kytos.mef_eline.controllers.ELineController.upsert_evc")
    @patch("napps.kytos.mef_eline.models.evc.EVC._send_flow_mods")
    @patch("napps.kytos.mef_eline.models.evc.log.error")
    def test_remove_current_flows(self, *args):
        """Test remove current flows."""
        # pylint: disable=too-many-locals
        (log_error_mock, send_flow_mods_mocked, _) = args
        uni_a = get_uni_mocked(
            interface_port=2,
            tag_value=82,
            switch_id="switch_uni_a",
            is_valid=True,
        )
        uni_z = get_uni_mocked(
            interface_port=3,
            tag_value=83,
            switch_id="switch_uni_z",
            is_valid=True,
        )

        switch_a = Switch("00:00:00:00:00:01")
        switch_b = Switch("00:00:00:00:00:02")
        switch_c = Switch("00:00:00:00:00:03")

        attributes = {
            "controller": get_controller_mock(),
            "name": "custom_name",
            "uni_a": uni_a,
            "uni_z": uni_z,
            "active": True,
            "enabled": True,
            "primary_links": [
                get_link_mocked(
                    switch_a=switch_a,
                    switch_b=switch_b,
                    endpoint_a_port=9,
                    endpoint_b_port=10,
                    metadata={"s_vlan": 5},
                ),
                get_link_mocked(
                    switch_a=switch_b,
                    switch_b=switch_c,
                    endpoint_a_port=11,
                    endpoint_b_port=12,
                    metadata={"s_vlan": 6},
                ),
            ],
        }

        evc = EVC(**attributes)

        evc.current_path = evc.primary_links
        evc.remove_current_flows()

        assert send_flow_mods_mocked.call_count == 5
        assert evc.is_active() is False
        flows = [
            {"cookie": evc.get_cookie(), "cookie_mask": 18446744073709551615}
        ]
        switch_1 = evc.primary_links[0].endpoint_a.switch
        switch_2 = evc.primary_links[0].endpoint_b.switch
        send_flow_mods_mocked.assert_any_call(switch_1.id, flows, 'delete',
                                              force=True)
        send_flow_mods_mocked.assert_any_call(switch_2.id, flows, 'delete',
                                              force=True)

        send_flow_mods_mocked.side_effect = FlowModException("error")
        evc.remove_current_flows()
        log_error_mock.assert_called()

    @patch("napps.kytos.mef_eline.controllers.ELineController.upsert_evc")
    @patch("napps.kytos.mef_eline.models.evc.EVC._send_flow_mods")
    @patch("napps.kytos.mef_eline.models.evc.log.error")
    def test_remove_failover_flows_exclude_uni_switches(self, *args):
        """Test remove failover flows excluding UNI switches."""
        # pylint: disable=too-many-locals
        (log_error_mock, send_flow_mods_mocked, mock_upsert) = args
        uni_a = get_uni_mocked(
            interface_port=2,
            tag_value=82,
            switch_id="00:00:00:00:00:00:00:01",
            is_valid=True,
        )
        uni_z = get_uni_mocked(
            interface_port=3,
            tag_value=83,
            switch_id="00:00:00:00:00:00:00:03",
            is_valid=True,
        )

        switch_a = Switch("00:00:00:00:00:00:00:01")
        switch_b = Switch("00:00:00:00:00:00:00:02")
        switch_c = Switch("00:00:00:00:00:00:00:03")

        attributes = {
            "controller": get_controller_mock(),
            "name": "custom_name",
            "uni_a": uni_a,
            "uni_z": uni_z,
            "active": True,
            "enabled": True,
            "failover_path": [
                get_link_mocked(
                    switch_a=switch_a,
                    switch_b=switch_b,
                    endpoint_a_port=9,
                    endpoint_b_port=10,
                    metadata={"s_vlan": 5},
                ),
                get_link_mocked(
                    switch_a=switch_b,
                    switch_b=switch_c,
                    endpoint_a_port=11,
                    endpoint_b_port=12,
                    metadata={"s_vlan": 6},
                ),
            ],
        }

        evc = EVC(**attributes)
        evc.remove_failover_flows(exclude_uni_switches=True, sync=True)

        assert send_flow_mods_mocked.call_count == 1
        flows = [
            {"cookie": evc.get_cookie(),
             "cookie_mask": int(0xffffffffffffffff)}
        ]
        send_flow_mods_mocked.assert_any_call(switch_b.id, flows, 'delete',
                                              force=True)
        assert mock_upsert.call_count == 1

        send_flow_mods_mocked.side_effect = FlowModException("error")
        evc.remove_current_flows()
        log_error_mock.assert_called()

    @patch("napps.kytos.mef_eline.controllers.ELineController.upsert_evc")
    @patch("napps.kytos.mef_eline.models.evc.EVC._send_flow_mods")
    def test_remove_failover_flows_include_all(self, *args):
        """Test remove failover flows including UNI switches."""
        # pylint: disable=too-many-locals
        (send_flow_mods_mocked, mock_upsert) = args
        uni_a = get_uni_mocked(
            interface_port=2,
            tag_value=82,
            switch_id="00:00:00:00:00:00:00:01",
            is_valid=True,
        )
        uni_z = get_uni_mocked(
            interface_port=3,
            tag_value=83,
            switch_id="00:00:00:00:00:00:00:03",
            is_valid=True,
        )

        switch_a = Switch("00:00:00:00:00:00:00:01")
        switch_b = Switch("00:00:00:00:00:00:00:02")
        switch_c = Switch("00:00:00:00:00:00:00:03")

        attributes = {
            "controller": get_controller_mock(),
            "name": "custom_name",
            "uni_a": uni_a,
            "uni_z": uni_z,
            "active": True,
            "enabled": True,
            "failover_path": [
                get_link_mocked(
                    switch_a=switch_a,
                    switch_b=switch_b,
                    endpoint_a_port=9,
                    endpoint_b_port=10,
                    metadata={"s_vlan": 5},
                ),
                get_link_mocked(
                    switch_a=switch_b,
                    switch_b=switch_c,
                    endpoint_a_port=11,
                    endpoint_b_port=12,
                    metadata={"s_vlan": 6},
                ),
            ],
        }

        evc = EVC(**attributes)
        evc.remove_failover_flows(exclude_uni_switches=False, sync=True)

        assert send_flow_mods_mocked.call_count == 3
        flows = [
            {"cookie": evc.get_cookie(),
             "cookie_mask": int(0xffffffffffffffff)}
        ]
        send_flow_mods_mocked.assert_any_call(switch_a.id, flows, 'delete',
                                              force=True)
        send_flow_mods_mocked.assert_any_call(switch_b.id, flows, 'delete',
                                              force=True)
        send_flow_mods_mocked.assert_any_call(switch_c.id, flows, 'delete',
                                              force=True)
        assert mock_upsert.call_count == 1

    @staticmethod
    def create_evc_intra_switch():
        """Create intra-switch EVC."""
        switch = Mock(spec=Switch)
        switch.dpid = 2
        switch.id = switch.dpid
        interface_a = Interface("eth0", 1, switch)
        interface_z = Interface("eth1", 3, switch)
        uni_a = get_uni_mocked(
            tag_value=82,
            is_valid=True,
        )
        uni_z = get_uni_mocked(
            tag_value=84,
            is_valid=True,
        )
        uni_a.interface = interface_a
        uni_z.interface = interface_z
        attributes = {
            "table_group": {"epl": 0, "evpl": 0},
            "controller": get_controller_mock(),
            "name": "custom_name",
            "id": "1",
            "uni_a": uni_a,
            "uni_z": uni_z,
            "enabled": True,
        }
        return EVC(**attributes)

    # pylint: disable=too-many-branches
    @pytest.mark.parametrize(
        "uni_a,uni_z",
        [
            (100, 50),
            (100, "4096/4096"),
            (100, 0),
            (100, None),
            ("4096/4096", 50),
            ("4096/4096", "4096/4096"),
            ("4096/4096", 0),
            ("4096/4096", None),
            (0, 50),
            (0, "4096/4096"),
            (0, 0),
            (0, None),
            (None, 50),
            (None, "4096/4096"),
            (None, 0),
            (None, None),
        ]
    )
    @patch("napps.kytos.mef_eline.models.evc.EVC._send_flow_mods")
    def test_deploy_direct_uni_flows(self, send_flow_mods_mock, uni_a, uni_z):
        """Test _install_direct_uni_flows"""
        evc = TestEVC.create_evc_intra_switch()
        expected_dpid = evc.uni_a.interface.switch.id

        expected_flows = [
            {
                "match": {"in_port": 1},
                "cookie": evc.get_cookie(),
                "owner": "mef_eline",
                "table_id": 0,
                "table_group": "epl",
                "actions": [
                    {"action_type": "output", "port": 3},
                ],
                "priority": EPL_SB_PRIORITY
            },
            {
                "match": {"in_port": 3},
                "cookie": evc.get_cookie(),
                "owner": "mef_eline",
                "table_id": 0,
                "table_group": "epl",
                "actions": [
                    {"action_type": "output", "port": 1},
                ],
                "priority": EPL_SB_PRIORITY
            }
        ]
        evc.uni_a = get_uni_mocked(tag_value=uni_a, is_valid=True)
        evc.uni_a.interface.port_number = 1
        evc.uni_z = get_uni_mocked(tag_value=uni_z, is_valid=True)
        evc.uni_z.interface.port_number = 3
        expected_dpid = evc.uni_a.interface.switch.id
        evc._install_direct_uni_flows()
        if uni_a is not None:
            expected_flows[0]["match"]["dl_vlan"] = uni_a
            expected_flows[0]["table_group"] = "evpl"
        if uni_z is not None:
            expected_flows[1]["match"]["dl_vlan"] = uni_z
            expected_flows[1]["table_group"] = "evpl"
        expected_flows[0]["priority"] = EVC.get_priority(uni_a)
        expected_flows[1]["priority"] = EVC.get_priority(uni_z)
        if uni_z not in evc.special_cases:
            expected_flows[0]["actions"].insert(
                0, {"action_type": "set_vlan", "vlan_id": uni_z}
            )
        if uni_a not in evc.special_cases:
            expected_flows[1]["actions"].insert(
                    0, {"action_type": "set_vlan",
                        "vlan_id": uni_a}
                )
            if not uni_z:
                expected_flows[1]["actions"].insert(
                    0, {"action_type": "push_vlan",
                        "tag_type": "c"}
                )
            if uni_z == 0:
                new_action = {"action_type": "pop_vlan"}
                expected_flows[0]["actions"].insert(0, new_action)
        elif uni_a == "4096/4096":
            if uni_z == 0:
                new_action = {"action_type": "pop_vlan"}
                expected_flows[0]["actions"].insert(0, new_action)
        elif uni_a == 0:
            if uni_z not in evc.special_cases:
                expected_flows[0]["actions"].insert(
                    0, {"action_type": "push_vlan",
                        "tag_type": "c"}
                )
            if uni_z:
                new_action = {"action_type": "pop_vlan"}
                expected_flows[1]["actions"].insert(0, new_action)
        elif uni_a is None:
            if uni_z not in evc.special_cases:
                expected_flows[0]["actions"].insert(
                    0, {"action_type": "push_vlan",
                        "tag_type": "c"}
                )
        send_flow_mods_mock.assert_called_with(
            expected_dpid, expected_flows
        )

    def test_is_affected_by_link(self):
        """Test is_affected_by_link method"""
        self.evc_deploy.current_path = Path(['a', 'b', 'c'])
        assert self.evc_deploy.is_affected_by_link('b') is True

    def test_is_backup_path_affected_by_link(self):
        """Test is_backup_path_affected_by_link method"""
        self.evc_deploy.backup_path = Path(['a', 'b', 'c'])
        assert self.evc_deploy.is_backup_path_affected_by_link('d') is False

    def test_is_primary_path_affected_by_link(self):
        """Test is_primary_path_affected_by_link method"""
        self.evc_deploy.primary_path = Path(['a', 'b', 'c'])
        assert self.evc_deploy.is_primary_path_affected_by_link('c') is True

    def test_is_using_primary_path(self):
        """Test is_using_primary_path method"""
        self.evc_deploy.primary_path = Path(['a', 'b', 'c'])
        self.evc_deploy.current_path = Path(['e', 'f', 'g'])
        assert self.evc_deploy.is_using_primary_path() is False

    def test_is_using_backup_path(self):
        """Test is_using_backup_path method"""
        self.evc_deploy.backup_path = Path(['a', 'b', 'c'])
        self.evc_deploy.current_path = Path(['e', 'f', 'g'])
        assert self.evc_deploy.is_using_backup_path() is False

    @patch('napps.kytos.mef_eline.models.path.Path.status')
    def test_is_using_dynamic_path(self, mock_status):
        """Test is_using_dynamic_path method"""
        mock_status.return_value = False
        self.evc_deploy.backup_path = Path([])
        self.evc_deploy.primary_path = Path([])
        assert self.evc_deploy.is_using_dynamic_path() is False

    def test_get_path_status(self):
        """Test get_path_status method"""
        path = Path([])
        assert self.evc_deploy.get_path_status(path) == EntityStatus.DISABLED
        path = Path([
            get_link_mocked(status=EntityStatus.UP),
            get_link_mocked(status=EntityStatus.DOWN)
        ])
        assert self.evc_deploy.get_path_status(path) == EntityStatus.DOWN
        path = Path([
            get_link_mocked(status=EntityStatus.UP),
            get_link_mocked(status=EntityStatus.UP)
        ])
        assert self.evc_deploy.get_path_status(path) == EntityStatus.UP

    @patch("napps.kytos.mef_eline.models.evc.EVC._prepare_uni_flows")
    def test_get_failover_flows(self, prepare_uni_flows_mock):
        """Test get_failover_flows method."""
        evc = self.create_evc_inter_switch()
        evc.failover_path = Path([])
        assert len(evc.get_failover_flows()) == 0

        path = MagicMock()
        evc.failover_path = path
        evc.get_failover_flows()
        prepare_uni_flows_mock.assert_called_with(path, skip_out=True)

    @patch("napps.kytos.mef_eline.models.evc.log")
    @patch("napps.kytos.mef_eline.models.evc.EVC._send_flow_mods")
    @patch("napps.kytos.mef_eline.models.path.Path.make_vlans_available")
    def test_remove_path_flows(self, *args):
        """Test remove path flows."""
        (
            make_vlans_available_mock,
            send_flow_mods_mock,
            log_mock,
        ) = args

        evc = self.create_evc_inter_switch()

        evc.remove_path_flows()
        make_vlans_available_mock.assert_not_called()

        expected_flows_1 = [
            {
                'cookie': 12249790986447749121,
                'cookie_mask': 18446744073709551615,
                'match': {'in_port': 9, 'dl_vlan':  5}
            },
        ]
        expected_flows_2 = [
            {
                'cookie': 12249790986447749121,
                'cookie_mask': 18446744073709551615,
                'match': {'in_port': 10, 'dl_vlan': 5}
            },
            {
                'cookie': 12249790986447749121,
                'cookie_mask': 18446744073709551615,
                'match': {'in_port': 11, 'dl_vlan': 6}
            },
        ]
        expected_flows_3 = [
            {
                'cookie': 12249790986447749121,
                'cookie_mask': 18446744073709551615,
                'match': {'in_port': 12, 'dl_vlan': 6}
            },
        ]

        evc.remove_path_flows(evc.primary_links)
        send_flow_mods_mock.assert_has_calls([
            call(1, expected_flows_1, 'delete', force=True),
            call(2, expected_flows_2, 'delete', force=True),
            call(3, expected_flows_3, 'delete', force=True),
        ], any_order=True)

        send_flow_mods_mock.side_effect = FlowModException("err")
        evc.remove_path_flows(evc.primary_links)
        log_mock.error.assert_called()

    @patch("requests.put")
    def test_run_bulk_sdntraces(self, put_mock):
        """Test run_bulk_sdntraces method for bulk request."""
        evc = self.create_evc_inter_switch()
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"result": "ok"}
        put_mock.return_value = response

        expected_endpoint = f"{SDN_TRACE_CP_URL}/traces"
        expected_payload = [
                            {
                                'trace': {
                                    'switch': {'dpid': 1, 'in_port': 2},
                                    'eth': {'dl_type': 0x8100, 'dl_vlan': 82}
                                }
                            }
                        ]
        result = EVCDeploy.run_bulk_sdntraces([evc.uni_a])
        put_mock.assert_called_with(
                                    expected_endpoint,
                                    json=expected_payload,
                                    timeout=30
                                )
        assert result['result'] == "ok"

        response.status_code = 400
        result = EVCDeploy.run_bulk_sdntraces([evc.uni_a])
        assert result == {"result": []}

    @patch("requests.put")
    def test_run_bulk_sdntraces_special_vlan(self, put_mock):
        """Test run_bulk_sdntraces method for bulk request."""
        evc = self.create_evc_inter_switch()
        response = MagicMock()
        response.status_code = 200
        put_mock.return_value = response

        expected_endpoint = f"{SDN_TRACE_CP_URL}/traces"
        expected_payload = [
                            {
                                'trace': {
                                    'switch': {'dpid': 1, 'in_port': 2}
                                }
                            }
                        ]

        evc.uni_a.user_tag.value = 'untagged'
        EVCDeploy.run_bulk_sdntraces([evc.uni_a])
        put_mock.assert_called_with(
                                    expected_endpoint,
                                    json=expected_payload,
                                    timeout=30
                                )
        args = put_mock.call_args[1]['json'][0]
        assert 'eth' not in args

        evc.uni_a.user_tag.value = 0
        EVCDeploy.run_bulk_sdntraces([evc.uni_a])
        put_mock.assert_called_with(
                                    expected_endpoint,
                                    json=expected_payload,
                                    timeout=30
                                )
        args = put_mock.call_args[1]['json'][0]['trace']
        assert 'eth' not in args

        evc.uni_a.user_tag.value = '5/2'
        EVCDeploy.run_bulk_sdntraces([evc.uni_a])
        put_mock.assert_called_with(
                                    expected_endpoint,
                                    json=expected_payload,
                                    timeout=30
                                )
        args = put_mock.call_args[1]['json'][0]['trace']
        assert 'eth' not in args

        expected_payload[0]['trace']['eth'] = {'dl_type': 0x8100, 'dl_vlan': 1}
        evc.uni_a.user_tag.value = 'any'
        EVCDeploy.run_bulk_sdntraces([evc.uni_a])
        put_mock.assert_called_with(
                                    expected_endpoint,
                                    json=expected_payload,
                                    timeout=30
                                )
        args = put_mock.call_args[1]['json'][0]['trace']
        assert args['eth'] == {'dl_type': 33024, 'dl_vlan': 1}

        evc.uni_a.user_tag.value = '4096/4096'
        EVCDeploy.run_bulk_sdntraces([evc.uni_a])
        put_mock.assert_called_with(
                                    expected_endpoint,
                                    json=expected_payload,
                                    timeout=30
                                )
        args = put_mock.call_args[1]['json'][0]['trace']
        assert args['eth'] == {'dl_type': 33024, 'dl_vlan': 1}

        expected_payload[0]['trace']['eth'] = {
            'dl_type': 0x8100,
            'dl_vlan': 10
            }
        evc.uni_a.user_tag.value = '10/10'
        EVCDeploy.run_bulk_sdntraces([evc.uni_a])
        put_mock.assert_called_with(
                                    expected_endpoint,
                                    json=expected_payload,
                                    timeout=30
                                )
        args = put_mock.call_args[1]['json'][0]['trace']
        assert args['eth'] == {'dl_type': 33024, 'dl_vlan': 10}

        expected_payload[0]['trace']['eth'] = {
            'dl_type': 0x8100,
            'dl_vlan': 1
            }
        evc.uni_a.user_tag.value = '5/3'
        EVCDeploy.run_bulk_sdntraces([evc.uni_a])
        put_mock.assert_called_with(
                                    expected_endpoint,
                                    json=expected_payload,
                                    timeout=30
                                )
        args = put_mock.call_args[1]['json'][0]['trace']
        assert args['eth'] == {'dl_type': 33024, 'dl_vlan': 1}

        expected_payload[0]['trace']['eth'] = {
            'dl_type': 0x8100,
            'dl_vlan': 10
            }
        evc.uni_a.user_tag.value = 10
        EVCDeploy.run_bulk_sdntraces([evc.uni_a])
        put_mock.assert_called_with(
                                    expected_endpoint,
                                    json=expected_payload,
                                    timeout=30
                                )

    @patch("napps.kytos.mef_eline.models.evc.log")
    @patch("napps.kytos.mef_eline.models.evc.EVCDeploy.run_bulk_sdntraces")
    def test_check_list_traces(self, run_bulk_sdntraces_mock, _):
        """Test check_list_traces method."""
        evc = self.create_evc_inter_switch()

        for link in evc.primary_links:
            link.metadata['s_vlan'] = MagicMock(value=link.metadata['s_vlan'])
        evc.current_path = evc.primary_links

        trace_a = [
            {
                "dpid": 1,
                "port": 2,
                "time": "t1",
                "type": "starting",
                "vlan": 82
            },
            {
                "dpid": 2,
                "port": 10,
                "time": "t2",
                "type": "intermediary",
                "vlan": 5
            },
            {"dpid": 3, "port": 12, "time": "t3", "type": "last", "vlan": 6},
        ]
        trace_z = [
            {
                "dpid": 3,
                "port": 3,
                "time": "t1",
                "type": "starting",
                "vlan": 83
            },
            {
                "dpid": 2,
                "port": 11,
                "time": "t2",
                "type": "intermediary",
                "vlan": 6
            },
            {"dpid": 1, "port": 9, "time": "t3", "type": "last", "vlan": 5},
        ]

        run_bulk_sdntraces_mock.return_value = {
                                                "result": [trace_a, trace_z]
                                            }
        result = EVCDeploy.check_list_traces([evc])
        assert result[evc.id] is True

        # case2: fail incomplete trace from uni_a
        run_bulk_sdntraces_mock.return_value = {
                                                "result": [
                                                            trace_a[:2],
                                                            trace_z
                                                        ]
        }
        result = EVCDeploy.check_list_traces([evc])
        assert result[evc.id] is False

        # case3: fail incomplete trace from uni_z
        run_bulk_sdntraces_mock.return_value = {
                                                "result": [
                                                            trace_a,
                                                            trace_z[:2]
                                                        ]
        }
        result = EVCDeploy.check_list_traces([evc])
        assert result[evc.id] is False

        # case4: fail wrong vlan id in trace from uni_a
        trace_a[1]["vlan"] = 5
        trace_z[1]["vlan"] = 99
        run_bulk_sdntraces_mock.return_value = {
                                                "result": [trace_a, trace_z]
        }
        result = EVCDeploy.check_list_traces([evc])
        assert result[evc.id] is False

        # case5: fail wrong vlan id in trace from uni_z
        trace_a[1]["vlan"] = 99
        run_bulk_sdntraces_mock.return_value = {
                                                "result": [trace_a, trace_z]
        }
        result = EVCDeploy.check_list_traces([evc])
        assert result[evc.id] is False

        # case6: success when no output in traces
        trace_a[1]["vlan"] = 5
        trace_z[1]["vlan"] = 6
        result = EVCDeploy.check_list_traces([evc])
        assert result[evc.id] is True

        # case7: fail when output is None in trace_a or trace_b
        trace_a[-1]["out"] = None
        result = EVCDeploy.check_list_traces([evc])
        assert result[evc.id] is False
        trace_a[-1].pop("out", None)
        trace_z[-1]["out"] = None
        result = EVCDeploy.check_list_traces([evc])
        assert result[evc.id] is False

        # case8: success when the output is correct on both uni
        trace_a[-1]["out"] = {"port": 3, "vlan": 83}
        trace_z[-1]["out"] = {"port": 2, "vlan": 82}
        result = EVCDeploy.check_list_traces([evc])
        assert result[evc.id] is True

        # case9: fail if any output is incorrect
        trace_a[-1]["out"] = {"port": 3, "vlan": 99}
        trace_z[-1]["out"] = {"port": 2, "vlan": 82}
        result = EVCDeploy.check_list_traces([evc])
        assert result[evc.id] is False
        trace_a[-1]["out"] = {"port": 3, "vlan": 83}
        trace_z[-1]["out"] = {"port": 2, "vlan": 99}
        result = EVCDeploy.check_list_traces([evc])
        assert result[evc.id] is False

    @patch("napps.kytos.mef_eline.models.evc.log")
    @patch("napps.kytos.mef_eline.models.evc.EVCDeploy.run_bulk_sdntraces")
    def test_check_list_traces_any_cases(self, run_bulk_sdntraces_mock, _):
        """Test check_list_traces method."""
        evc = self.create_evc_inter_switch("any", "any")

        for link in evc.primary_links:
            link.metadata['s_vlan'] = MagicMock(value=link.metadata['s_vlan'])
        evc.current_path = evc.primary_links

        trace_a = [
            {
                "dpid": 1,
                "port": 2,
                "time": "t1",
                "type": "starting",
                "vlan": 1
            },
            {
                "dpid": 2,
                "port": 10,
                "time": "t2",
                "type": "intermediary",
                "vlan": 5
            },
            {
                "dpid": 3,
                "port": 12,
                'out': {'port': 3, 'vlan': 1},
                "time": "t3",
                "type": "last",
                "vlan": 6
            },
        ]
        trace_z = [
            {
                "dpid": 3,
                "port": 3,
                "time": "t1",
                "type": "starting",
                "vlan": 1
            },
            {
                "dpid": 2,
                "port": 11,
                "time": "t2",
                "type": "intermediary",
                "vlan": 6
            },
            {
                "dpid": 1,
                "port": 9,
                'out': {'port': 2, 'vlan': 1},
                "time": "t3",
                "type": "last",
                "vlan": 5
            },
        ]

        run_bulk_sdntraces_mock.return_value = {
                                                "result": [trace_a, trace_z]
                                            }
        result = EVCDeploy.check_list_traces([evc])
        assert result[evc.id] is True

    @patch("napps.kytos.mef_eline.models.evc.log")
    @patch("napps.kytos.mef_eline.models.evc.EVCDeploy.run_bulk_sdntraces")
    def test_check_list_traces_untagged_cases(self, bulk_sdntraces_mock, _):
        """Test check_list_traces method."""
        evc = self.create_evc_inter_switch("untagged", "untagged")

        for link in evc.primary_links:
            link.metadata['s_vlan'] = MagicMock(value=link.metadata['s_vlan'])
        evc.current_path = evc.primary_links

        trace_a = [
            {
                "dpid": 1,
                "port": 2,
                "time": "t1",
                "type": "starting",
                "vlan": 0
            },
            {
                "dpid": 2,
                "port": 10,
                "time": "t2",
                "type": "intermediary",
                "vlan": 5
            },
            {
                "dpid": 3,
                "port": 12,
                'out': {'port': 3},
                "time": "t3", "type":
                "last",
                "vlan": 6
                },
        ]
        trace_z = [
            {
                "dpid": 3,
                "port": 3,
                "time": "t1",
                "type": "starting",
                "vlan": 0
            },
            {
                "dpid": 2,
                "port": 11,
                "time": "t2",
                "type": "intermediary",
                "vlan": 6
            },
            {
                "dpid": 1,
                "port": 9,
                'out': {'port': 2},
                "time": "t3",
                "type": "last",
                "vlan": 5
            },
        ]

        bulk_sdntraces_mock.return_value = {
                                                "result": [trace_a, trace_z]
                                            }
        result = EVCDeploy.check_list_traces([evc])
        assert result[evc.id] is True

    @patch("napps.kytos.mef_eline.models.evc.log")
    @patch("napps.kytos.mef_eline.models.evc.EVCDeploy.run_bulk_sdntraces")
    def test_check_list_traces_invalid_types(self, run_bulk_sdntraces_mock, _):
        """Test check_list_traces method for invalid traces by trace type."""
        evc = self.create_evc_inter_switch()

        for link in evc.primary_links:
            link.metadata['s_vlan'] = MagicMock(value=link.metadata['s_vlan'])
        evc.current_path = evc.primary_links

        trace_a = [
            {
                "dpid": 1,
                "port": 2,
                "time": "t1",
                "type": "starting",
                "vlan": 82
            },
            {
                "dpid": 2,
                "port": 10,
                "time": "t2",
                "type": "intermediary",
                "vlan": 5
            },
            {"dpid": 3, "port": 12, "time": "t3", "type": "last", "vlan": 6},
        ]
        trace_z = [
            {
                "dpid": 3,
                "port": 3,
                "time": "t1",
                "type": "starting",
                "vlan": 83
            },
            {
                "dpid": 2,
                "port": 11,
                "time": "t2",
                "type": "intermediary",
                "vlan": 6
            },
            {
                "dpid": 1,
                "port": 9,
                "time": "t3",
                "type": "last",
                "vlan": 5
            },
        ]

        run_bulk_sdntraces_mock.return_value = {
                                                "result": [trace_a, trace_z]
                                            }
        result = EVCDeploy.check_list_traces([evc])

        assert result[evc.id] is True

        trace_z = [
            {
                "dpid": 3,
                "port": 3,
                "time": "t1",
                "type": "starting",
                "vlan": 83
            },
            {
                "dpid": 2,
                "port": 11,
                "time": "t2",
                "type": "loop",
                "vlan": 6
            },
        ]

        run_bulk_sdntraces_mock.return_value = {
                                                "result": [trace_a, trace_z]
                                            }
        result = EVCDeploy.check_list_traces([evc])
        # type loop
        assert result[evc.id] is False

    @patch(
        "napps.kytos.mef_eline.models.path.DynamicPathManager"
        ".get_disjoint_paths"
    )
    def test_get_failover_path_vandidates(self, get_disjoint_paths_mock):
        """Test get_failover_path_candidates method"""
        self.evc_deploy.get_failover_path_candidates()
        get_disjoint_paths_mock.assert_called_once()

    def test_is_failover_path_affected_by_link(self):
        """Test is_failover_path_affected_by_link method"""
        link1 = get_link_mocked(endpoint_a_port=1, endpoint_b_port=2)
        link2 = get_link_mocked(endpoint_a_port=3, endpoint_b_port=4)
        link3 = get_link_mocked(endpoint_a_port=5, endpoint_b_port=6)
        self.evc_deploy.failover_path = Path([link1, link2])
        assert self.evc_deploy.is_failover_path_affected_by_link(link1) is True
        assert self.evc_deploy.is_failover_path_affected_by_link(link3) \
               is False

    def test_is_eligible_for_failover_path(self):
        """Test is_eligible_for_failover_path method"""
        assert self.evc_deploy.is_eligible_for_failover_path() is False
        self.evc_deploy.dynamic_backup_path = True
        self.evc_deploy.primary_path = Path([])
        self.evc_deploy.backup_path = Path([])
        assert self.evc_deploy.is_eligible_for_failover_path() is True

    def test_get_value_from_uni_tag(self):
        """Test _get_value_from_uni_tag"""
        uni = get_uni_mocked(tag_value=None)
        value = EVC._get_value_from_uni_tag(uni)
        assert value is None

        uni = get_uni_mocked(tag_value="any")
        value = EVC._get_value_from_uni_tag(uni)
        assert value == "4096/4096"

        uni = get_uni_mocked(tag_value="untagged")
        value = EVC._get_value_from_uni_tag(uni)
        assert value == 0

        uni = get_uni_mocked(tag_value=100)
        value = EVC._get_value_from_uni_tag(uni)
        assert value == 100

    def test_get_priority(self):
        """Test get_priority_from_vlan"""
        evpl_value = EVC.get_priority(100)
        assert evpl_value == EVPL_SB_PRIORITY

        untagged_value = EVC.get_priority(0)
        assert untagged_value == UNTAGGED_SB_PRIORITY

        any_value = EVC.get_priority("4096/4096")
        assert any_value == ANY_SB_PRIORITY

        epl_value = EVC.get_priority(None)
        assert epl_value == EPL_SB_PRIORITY

    def test_set_flow_table_group_id(self):
        """Test set_flow_table_group_id"""
        self.evc_deploy.table_group = {"epl": 3, "evpl": 4}
        flow_mod = {}
        self.evc_deploy.set_flow_table_group_id(flow_mod, 100)
        assert flow_mod["table_group"] == "evpl"
        assert flow_mod["table_id"] == 4
        self.evc_deploy.set_flow_table_group_id(flow_mod, None)
        assert flow_mod["table_group"] == "epl"
        assert flow_mod["table_id"] == 3

    def test_get_endpoint_by_id(self):
        """Test get_endpoint_by_id"""
        link = MagicMock()
        link.endpoint_a.switch.id = "01"
        link.endpoint_b.switch.id = "02"
        result = self.evc_deploy.get_endpoint_by_id(link, "01", operator.eq)
        assert result == link.endpoint_a
        result = self.evc_deploy.get_endpoint_by_id(link, "01", operator.ne)
        assert result == link.endpoint_b
