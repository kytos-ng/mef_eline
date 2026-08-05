"""Module to test the LinkProtection class."""
import sys
from unittest.mock import MagicMock, patch

from kytos.core.common import EntityStatus
from kytos.lib.helpers import get_controller_mock
from napps.kytos.mef_eline.models import EVC, Path  # NOQA pycodestyle
from napps.kytos.mef_eline.tests.helpers import (
    get_link_mocked,
    get_uni_mocked,
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

    def test_is_eligible_for_static_revert(self):
        """Revert eligibility: dual static and single static + dynamic.

        Eligibility ties to the keep-primary-installed regimes, which carry
        the make-before-break disjointness invariant, instead of a runtime
        disjointness check (EP041).
        """
        evc = self.evc

        def make_eligible():
            evc.primary_path = MagicMock(status=EntityStatus.UP)
            evc.is_intra_switch = MagicMock(return_value=False)
            evc.is_active = MagicMock(return_value=True)
            evc.is_using_primary_path = MagicMock(return_value=False)
            evc.has_dual_static_paths = MagicMock(return_value=True)
            evc.has_single_static_dynamic_path = MagicMock(return_value=False)

        # dual static EVC running on its backup
        make_eligible()
        assert evc.is_eligible_for_static_revert() is True

        # single static + dynamic EVC running on its dynamic failover
        make_eligible()
        evc.has_dual_static_paths = MagicMock(return_value=False)
        evc.has_single_static_dynamic_path = MagicMock(return_value=True)
        assert evc.is_eligible_for_static_revert() is True

        # neither regime keeps primary installed -> slow revert
        make_eligible()
        evc.has_dual_static_paths = MagicMock(return_value=False)
        evc.has_single_static_dynamic_path = MagicMock(return_value=False)
        assert evc.is_eligible_for_static_revert() is False

        make_eligible()
        evc.primary_path = Path([])
        assert evc.is_eligible_for_static_revert() is False

        make_eligible()
        evc.is_intra_switch = MagicMock(return_value=True)
        assert evc.is_eligible_for_static_revert() is False

        make_eligible()
        evc.is_active = MagicMock(return_value=False)
        assert evc.is_eligible_for_static_revert() is False

        make_eligible()
        # already on primary -> nothing to revert
        evc.is_using_primary_path = MagicMock(return_value=True)
        assert evc.is_eligible_for_static_revert() is False

        make_eligible()
        evc.primary_path = MagicMock(status=EntityStatus.DOWN)
        assert evc.is_eligible_for_static_revert() is False

    def test_is_eligible_for_dyn_failover_recovery(self):
        """Down static EVC (all statics down) with a dynamic backup can
        recover onto a fresh dynamic escape, keeping the configured paths
        installed (EP041)."""
        evc = self.evc

        def make_eligible():
            evc.is_active = MagicMock(return_value=False)
            evc.is_intra_switch = MagicMock(return_value=False)
            evc.primary_path = MagicMock()
            evc.dynamic_backup_path = True
            evc.current_path = MagicMock()
            evc.are_unis_active = MagicMock(return_value=True)
            evc.get_reactivation_path = MagicMock(return_value=Path([]))

        make_eligible()
        assert evc.is_eligible_for_dyn_failover_recovery() is True

        # active -> revert/normal convergence handle it, not this path
        make_eligible()
        evc.is_active = MagicMock(return_value=True)
        assert evc.is_eligible_for_dyn_failover_recovery() is False

        # a configured static path is usable -> revert/reactivation instead
        make_eligible()
        evc.get_reactivation_path = MagicMock(return_value=MagicMock())
        assert evc.is_eligible_for_dyn_failover_recovery() is False

        # no dynamic backup -> nothing to escape to
        make_eligible()
        evc.dynamic_backup_path = False
        assert evc.is_eligible_for_dyn_failover_recovery() is False

        # fully undeployed (no kept statics) -> plain ladder install instead
        make_eligible()
        evc.current_path = Path([])
        assert evc.is_eligible_for_dyn_failover_recovery() is False

        # not a static EVC (no primary) -> not handled here
        make_eligible()
        evc.primary_path = Path([])
        assert evc.is_eligible_for_dyn_failover_recovery() is False

        # intra switch -> no path to protect
        make_eligible()
        evc.is_intra_switch = MagicMock(return_value=True)
        assert evc.is_eligible_for_dyn_failover_recovery() is False

    @patch("napps.kytos.mef_eline.models.path.DynamicPathManager"
           ".get_disjointness")
    def test_is_failover_reusable_after_revert(self, disjoint_mock):
        """After reverting to primary, the old dynamic failover is reusable
        only when UP and disjoint from primary (EP041)."""
        evc = self.evc
        evc.primary_path = MagicMock()

        # UP and disjoint -> keep
        evc.failover_path = MagicMock(status=EntityStatus.UP)
        disjoint_mock.return_value = 1.0
        assert evc.is_failover_reusable_after_revert() is True

        # UP but not disjoint -> clear
        disjoint_mock.return_value = 0
        assert evc.is_failover_reusable_after_revert() is False

        # down (affected) -> clear
        evc.failover_path = MagicMock(status=EntityStatus.DOWN)
        disjoint_mock.return_value = 1.0
        assert evc.is_failover_reusable_after_revert() is False

        # no failover parked -> nothing to keep
        evc.failover_path = Path([])
        assert evc.is_failover_reusable_after_revert() is False

    def test_has_dual_static_paths(self):
        """Test has_dual_static_paths classifies by configuration (EP041).

        Disjointness is guaranteed upstream by _validate_paths_distinct, so
        this only checks both static paths are set on a non-intra EVC.
        """
        evc = self.evc
        evc.is_intra_switch = MagicMock(return_value=False)
        evc.primary_path = Path([MagicMock()])
        evc.backup_path = Path([MagicMock()])

        assert evc.has_dual_static_paths() is True

        evc.backup_path = Path([])
        assert evc.has_dual_static_paths() is False
        evc.backup_path = Path([MagicMock()])

        evc.primary_path = Path([])
        assert evc.has_dual_static_paths() is False
        evc.primary_path = Path([MagicMock()])

        evc.is_intra_switch = MagicMock(return_value=True)
        assert evc.has_dual_static_paths() is False

    @patch("napps.kytos.mef_eline.models.path.DynamicPathManager"
           ".get_disjointness")
    def test_has_single_static_dynamic_path(self, get_disjointness_mock):
        """Test has_single_static_dynamic_path guards (EP041)."""
        evc = self.evc
        get_disjointness_mock.return_value = 1.0
        evc.is_intra_switch = MagicMock(return_value=False)
        evc.primary_path = Path([MagicMock()])
        evc.backup_path = Path([])
        evc.dynamic_backup_path = True

        assert evc.has_single_static_dynamic_path() is True

        evc.dynamic_backup_path = False
        assert evc.has_single_static_dynamic_path() is False
        evc.dynamic_backup_path = True

        evc.primary_path = Path([])
        assert evc.has_single_static_dynamic_path() is False
        evc.primary_path = Path([MagicMock()])

        # a disjoint static backup makes it dual static, not
        # single static + dynamic
        evc.backup_path = Path([MagicMock()])
        assert evc.has_single_static_dynamic_path() is False
        evc.backup_path = Path([])

        evc.is_intra_switch = MagicMock(return_value=True)
        assert evc.has_single_static_dynamic_path() is False

    def test_has_single_static_path(self):
        """Test has_single_static_path (lone primary) (EP041)."""
        evc = self.evc
        evc.is_intra_switch = MagicMock(return_value=False)
        evc.primary_path = Path([MagicMock()])
        evc.backup_path = Path([])
        evc.dynamic_backup_path = False

        assert evc.has_single_static_path() is True

        # a static backup makes it dual static, not single
        evc.backup_path = Path([MagicMock()])
        assert evc.has_single_static_path() is False
        evc.backup_path = Path([])

        # a dynamic backup makes it single static + dynamic, not single
        evc.dynamic_backup_path = True
        assert evc.has_single_static_path() is False
        evc.dynamic_backup_path = False

        evc.primary_path = Path([])
        assert evc.has_single_static_path() is False
        evc.primary_path = Path([MagicMock()])

        evc.is_intra_switch = MagicMock(return_value=True)
        assert evc.has_single_static_path() is False

    def test_get_static_standby_path(self):
        """Test get_static_standby_path (EP041)."""
        evc = self.evc
        primary, backup = Path([MagicMock()]), Path([MagicMock()])
        evc.primary_path, evc.backup_path = primary, backup

        # dual static on primary -> backup is the standby
        evc.is_using_primary_path = MagicMock(return_value=True)
        assert evc.get_static_standby_path() is backup

        # dual static on backup, or single static + dynamic on a dynamic
        # path -> primary
        evc.is_using_primary_path = MagicMock(return_value=False)
        assert evc.get_static_standby_path() is primary

        # no primary configured -> no standby
        evc.primary_path = Path([])
        assert not evc.get_static_standby_path()

    def test_get_reactivation_path(self):
        """Test get_reactivation_path prefers an UP primary (EP041)."""
        evc = self.evc
        primary = MagicMock(status=EntityStatus.UP)
        backup = MagicMock(status=EntityStatus.UP)
        evc.primary_path, evc.backup_path = primary, backup
        # primary preferred (non revertive) when both are UP
        assert evc.get_reactivation_path() is primary

        primary.status = EntityStatus.DOWN
        # falls back to the backup when only it is UP
        assert evc.get_reactivation_path() is backup

        backup.status = EntityStatus.DOWN
        # neither UP -> nothing to resume on
        assert not evc.get_reactivation_path()

    def test_is_eligible_for_static_reactivation(self):
        """Test is_eligible_for_static_reactivation guards (EP041)."""
        evc = self.evc
        link = MagicMock()

        def make_eligible():
            evc.is_active = MagicMock(return_value=False)
            evc.current_path = Path([MagicMock()])
            evc.has_dual_static_paths = MagicMock(return_value=True)
            evc.has_single_static_path = MagicMock(return_value=False)
            evc.has_single_static_dynamic_path = MagicMock(return_value=False)
            evc.are_unis_active = MagicMock(return_value=True)
            evc.is_primary_path_affected_by_link = MagicMock(
                return_value=True
            )
            evc.is_backup_path_affected_by_link = MagicMock(
                return_value=False
            )
            evc.get_reactivation_path = MagicMock(
                return_value=Path([MagicMock()])
            )

        make_eligible()
        assert evc.is_eligible_for_static_reactivation(link) is True

        make_eligible()
        # a lone static primary also reactivates via ingress reinstall
        evc.has_dual_static_paths = MagicMock(return_value=False)
        evc.has_single_static_path = MagicMock(return_value=True)
        assert evc.is_eligible_for_static_reactivation(link) is True

        make_eligible()
        # a single static + dynamic EVC (primary + dynamic backup) also
        # reactivates onto primary
        evc.has_dual_static_paths = MagicMock(return_value=False)
        evc.has_single_static_dynamic_path = MagicMock(return_value=True)
        assert evc.is_eligible_for_static_reactivation(link) is True

        make_eligible()
        evc.is_active = MagicMock(return_value=True)
        assert evc.is_eligible_for_static_reactivation(link) is False

        make_eligible()
        # a cleared current_path means it was fully torn down -> redeploy
        evc.current_path = Path([])
        assert evc.is_eligible_for_static_reactivation(link) is False

        make_eligible()
        # a down UNI must not be silently reactivated
        evc.are_unis_active = MagicMock(return_value=False)
        assert evc.is_eligible_for_static_reactivation(link) is False

        make_eligible()
        evc.has_dual_static_paths = MagicMock(return_value=False)
        assert evc.is_eligible_for_static_reactivation(link) is False

        make_eligible()
        evc.is_primary_path_affected_by_link = MagicMock(return_value=False)
        evc.is_backup_path_affected_by_link = MagicMock(return_value=False)
        assert evc.is_eligible_for_static_reactivation(link) is False

        make_eligible()
        evc.get_reactivation_path = MagicMock(return_value=Path([]))
        assert evc.is_eligible_for_static_reactivation(link) is False

    def test_is_eligible_for_standby_install(self):
        """A never-deployed target needs its standby installed first, not an
        ingress-only reactivation (EP041)."""
        evc = self.evc
        link = MagicMock()
        evc.is_active = MagicMock(return_value=False)
        evc.current_path = Path([MagicMock()])
        evc.has_dual_static_paths = MagicMock(return_value=True)
        evc.are_unis_active = MagicMock(return_value=True)
        evc.is_primary_path_affected_by_link = MagicMock(return_value=True)

        deployed = Path([MagicMock()])  # mock metadata -> deployed
        evc.get_reactivation_path = MagicMock(return_value=deployed)
        assert evc.is_eligible_for_static_reactivation(link) is True
        assert evc.is_eligible_for_standby_install(link) is False

        never = MagicMock()
        never.get_metadata.return_value = None  # no s_vlan
        evc.get_reactivation_path = MagicMock(return_value=Path([never]))
        assert evc.is_eligible_for_static_reactivation(link) is False
        assert evc.is_eligible_for_standby_install(link) is True

        evc.get_reactivation_path = MagicMock(return_value=Path([]))
        assert evc.is_eligible_for_standby_install(link) is False

    @patch("napps.kytos.mef_eline.models.evc.EVCDeploy.deploy")
    async def test_handle_link_up_case_1(
        self,
        deploy_to_mocked,
    ):
        """Test if handle link up do nothing when is using primary path."""
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
        """A live EVC on backup is not reverted by the model ladder.

        With primary fully UP the EVC keeps forwarding on its provisioned
        backup: the model no longer break-before-makes to primary. The revert
        is an ingress swap driven by the napp (execute_revert_to_primary), not
        a redeploy here (EP041).
        """
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
        # No break-before-make revert: the provisioned backup stays live
        assert deploy_mocked.call_count == 0
        assert deploy_to_path_mocked.call_count == 0
        assert evc.current_path == evc.backup_path
        assert current_handle_link_up

    @patch("napps.kytos.mef_eline.models.evc.EVCDeploy.deploy")
    @patch("napps.kytos.mef_eline.models.evc.EVCDeploy.deploy_to_path")
    @patch("napps.kytos.mef_eline.models.evc.EVC._install_flows")
    @patch("napps.kytos.mef_eline.models.path.Path.status", EntityStatus.UP)
    async def test_handle_link_up_case_3(
        self,
        _install_flows_mocked,
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

        assert deploy_mocked.call_count == 0
        assert deploy_to_path_mocked.call_count == 1
        deploy_to_path_mocked.assert_called_once_with(evc.backup_path, None)
        assert current_handle_link_up

    @patch("napps.kytos.mef_eline.models.evc.EVCDeploy.deploy_to_path")
    @patch("napps.kytos.mef_eline.models.evc.EVC._install_flows")
    @patch("napps.kytos.mef_eline.models.path.Path.status", EntityStatus.DOWN)
    async def test_handle_link_up_case_4(self, *args):
        """Test if not path is found a dynamic path is used."""
        (
            _install_flows_mocked,
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
    async def test_handle_link_up_keeps_provisioned_static(
        self, deploy_primary_mock, deploy_backup_mock
    ):
        """A live static EVC must not break-before-make on convergence.

        When a static EVC already has a path provisioned (non-empty
        current_path) and a primary link recovers, handle_link_up must NOT
        redeploy (which would tear down the live flows). It leaves the paths
        installed; the napp reverts via an ingress swap once primary is fully
        UP (EP041).
        """
        # Live on backup, so current_path is provisioned (non-empty)
        self.evc.current_path = self.evc.backup_path
        self.evc.is_using_primary_path = MagicMock(return_value=False)
        self.evc.is_intra_switch = MagicMock(return_value=False)
        # A primary link came back up
        self.evc.primary_path.is_affected_by_link = MagicMock(
            return_value=True
        )
        self.evc.is_using_backup_path = MagicMock(return_value=True)

        assert self.evc.handle_link_up(MagicMock())

        # No break-before-make redeploy; the backup stays live
        assert deploy_primary_mock.call_count == 0
        assert deploy_backup_mock.call_count == 0
        assert self.evc.current_path == self.evc.backup_path

    async def test_handle_link_up_case_7(self):
        """Test handle_link_up method."""
        return_false_mock = MagicMock(return_value=False)
        self.evc.is_using_primary_path = return_false_mock
        self.evc.primary_path.is_affected_by_link = return_false_mock
        self.evc.is_using_dynamic_path = return_false_mock
        self.evc.backup_path.is_affected_by_link = return_false_mock
        self.evc.dynamic_backup_path = True
        self.evc.activate()
        assert self.evc.is_active()
        self.evc.deploy_to_path = MagicMock(return_value=True)
        assert not self.evc.handle_link_up(MagicMock())
        assert self.evc.deploy_to_path.call_count == 0

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

    async def test_are_unis_active(self):
        """Test are_unis_active"""
        self.evc.uni_a.interface._enabled = True
        self.evc.uni_z.interface._enabled = True
        assert self.evc.are_unis_active() is True

        self.evc.uni_a.interface._active = False
        self.evc.uni_z.interface._active = False
        assert self.evc.are_unis_active() is False

        self.evc.uni_a.interface._enabled = False
        self.evc.uni_z.interface._enabled = False
        assert self.evc.are_unis_active() is False

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

        assert emit_mock.call_count == 0
        self.evc.handle_interface_link_down(interface_a)
        assert emit_mock.call_count == 1

        self.evc.deactivate.assert_called_once()
        self.evc.sync.assert_called_once()

        # Test do nothing
        self.evc.is_active = return_false_mock

        self.evc.handle_interface_link_down(interface_a)

        self.evc.deactivate.assert_called_once()
        self.evc.sync.assert_called_once()

        # Test activating
        interface_a.activate()

        assert emit_mock.call_count == 1
        self.evc.try_to_handle_uni_as_link_up = MagicMock()
        self.evc.try_to_handle_uni_as_link_up.return_value = False
        self.evc.handle_interface_link_up(interface_a)

        self.evc.try_to_activate.assert_called_once()
        assert self.evc.sync.call_count == 2
        assert emit_mock.call_count == 2
