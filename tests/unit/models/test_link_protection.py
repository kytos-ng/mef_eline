# pylint: disable=too-many-lines
"""Module to test the LinkProtection class."""
import sys
from unittest.mock import MagicMock, patch

from kytos.core.common import EntityStatus
from kytos.lib.helpers import get_controller_mock
from napps.kytos.mef_eline.models import EVC, Path  # NOQA pycodestyle
from napps.kytos.mef_eline.tests.helpers import (
    get_link_mocked,
    get_uni_mocked,
    get_mocked_requests,
    id_to_interface_mock
)  # NOQA pycodestyle


sys.path.insert(0, "/var/lib/kytos/napps/..")


DEPLOY_TO_PRIMARY_PATH = (
    "napps.kytos.mef_eline.models.evc.LinkProtection.deploy_to_primary_path"
)
DEPLOY_TO_BACKUP_PATH = (
    "napps.kytos.mef_eline.models.evc.LinkProtection.deploy_to_backup_path"
)
GET_BEST_PATH = (
    "napps.kytos.mef_eline.models.path.DynamicPathManager.get_best_path"
)


class TestLinkProtection():  # pylint: disable=too-many-public-methods
    """Tests to validate LinkProtection class."""

    def setup_method(self):
        """Set up method"""
        primary_path = [
            get_link_mocked(
                endpoint_a_port=9,
                endpoint_b_port=10,
                metadata={"s_vlan": 5},
                status=EntityStatus.UP,
            ),
            get_link_mocked(
                endpoint_a_port=11,
                endpoint_b_port=12,
                metadata={"s_vlan": 6},
                status=EntityStatus.DOWN,
            ),
        ]
        backup_path = [
            get_link_mocked(
                endpoint_a_port=13,
                endpoint_b_port=14,
                metadata={"s_vlan": 5},
                status=EntityStatus.DOWN,
            ),
            get_link_mocked(
                endpoint_a_port=11,
                endpoint_b_port=12,
                metadata={"s_vlan": 6},
                status=EntityStatus.DOWN,
            ),
        ]
        attributes = {
            "controller": get_controller_mock(),
            "name": "circuit_1",
            "uni_a": get_uni_mocked(is_valid=True),
            "uni_z": get_uni_mocked(is_valid=True),
            "primary_path": primary_path,
            "backup_path": backup_path,
            "enabled": True,
            "dynamic_backup_path": True,
        }
        self.evc = EVC(**attributes)

    async def test_is_using_backup_path(self):
        """Test test is using backup path."""

        attributes = {
            "controller": get_controller_mock(),
            "name": "circuit_1",
            "uni_a": get_uni_mocked(is_valid=True),
            "uni_z": get_uni_mocked(is_valid=True),
            "backup_path": [
                get_link_mocked(
                    endpoint_a_port=10,
                    endpoint_b_port=9,
                    metadata={"s_vlan": 5},
                ),
                get_link_mocked(
                    endpoint_a_port=12,
                    endpoint_b_port=11,
                    metadata={"s_vlan": 6},
                ),
            ],
        }

        evc = EVC(**attributes)
        assert evc.is_using_backup_path() is False
        evc.current_path = evc.backup_path
        assert evc.is_using_backup_path()

    async def test_is_using_primary_path(self):
        """Test test is using primary path."""
        primary_path = [
            get_link_mocked(
                endpoint_a_port=10, endpoint_b_port=9, metadata={"s_vlan": 5}
            ),
            get_link_mocked(
                endpoint_a_port=12, endpoint_b_port=11, metadata={"s_vlan": 6}
            ),
        ]

        attributes = {
            "controller": get_controller_mock(),
            "name": "circuit_2",
            "uni_a": get_uni_mocked(is_valid=True),
            "uni_z": get_uni_mocked(is_valid=True),
            "primary_path": primary_path,
        }
        evc = EVC(**attributes)
        assert evc.is_using_primary_path() is False
        evc.current_path = evc.primary_path
        assert evc.is_using_primary_path()

    @patch("napps.kytos.mef_eline.models.evc.log")
    async def test_deploy_to_case_1(self, log_mocked):
        """Test if the path is equal to current_path."""
        primary_path = [
            get_link_mocked(
                endpoint_a_port=10, endpoint_b_port=9, metadata={"s_vlan": 5}
            ),
            get_link_mocked(
                endpoint_a_port=12, endpoint_b_port=11, metadata={"s_vlan": 6}
            ),
        ]
        attributes = {
            "controller": get_controller_mock(),
            "name": "circuit_3",
            "uni_a": get_uni_mocked(is_valid=True),
            "uni_z": get_uni_mocked(is_valid=True),
            "primary_path": primary_path,
        }
        evc = EVC(**attributes)
        evc.current_path = evc.primary_path

        expected_deployed = evc.deploy_to("primary_path", evc.primary_path)
        expected_msg = "primary_path is equal to current_path."
        log_mocked.debug.assert_called_with(expected_msg)
        assert expected_deployed

    # pylint: disable=too-many-arguments
    @patch("requests.post")
    @patch("napps.kytos.mef_eline.controllers.ELineController.upsert_evc")
    @patch("napps.kytos.mef_eline.models.evc.EVCDeploy.deploy")
    @patch("napps.kytos.mef_eline.models.evc.EVC._install_nni_flows")
    @patch("napps.kytos.mef_eline.models.evc.EVC._install_uni_flows")
    @patch("napps.kytos.mef_eline.models.path.Path.status", EntityStatus.UP)
    async def test_deploy_to_case_2(
        self,
        install_uni_flows_mocked,
        install_nni_flows_mocked,
        deploy_mocked,
        _,
        requests_mock,
    ):
        """Test deploy with all links up."""
        deploy_mocked.return_value = True
        response = MagicMock()
        response.status_code = 201
        requests_mock.return_value = response

        primary_path = [
            get_link_mocked(status=EntityStatus.UP),
            get_link_mocked(status=EntityStatus.UP),
        ]
        attributes = {
            "controller": get_controller_mock(),
            "name": "circuit_4",
            "uni_a": get_uni_mocked(is_valid=True),
            "uni_z": get_uni_mocked(is_valid=True),
            "primary_path": primary_path,
            "enabled": True,
        }
        evc = EVC(**attributes)

        deployed = evc.deploy_to("primary_path", evc.primary_path)
        install_uni_flows_mocked.assert_called_with(evc.primary_path)
        install_nni_flows_mocked.assert_called_with(evc.primary_path)
        assert deployed

    @patch("requests.get", side_effect=get_mocked_requests)
    async def test_deploy_to_case_3(self, requests_mocked):
        # pylint: disable=unused-argument
        """Test deploy with one link down."""
        link1 = get_link_mocked()
        link2 = get_link_mocked()
        link1.id = "abc"
        link2.id = "def"
        primary_path = [link1, link2]
        attributes = {
            "controller": get_controller_mock(),
            "name": "circuit_5",
            "uni_a": get_uni_mocked(is_valid=True),
            "uni_z": get_uni_mocked(is_valid=True),
            "primary_path": primary_path,
            "enabled": True,
        }
        evc = EVC(**attributes)

        deployed = evc.deploy_to("primary_path", evc.primary_path)
        assert deployed is False

    @patch("napps.kytos.mef_eline.models.evc.log")
    @patch("napps.kytos.mef_eline.models.evc.EVCDeploy._send_flow_mods")
    @patch(DEPLOY_TO_BACKUP_PATH)
    @patch("napps.kytos.mef_eline.models.evc.EVCDeploy.deploy")
    @patch("napps.kytos.mef_eline.models.path.Path.status")
    async def test_handle_link_down_case_1(
        self,
        path_status_mocked,
        deploy_mocked,
        deploy_to_mocked,
        _send_flow_mods_mocked,
        log_mocked,
    ):
        """Test if deploy_to backup path is called."""
        deploy_mocked.return_value = True
        path_status_mocked.side_effect = [EntityStatus.DOWN, EntityStatus.UP]

        self.evc.current_path = self.evc.primary_path
        self.evc.activate()
        deploy_to_mocked.reset_mock()
        current_handle_link_down = self.evc.handle_link_down()
        assert deploy_mocked.call_count == 0
        deploy_to_mocked.assert_called_once()

        assert current_handle_link_down
        msg = f"{self.evc} deployed after link down."
        log_mocked.debug.assert_called_once_with(msg)

    @patch("napps.kytos.mef_eline.models.evc.log")
    @patch("napps.kytos.mef_eline.models.evc.EVCDeploy.deploy")
    @patch(DEPLOY_TO_PRIMARY_PATH)
    @patch("napps.kytos.mef_eline.models.path.Path.status")
    async def test_handle_link_down_case_2(
        self, path_status_mocked, deploy_to_mocked, deploy_mocked, log_mocked
    ):
        """Test if deploy_to backup path is called."""
        deploy_mocked.return_value = True
        deploy_to_mocked.return_value = True
        path_status_mocked.side_effect = [EntityStatus.UP, EntityStatus.DOWN]
        primary_path = [
            get_link_mocked(
                endpoint_a_port=7,
                endpoint_b_port=8,
                metadata={"s_vlan": 5},
                status=EntityStatus.UP,
            ),
            get_link_mocked(
                endpoint_a_port=11,
                endpoint_b_port=12,
                metadata={"s_vlan": 6},
                status=EntityStatus.UP,
            ),
        ]
        backup_path = [
            get_link_mocked(
                endpoint_a_port=7,
                endpoint_b_port=10,
                metadata={"s_vlan": 5},
                status=EntityStatus.DOWN,
            ),
            get_link_mocked(
                endpoint_a_port=15,
                endpoint_b_port=12,
                metadata={"s_vlan": 6},
                status=EntityStatus.UP,
            ),
        ]
        attributes = {
            "controller": get_controller_mock(),
            "name": "circuit_13",
            "uni_a": get_uni_mocked(is_valid=True),
            "uni_z": get_uni_mocked(is_valid=True),
            "primary_path": primary_path,
            "backup_path": backup_path,
            "enabled": True,
        }

        evc = EVC(**attributes)
        evc.current_path = evc.backup_path
        deploy_to_mocked.reset_mock()
        current_handle_link_down = evc.handle_link_down()
        assert deploy_mocked.call_count == 0
        deploy_to_mocked.assert_called_once()
        assert current_handle_link_down
        msg = f"{evc} deployed after link down."
        log_mocked.debug.assert_called_once_with(msg)

    @patch("napps.kytos.mef_eline.models.evc.EVCDeploy.remove_current_flows")
    @patch("napps.kytos.mef_eline.controllers.ELineController.upsert_evc")
    @patch("napps.kytos.mef_eline.models.evc.log")
    @patch("napps.kytos.mef_eline.models.evc.EVCDeploy.deploy")
    @patch(DEPLOY_TO_PRIMARY_PATH)
    @patch("napps.kytos.mef_eline.models.path.DynamicPathManager.get_paths")
    @patch("napps.kytos.mef_eline.models.path.Path.status", EntityStatus.DOWN)
    async def test_handle_link_down_case_3(
        self, get_paths_mocked, deploy_to_mocked, deploy_mocked,
        log_mocked, _, mock_remove_current
    ):
        """Test if circuit without dynamic path is return failed."""
        deploy_mocked.return_value = False
        mock_remove_current.return_value = True
        deploy_to_mocked.return_value = False
        primary_path = [
            get_link_mocked(
                endpoint_a_port=9,
                endpoint_b_port=10,
                metadata={"s_vlan": 5},
                status=EntityStatus.DOWN,
            ),
            get_link_mocked(
                endpoint_a_port=11,
                endpoint_b_port=12,
                metadata={"s_vlan": 6},
                status=EntityStatus.UP,
            ),
        ]
        backup_path = [
            get_link_mocked(
                endpoint_a_port=9,
                endpoint_b_port=10,
                metadata={"s_vlan": 5},
                status=EntityStatus.DOWN,
            ),
            get_link_mocked(
                endpoint_a_port=13,
                endpoint_b_port=14,
                metadata={"s_vlan": 6},
                status=EntityStatus.UP,
            ),
        ]
        attributes = {
            "controller": get_controller_mock(),
            "name": "circuit_7",
            "uni_a": get_uni_mocked(is_valid=True),
            "uni_z": get_uni_mocked(is_valid=True),
            "primary_path": primary_path,
            "backup_path": backup_path,
            "enabled": True,
        }

        evc = EVC(**attributes)
        evc.current_path = evc.backup_path
        deploy_to_mocked.reset_mock()
        current_handle_link_down = evc.handle_link_down()

        assert get_paths_mocked.call_count == 0
        assert deploy_mocked.call_count == 0
        assert deploy_to_mocked.call_count == 1

        assert current_handle_link_down is False
        msg = f"Failed to re-deploy {evc} after link down."
        log_mocked.debug.assert_called_once_with(msg)

    @patch("napps.kytos.mef_eline.models.evc.log")
    @patch("napps.kytos.mef_eline.models.evc.EVCDeploy.deploy_to_path")
    @patch("napps.kytos.mef_eline.models.evc.EVCDeploy._send_flow_mods")
    @patch(DEPLOY_TO_PRIMARY_PATH)
    @patch("napps.kytos.mef_eline.models.path.Path.status", EntityStatus.DOWN)
    async def test_handle_link_down_case_4(
        self,
        deploy_to_mocked,
        _send_flow_mods_mocked,
        deploy_mocked,
        log_mocked,
    ):
        """Test if circuit with dynamic path is return success."""
        deploy_mocked.return_value = True
        deploy_to_mocked.return_value = False
        primary_path = [
            get_link_mocked(
                endpoint_a_port=9,
                endpoint_b_port=10,
                metadata={"s_vlan": 5},
                status=EntityStatus.DOWN,
            ),
            get_link_mocked(
                endpoint_a_port=11,
                endpoint_b_port=12,
                metadata={"s_vlan": 6},
                status=EntityStatus.UP,
            ),
        ]
        backup_path = [
            get_link_mocked(
                endpoint_a_port=9,
                endpoint_b_port=10,
                metadata={"s_vlan": 5},
                status=EntityStatus.DOWN,
            ),
            get_link_mocked(
                endpoint_a_port=13,
                endpoint_b_port=14,
                metadata={"s_vlan": 6},
                status=EntityStatus.UP,
            ),
        ]
        attributes = {
            "controller": get_controller_mock(),
            "name": "circuit_8",
            "uni_a": get_uni_mocked(is_valid=True),
            "uni_z": get_uni_mocked(is_valid=True),
            "primary_path": primary_path,
            "backup_path": backup_path,
            "enabled": True,
            "dynamic_backup_path": True,
        }

        evc = EVC(**attributes)
        evc.current_path = evc.backup_path

        deploy_to_mocked.reset_mock()
        current_handle_link_down = evc.handle_link_down()
        assert deploy_to_mocked.call_count == 1

        assert current_handle_link_down
        msg = f"{evc} deployed after link down."
        log_mocked.debug.assert_called_with(msg)

    @patch("napps.kytos.mef_eline.models.evc.EVCDeploy.deploy")
    @patch("napps.kytos.mef_eline.models.evc.LinkProtection.deploy_to")
    async def test_handle_link_up_case_1(
        self,
        deploy_to_mocked,
        deploy_mocked
    ):
        """Test if handle link up do nothing when is using primary path."""
        deploy_mocked.return_value = True
        deploy_to_mocked.return_value = True
        primary_path = [
            get_link_mocked(
                endpoint_a_port=9,
                endpoint_b_port=10,
                metadata={"s_vlan": 5},
                status=EntityStatus.UP,
            ),
            get_link_mocked(
                endpoint_a_port=11,
                endpoint_b_port=12,
                metadata={"s_vlan": 6},
                status=EntityStatus.UP,
            ),
        ]
        backup_path = [
            get_link_mocked(
                endpoint_a_port=9,
                endpoint_b_port=14,
                metadata={"s_vlan": 5},
                status=EntityStatus.UP,
            ),
            get_link_mocked(
                endpoint_a_port=15,
                endpoint_b_port=12,
                metadata={"s_vlan": 6},
                status=EntityStatus.UP,
            ),
        ]
        attributes = {
            "controller": get_controller_mock(),
            "name": "circuit_9",
            "uni_a": get_uni_mocked(is_valid=True),
            "uni_z": get_uni_mocked(is_valid=True),
            "primary_path": primary_path,
            "backup_path": backup_path,
            "enabled": True,
            "dynamic_backup_path": True,
        }

        evc = EVC(**attributes)
        evc.current_path = evc.primary_path
        deploy_to_mocked.reset_mock()
        current_handle_link_up = evc.handle_link_up(backup_path[0])
        assert deploy_mocked.call_count == 0
        assert deploy_to_mocked.call_count == 0
        assert current_handle_link_up

    @patch("napps.kytos.mef_eline.models.evc.EVCDeploy.deploy")
    @patch("napps.kytos.mef_eline.models.evc.EVCDeploy.deploy_to_path")
    @patch("napps.kytos.mef_eline.models.path.Path.status", EntityStatus.UP)
    async def test_handle_link_up_case_2(
        self,
        deploy_to_path_mocked,
        deploy_mocked
    ):
        """Test if it is changing from backup_path to primary_path."""
        deploy_mocked.return_value = True
        deploy_to_path_mocked.return_value = True
        primary_path = [
            get_link_mocked(
                endpoint_a_port=9,
                endpoint_b_port=10,
                metadata={"s_vlan": 5},
                status=EntityStatus.UP,
            ),
            get_link_mocked(
                endpoint_a_port=11,
                endpoint_b_port=12,
                metadata={"s_vlan": 6},
                status=EntityStatus.UP,
            ),
        ]
        backup_path = [
            get_link_mocked(
                endpoint_a_port=9,
                endpoint_b_port=14,
                metadata={"s_vlan": 5},
                status=EntityStatus.UP,
            ),
            get_link_mocked(
                endpoint_a_port=15,
                endpoint_b_port=12,
                metadata={"s_vlan": 6},
                status=EntityStatus.UP,
            ),
        ]
        attributes = {
            "controller": get_controller_mock(),
            "name": "circuit_10",
            "uni_a": get_uni_mocked(is_valid=True),
            "uni_z": get_uni_mocked(is_valid=True),
            "primary_path": primary_path,
            "backup_path": backup_path,
            "enabled": True,
            "dynamic_backup_path": True,
        }

        evc = EVC(**attributes)
        evc.current_path = evc.backup_path
        deploy_to_path_mocked.reset_mock()
        current_handle_link_up = evc.handle_link_up(primary_path[0])
        assert deploy_mocked.call_count == 0
        assert deploy_to_path_mocked.call_count == 1
        deploy_to_path_mocked.assert_called_once_with(evc.primary_path, None)
        assert current_handle_link_up

    @patch("napps.kytos.mef_eline.models.evc.EVCDeploy.deploy")
    @patch("napps.kytos.mef_eline.models.evc.EVCDeploy.deploy_to_path")
    @patch(GET_BEST_PATH)
    @patch("napps.kytos.mef_eline.models.evc.EVC._install_nni_flows")
    @patch("napps.kytos.mef_eline.models.evc.EVC._install_uni_flows")
    @patch("napps.kytos.mef_eline.models.path.Path.status", EntityStatus.UP)
    async def test_handle_link_up_case_3(
        self,
        _install_uni_flows_mocked,
        _install_nni_flows_mocked,
        get_best_path_mocked,
        deploy_to_path_mocked,
        deploy_mocked,
    ):
        """Test if it is deployed after the backup is up."""
        deploy_mocked.return_value = True
        deploy_to_path_mocked.return_value = True
        primary_path = [
            get_link_mocked(
                endpoint_a_port=9,
                endpoint_b_port=10,
                metadata={"s_vlan": 5},
                status=EntityStatus.DOWN,
            ),
            get_link_mocked(
                endpoint_a_port=11,
                endpoint_b_port=12,
                metadata={"s_vlan": 6},
                status=EntityStatus.UP,
            ),
        ]
        backup_path = [
            get_link_mocked(
                endpoint_a_port=9,
                endpoint_b_port=14,
                metadata={"s_vlan": 5},
                status=EntityStatus.DOWN,
            ),
            get_link_mocked(
                endpoint_a_port=15,
                endpoint_b_port=12,
                metadata={"s_vlan": 6},
                status=EntityStatus.UP,
            ),
        ]
        attributes = {
            "controller": get_controller_mock(),
            "name": "circuit_11",
            "uni_a": get_uni_mocked(is_valid=True),
            "uni_z": get_uni_mocked(is_valid=True),
            "primary_path": primary_path,
            "backup_path": backup_path,
            "enabled": True,
            "dynamic_backup_path": True,
        }

        evc = EVC(**attributes)

        evc.current_path = Path([])
        deploy_to_path_mocked.reset_mock()
        current_handle_link_up = evc.handle_link_up(backup_path[0])

        assert get_best_path_mocked.call_count == 0
        assert deploy_mocked.call_count == 0
        assert deploy_to_path_mocked.call_count == 1
        deploy_to_path_mocked.assert_called_once_with(evc.backup_path, None)
        assert current_handle_link_up

    @patch("napps.kytos.mef_eline.models.evc.EVCDeploy.deploy_to_path")
    @patch(GET_BEST_PATH)
    @patch("napps.kytos.mef_eline.models.evc.EVC._install_nni_flows")
    @patch("napps.kytos.mef_eline.models.evc.EVC._install_uni_flows")
    @patch("napps.kytos.mef_eline.models.path.Path.status", EntityStatus.DOWN)
    async def test_handle_link_up_case_4(self, *args):
        """Test if not path is found a dynamic path is used."""
        (
            _install_uni_flows_mocked,
            _install_nni_flows_mocked,
            get_best_path_mocked,
            deploy_to_path_mocked,
        ) = args

        deploy_to_path_mocked.return_value = True

        primary_path = [
            get_link_mocked(
                endpoint_a_port=9,
                endpoint_b_port=10,
                metadata={"s_vlan": 5},
                status=EntityStatus.UP,
            ),
            get_link_mocked(
                endpoint_a_port=11,
                endpoint_b_port=12,
                metadata={"s_vlan": 6},
                status=EntityStatus.DOWN,
            ),
        ]
        backup_path = [
            get_link_mocked(
                endpoint_a_port=13,
                endpoint_b_port=14,
                metadata={"s_vlan": 5},
                status=EntityStatus.DOWN,
            ),
            get_link_mocked(
                endpoint_a_port=11,
                endpoint_b_port=12,
                metadata={"s_vlan": 6},
                status=EntityStatus.DOWN,
            ),
        ]

        # Setup best_path mock
        best_path = Path()
        best_path.append(primary_path[0])
        get_best_path_mocked.return_value = best_path

        attributes = {
            "controller": get_controller_mock(),
            "name": "circuit_12",
            "uni_a": get_uni_mocked(is_valid=True),
            "uni_z": get_uni_mocked(is_valid=True),
            "primary_path": primary_path,
            "backup_path": backup_path,
            "enabled": True,
            "dynamic_backup_path": True,
        }

        evc = EVC(**attributes)
        evc.current_path = Path([])

        deploy_to_path_mocked.reset_mock()
        current_handle_link_up = evc.handle_link_up(backup_path[0])

        assert get_best_path_mocked.call_count == 0
        assert deploy_to_path_mocked.call_count == 1
        deploy_to_path_mocked.assert_called_once_with(old_path_dict=None)
        assert current_handle_link_up

    async def test_handle_link_up_case_5(self):
        """Test handle_link_up method."""
        return_false_mock = MagicMock(return_value=False)
        self.evc.is_using_primary_path = return_false_mock
        self.evc.primary_path.is_affected_by_link = return_false_mock
        self.evc.is_using_backup_path = MagicMock(return_value=True)
        assert self.evc.handle_link_up(MagicMock())

        # not possible to deploy this evc (it will not benefit from link up)
        self.evc.is_using_backup_path = return_false_mock
        self.evc.is_using_dynamic_path = return_false_mock
        self.evc.backup_path.is_affected_by_link = return_false_mock
        self.evc.dynamic_backup_path = True
        self.evc.deploy_to_path = return_false_mock
        assert not self.evc.handle_link_up(MagicMock())

    # pylint: disable=too-many-statements
    async def test_handle_link_up_case_6(self):
        """Test handle_link_up method."""
        # not possible to deploy this evc (it will not benefit from link up)
        return_false_mock = MagicMock(return_value=False)
        return_true_mock = MagicMock(return_value=True)
        self.evc.is_using_primary_path = return_false_mock
        self.evc.primary_path.is_affected_by_link = return_false_mock
        self.evc.is_using_backup_path = return_false_mock
        self.evc.is_using_dynamic_path = return_false_mock
        self.evc.backup_path.is_affected_by_link = return_false_mock
        self.evc.dynamic_backup_path = True

        self.evc.deploy_to_primary_path = MagicMock(return_value=False)
        self.evc.deploy_to_backup_path = MagicMock(return_value=False)
        self.evc.deploy_to_path = MagicMock(return_value=False)

        assert not self.evc.handle_link_up(MagicMock())
        assert self.evc.deploy_to_path.call_count == 1

        self.evc.is_using_primary_path = return_true_mock
        assert self.evc.handle_link_up(MagicMock())
        assert self.evc.deploy_to_path.call_count == 1

        self.evc.is_using_primary_path = return_false_mock
        self.evc.is_intra_switch = return_true_mock
        assert self.evc.handle_link_up(MagicMock())
        assert self.evc.deploy_to_path.call_count == 1

        self.evc.is_using_primary_path = return_false_mock
        self.evc.is_intra_switch = return_false_mock
        self.evc.primary_path.is_affected_by_link = return_true_mock
        assert not self.evc.handle_link_up(MagicMock())
        assert self.evc.deploy_to_primary_path.call_count == 1
        assert self.evc.deploy_to_path.call_count == 2

        self.evc.is_using_primary_path = return_false_mock
        self.evc.is_intra_switch = return_false_mock
        self.evc.primary_path.is_affected_by_link = return_true_mock
        self.evc.deploy_to_primary_path.return_value = True
        assert self.evc.handle_link_up(MagicMock())
        assert self.evc.deploy_to_primary_path.call_count == 2
        assert self.evc.deploy_to_path.call_count == 2

        self.evc.is_using_primary_path = return_false_mock
        self.evc.is_intra_switch = return_false_mock
        self.evc.primary_path.is_affected_by_link = return_false_mock
        self.evc.deploy_to_primary_path.return_value = False
        self.evc.is_using_backup_path = return_true_mock
        assert self.evc.handle_link_up(MagicMock())
        assert self.evc.deploy_to_primary_path.call_count == 2
        assert self.evc.deploy_to_path.call_count == 2

        self.evc.is_using_primary_path = return_false_mock
        self.evc.is_intra_switch = return_false_mock
        self.evc.primary_path.is_affected_by_link = return_false_mock
        self.evc.deploy_to_primary_path.return_value = False
        self.evc.is_using_backup_path = return_false_mock
        self.evc.is_using_dynamic_path = return_true_mock
        assert self.evc.handle_link_up(MagicMock())
        assert self.evc.deploy_to_primary_path.call_count == 2
        assert self.evc.deploy_to_path.call_count == 2

        self.evc.is_using_primary_path = return_false_mock
        self.evc.is_intra_switch = return_false_mock
        self.evc.primary_path.is_affected_by_link = return_false_mock
        self.evc.deploy_to_primary_path.return_value = False
        self.evc.is_using_backup_path = return_false_mock
        self.evc.is_using_dynamic_path = return_false_mock
        self.evc.backup_path.is_affected_by_link = return_true_mock
        assert not self.evc.handle_link_up(MagicMock())
        assert self.evc.deploy_to_primary_path.call_count == 2
        assert self.evc.deploy_to_backup_path.call_count == 1
        assert self.evc.deploy_to_path.call_count == 3

        self.evc.is_using_primary_path = return_false_mock
        self.evc.is_intra_switch = return_false_mock
        self.evc.primary_path.is_affected_by_link = return_false_mock
        self.evc.deploy_to_primary_path.return_value = False
        self.evc.is_using_backup_path = return_false_mock
        self.evc.is_using_dynamic_path = return_false_mock
        self.evc.backup_path.is_affected_by_link = return_true_mock
        self.evc.deploy_to_backup_path.return_value = True
        assert self.evc.handle_link_up(MagicMock())
        assert self.evc.deploy_to_primary_path.call_count == 2
        assert self.evc.deploy_to_backup_path.call_count == 2
        assert self.evc.deploy_to_path.call_count == 3

        self.evc.is_using_primary_path = return_false_mock
        self.evc.is_intra_switch = return_false_mock
        self.evc.primary_path.is_affected_by_link = return_false_mock
        self.evc.deploy_to_primary_path.return_value = False
        self.evc.is_using_backup_path = return_false_mock
        self.evc.is_using_dynamic_path = return_false_mock
        self.evc.backup_path.is_affected_by_link = return_false_mock
        self.evc.deploy_to_backup_path.return_value = False
        self.evc.dynamic_backup_path = True
        assert not self.evc.handle_link_up(MagicMock())
        assert self.evc.deploy_to_primary_path.call_count == 2
        assert self.evc.deploy_to_backup_path.call_count == 2
        assert self.evc.deploy_to_path.call_count == 4

        self.evc.is_using_primary_path = return_false_mock
        self.evc.is_intra_switch = return_false_mock
        self.evc.primary_path.is_affected_by_link = return_false_mock
        self.evc.deploy_to_primary_path.return_value = False
        self.evc.is_using_backup_path = return_false_mock
        self.evc.is_using_dynamic_path = return_false_mock
        self.evc.backup_path.is_affected_by_link = return_false_mock
        self.evc.deploy_to_backup_path.return_value = False
        self.evc.dynamic_backup_path = True
        self.evc.deploy_to_path.return_value = True
        assert self.evc.handle_link_up(MagicMock())
        assert self.evc.deploy_to_primary_path.call_count == 2
        assert self.evc.deploy_to_backup_path.call_count == 2
        assert self.evc.deploy_to_path.call_count == 5

        self.evc.is_using_primary_path = return_false_mock
        self.evc.is_intra_switch = return_false_mock
        self.evc.primary_path.is_affected_by_link = return_false_mock
        self.evc.deploy_to_primary_path.return_value = False
        self.evc.is_using_backup_path = return_false_mock
        self.evc.is_using_dynamic_path = return_false_mock
        self.evc.backup_path.is_affected_by_link = return_false_mock
        self.evc.deploy_to_backup_path.return_value = False
        self.evc.dynamic_backup_path = False
        self.evc.deploy_to_path.return_value = False
        assert not self.evc.handle_link_up(MagicMock())
        assert self.evc.deploy_to_primary_path.call_count == 2
        assert self.evc.deploy_to_backup_path.call_count == 2
        assert self.evc.deploy_to_path.call_count == 5

    @patch(DEPLOY_TO_BACKUP_PATH)
    @patch(DEPLOY_TO_PRIMARY_PATH)
    async def test_handle_link_up_case_8(
        self, deploy_primary_mock, deploy_backup_mock
    ):
        """Test when UNI is UP and dinamic primary_path from
        EVC is UP as well."""
        primary_path = [
            get_link_mocked(
                endpoint_a_port=9,
                endpoint_b_port=10,
                metadata={"s_vlan": 5},
                status=EntityStatus.UP,
            ),
            get_link_mocked(
                endpoint_a_port=11,
                endpoint_b_port=12,
                metadata={"s_vlan": 6},
                status=EntityStatus.UP,
            ),
        ]
        backup_path = [
            get_link_mocked(
                endpoint_a_port=13,
                endpoint_b_port=14,
                metadata={"s_vlan": 5},
                status=EntityStatus.UP,
            ),
            get_link_mocked(
                endpoint_a_port=11,
                endpoint_b_port=12,
                metadata={"s_vlan": 6},
                status=EntityStatus.DOWN,
            ),
        ]

        attributes = {
            "controller": get_controller_mock(),
            "name": "circuit",
            "uni_a": get_uni_mocked(is_valid=True),
            "uni_z": get_uni_mocked(is_valid=True),
            "primary_path": primary_path,
            "backup_path": backup_path,
            "enabled": True,
            "dynamic_backup_path": True,
        }

        evc = EVC(**attributes)
        evc.handle_link_up(interface=evc.uni_a.interface)
        assert deploy_primary_mock.call_count == 1
        assert deploy_backup_mock.call_count == 0

        evc.primary_path[0].status = EntityStatus.DOWN
        evc.backup_path[1].status = EntityStatus.UP
        evc.handle_link_up(interface=evc.uni_a.interface)
        assert deploy_primary_mock.call_count == 1
        assert deploy_backup_mock.call_count == 1

    async def test_get_interface_from_switch(self):
        """Test get_interface_from_switch"""
        interface = id_to_interface_mock('00:01:1')
        interface.switch.interfaces = {1: interface}
        switches = {
            '00:01': interface.switch
        }
        uni = get_uni_mocked(is_valid=True, switch_dpid='00:01')
        actual_interface = self.evc.get_interface_from_switch(uni, switches)
        assert interface == actual_interface

    async def test_are_unis_active(self):
        """Test are_unis_active"""
        interface = id_to_interface_mock('00:01:1')

        interface.switch.interfaces = {1: interface}
        switches = {
            'custom_switch_dpid': interface.switch
        }

        interface.status = EntityStatus.UP
        assert self.evc.are_unis_active(switches) is True

        interface.status = EntityStatus.DOWN
        assert self.evc.are_unis_active(switches) is False

        interface.status = EntityStatus.DISABLED
        assert self.evc.are_unis_active(switches) is False

    async def test_is_uni_interface_active(self):
        """Test is_uni_interface_active"""
        interface_a = id_to_interface_mock('00:01:1')
        interface_a.status_reason = set()
        interface_z = id_to_interface_mock('00:03:1')
        interface_z.status_reason = set()

        interface_a.status = EntityStatus.UP
        interface_z.status = EntityStatus.UP
        actual = self.evc.is_uni_interface_active(interface_a, interface_z)
        interfaces = {
            '00:01:1': {"status": "UP", "status_reason": set()},
            '00:03:1': {"status": "UP", "status_reason": set()},
        }
        expected = (True, interfaces)
        assert actual == expected

        interface_a.status = EntityStatus.DOWN
        actual = self.evc.is_uni_interface_active(interface_a, interface_z)
        interfaces = {
            '00:01:1': {'status': 'DOWN', 'status_reason': set()}
        }
        expected = (False, interfaces)
        assert actual == expected

        interface_a.status = EntityStatus.UP
        interface_z.status = EntityStatus.DOWN
        actual = self.evc.is_uni_interface_active(interface_a, interface_z)
        interfaces = {
            '00:03:1': {'status': 'DOWN', 'status_reason': set()}
        }
        expected = (False, interfaces)
        assert actual == expected

    async def test_handle_interface_link(self, monkeypatch):
        """
        Test Interface Link Up
        """
        return_false_mock = MagicMock(return_value=False)
        return_true_mock = MagicMock(return_value=True)
        interface_a = self.evc.uni_a.interface
        interface_a.enable()
        interface_b = self.evc.uni_z.interface
        interface_b.enable()
        emit_mock = MagicMock()
        monkeypatch.setattr("napps.kytos.mef_eline.models.evc.emit_event",
                            emit_mock)

        self.evc.try_to_activate = MagicMock()
        self.evc.deactivate = MagicMock()
        self.evc.sync = MagicMock()

        # Test do nothing
        self.evc.is_active = return_true_mock

        self.evc.handle_interface_link_up(interface_a)

        self.evc.try_to_activate.assert_not_called()
        self.evc.sync.assert_not_called()

        # Test deactivating
        interface_a.deactivate()

        self.evc.handle_interface_link_down(interface_a)

        self.evc.deactivate.assert_called_once()
        self.evc.sync.assert_called_once()

        # Test do nothing
        self.evc.is_active = return_false_mock

        self.evc.handle_interface_link_down(interface_a)

        self.evc.deactivate.assert_called_once()
        self.evc.sync.assert_called_once()

        # Test activating
        interface_a.activate()

        self.evc.try_to_handle_uni_as_link_up = MagicMock()
        self.evc.try_to_handle_uni_as_link_up.return_value = False
        self.evc.handle_interface_link_up(interface_a)

        self.evc.try_to_activate.assert_called_once()
        assert self.evc.sync.call_count == 2
