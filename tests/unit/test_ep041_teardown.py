"""Regression tests for EP041 dual-static standby teardown.

A dual static EVC keeps its standby path's egress/NNI flows installed on
disjoint switches. remove_current_flows only sweeps the current path's
switches by cookie, so every teardown path must call
remove_static_standby_flows first or the standby's flows/VLANs leak. These
lock the paths that previously missed it (EP041).
"""
import asyncio
from unittest.mock import MagicMock, patch

from kytos.lib.helpers import get_controller_mock, get_test_client
from kytos.core.common import EntityStatus
from kytos.core.events import KytosEvent
from napps.kytos.mef_eline.models import EVC, Path
from napps.kytos.mef_eline.tests.helpers import (
    get_link_mocked,
    get_uni_mocked,
)


class TestEP041Teardown:
    """Teardown paths must sweep the dual-static standby."""

    def setup_method(self):
        """Build a Main napp with a mocked controller."""
        patch("kytos.core.helpers.run_on_thread", lambda x: x).start()
        # pylint: disable=import-outside-toplevel
        from napps.kytos.mef_eline.main import Main
        Main.get_eline_controller = MagicMock()
        controller = get_controller_mock()
        self.napp = Main(controller)
        self.api_client = get_test_client(controller, self.napp)
        self.base_endpoint = "kytos/mef_eline"

    async def test_delete_circuit_sweeps_standby(self):
        """delete_circuit removes the standby before remove_current_flows."""
        parent = MagicMock()
        evc = parent.evc
        evc.archived = False
        self.napp.circuits = {"1": evc}
        self.napp.sched = MagicMock()

        response = await self.api_client.delete(
            f"{self.base_endpoint}/v2/evc/1"
        )

        assert response.status_code == 200, response.text
        evc.remove_static_standby_flows.assert_called_once()
        # must run before remove_current_flows (standby derives from current)
        names = [c[0] for c in parent.evc.method_calls]
        assert names.index("remove_static_standby_flows") < \
            names.index("remove_current_flows")

    @patch("napps.kytos.mef_eline.main.EVC.get_id_from_cookie",
           return_value="1")
    def test_handle_flow_mod_error_sweeps_standby(self, _get_id_mock):
        """handle_flow_mod_error removes the standby before current flows."""
        parent = MagicMock()
        evc = parent.evc
        evc.archived = False
        evc.is_enabled.return_value = True
        self.napp.circuits = {"1": evc}

        event = KytosEvent(content={
            "flow": MagicMock(cookie=0xaa1),
            "error_command": "add",
        })
        self.napp.handle_flow_mod_error(event)

        evc.remove_static_standby_flows.assert_called_once()
        names = [c[0] for c in parent.evc.method_calls]
        assert names.index("remove_static_standby_flows") < \
            names.index("remove_current_flows")

    async def test_disable_inactive_kept_flows_tears_down(self):
        """Disabling an inactive EVC that still holds flows removes them."""
        self.napp.controller.loop = asyncio.get_running_loop()
        evc = MagicMock(id="1")
        evc.as_dict.return_value = {}
        evc.update.return_value = (False, None)  # (enable, redeploy)
        evc.is_active.return_value = False
        evc.current_path = MagicMock(__bool__=lambda self: True)
        self.napp.circuits = {"1": evc}
        self.napp._check_no_tag_duplication = MagicMock()
        self.napp._evc_dict_with_instances = MagicMock(return_value={})

        response = await self.api_client.patch(
            f"{self.base_endpoint}/v2/evc/1", json={"enabled": False}
        )

        assert response.status_code == 200, response.text
        evc.remove.assert_called_once()
        evc.deploy.assert_not_called()

    async def test_disable_torn_down_evc_is_noop(self):
        """Disabling an already torn-down EVC (no current_path) does not
        try to remove flows."""
        self.napp.controller.loop = asyncio.get_running_loop()
        evc = MagicMock(id="1")
        evc.as_dict.return_value = {}
        evc.update.return_value = (False, None)
        evc.is_active.return_value = False
        evc.current_path = MagicMock(__bool__=lambda self: False)
        self.napp.circuits = {"1": evc}
        self.napp._check_no_tag_duplication = MagicMock()
        self.napp._evc_dict_with_instances = MagicMock(return_value={})

        response = await self.api_client.patch(
            f"{self.base_endpoint}/v2/evc/1", json={"enabled": False}
        )

        assert response.status_code == 200, response.text
        evc.remove.assert_not_called()

    @patch("napps.kytos.mef_eline.models.path.Path.is_valid")
    def test_update_sweeps_old_standby_while_inactive(self, _is_valid_mock):
        """BUG 3b: updating the standby path of an inactive kept-flows dual
        static EVC sweeps the OLD standby before its config is overwritten,
        even though the EVC is not active."""
        primary = [get_link_mocked(endpoint_a_port=9, endpoint_b_port=10,
                                   metadata={"s_vlan": 5})]
        backup = [get_link_mocked(endpoint_a_port=13, endpoint_b_port=14,
                                  metadata={"s_vlan": 6})]
        evc = EVC(
            controller=get_controller_mock(),
            name="c1",
            uni_a=get_uni_mocked(is_valid=True),
            uni_z=get_uni_mocked(is_valid=True),
            primary_path=primary,
            backup_path=backup,
            enabled=True,
        )
        evc.current_path = evc.primary_path  # on primary, flows kept
        evc.deactivate()                     # inactive after a full failure
        evc._validate_paths_distinct = MagicMock()
        evc._get_unis_use_tags = MagicMock(return_value=(evc.uni_a, evc.uni_z))
        evc.sync = MagicMock()
        evc.remove_static_standby_flows = MagicMock()

        new_backup = Path([get_link_mocked(endpoint_a_port=15,
                                           endpoint_b_port=16,
                                           metadata={"s_vlan": 7})])
        evc.update(backup_path=new_backup)

        assert not evc.is_active()
        evc.remove_static_standby_flows.assert_called_once()

    @patch("napps.kytos.mef_eline.models.path.Path.is_valid")
    def test_update_backup_on_dynamic_escape_sweeps_standbys(
        self, _is_valid_mock
    ):
        """A dual static + dynamic EVC on a dynamic escape keeps BOTH statics
        installed, so both are standbys. Updating only backup_path must still
        sweep before the overwrite: the old single standby_key heuristic
        picked primary_path here, skipped the sweep, and leaked the old
        backup's flows and s_vlan (EP041)."""
        primary = [get_link_mocked(endpoint_a_port=9, endpoint_b_port=10,
                                   metadata={"s_vlan": 5})]
        backup = [get_link_mocked(endpoint_a_port=13, endpoint_b_port=14,
                                  metadata={"s_vlan": 6})]
        evc = EVC(
            controller=get_controller_mock(),
            name="c1",
            uni_a=get_uni_mocked(is_valid=True),
            uni_z=get_uni_mocked(is_valid=True),
            primary_path=primary,
            backup_path=backup,
            dynamic_backup_path=True,
            enabled=True,
        )
        # forwarding on a cold dynamic escape: neither static is current
        evc.current_path = Path([get_link_mocked(endpoint_a_port=17,
                                                 endpoint_b_port=18,
                                                 metadata={"s_vlan": 8})])
        evc._validate_paths_distinct = MagicMock()
        evc._get_unis_use_tags = MagicMock(return_value=(evc.uni_a, evc.uni_z))
        evc.sync = MagicMock()
        evc.remove_static_standby_flows = MagicMock()

        new_backup = Path([get_link_mocked(endpoint_a_port=15,
                                           endpoint_b_port=16,
                                           metadata={"s_vlan": 7})])
        evc.update(backup_path=new_backup)

        evc.remove_static_standby_flows.assert_called_once()

    def test_standby_link_down_syncs_without_touching_flows(self):
        """A dual static EVC forwarding on one path whose standby's link goes
        down is persisted (sync), but its flows are left untouched (EP041)."""
        link = MagicMock()
        evc = MagicMock(id="1")
        evc.has_dual_static_paths.return_value = True
        evc.is_affected_by_link.return_value = False  # not on the current path
        standby = MagicMock()
        standby.is_affected_by_link.return_value = True  # the standby is down
        evc.get_static_standby_path.return_value = standby
        self.napp.get_evcs_by_svc_level = MagicMock(return_value=[evc])
        self.napp.mongo_controller = MagicMock()

        self.napp.handle_link_down(KytosEvent(content={"link": link}))

        # persisted, but no flow operation touched it
        self.napp.mongo_controller.update_evcs.assert_called_once_with(
            [evc.as_dict()]
        )
        evc.remove_static_standby_flows.assert_not_called()

    def test_single_static_link_down_removes_ingress(self):
        """A single static EVC (lone primary) on link_down drops only its UNI
        ingress and keeps egress/NNI, instead of undeploying (EP041)."""
        link = MagicMock()
        evc = MagicMock(id="1")
        evc.has_dual_static_paths.return_value = False
        evc.has_single_static_path.return_value = True
        evc.dynamic_backup_path = False  # lone primary, no dynamic escape
        evc.is_affected_by_link.return_value = True
        evc.is_active.return_value = True
        evc.get_static_standby_path.return_value = Path([])  # no standby
        self.napp.get_evcs_by_svc_level = MagicMock(return_value=[evc])
        self.napp.execute_remove_ingress = MagicMock(return_value=([evc], []))
        self.napp.execute_undeploy = MagicMock(return_value=([], []))
        self.napp.mongo_controller = MagicMock()

        self.napp.handle_link_down(KytosEvent(content={"link": link}))

        self.napp.execute_remove_ingress.assert_called_once_with([evc])
        self.napp.execute_undeploy.assert_not_called()

    def test_ssd_no_usable_failover_keeps_primary(self):
        """A single static + dynamic EVC whose path is down with no usable
        failover is routed to execute_dyn_escape (keep primary), never
        undeploy (EP041)."""
        link = MagicMock()
        evc = MagicMock(id="1")
        evc.has_dual_static_paths.return_value = False
        evc.has_single_static_path.return_value = False
        evc.has_single_static_dynamic_path.return_value = True
        evc.is_affected_by_link.return_value = True
        evc.failover_path = Path([])  # no usable failover
        self.napp.get_evcs_by_svc_level = MagicMock(return_value=[evc])
        self.napp.execute_dyn_escape = MagicMock(
            return_value=([evc], [])
        )
        self.napp.execute_undeploy = MagicMock(return_value=([], []))
        self.napp.mongo_controller = MagicMock()

        self.napp.handle_link_down(KytosEvent(content={"link": link}))

        self.napp.execute_dyn_escape.assert_called_once_with([evc])
        self.napp.execute_undeploy.assert_not_called()

    def test_dual_dynamic_link_down_tries_dyn_escape(self):
        """dual + dynamic on a double failure routes to the dynamic escape
        (execute_dyn_escape), keeping both statics installed, instead
        of only removing the ingress like a plain dual EVC (EP041)."""
        link = MagicMock()
        standby_down = MagicMock(status=EntityStatus.DOWN)
        evc = MagicMock(id="1")
        evc.has_dual_static_paths.return_value = True
        evc.has_single_static_path.return_value = False
        evc.dynamic_backup_path = True          # dual + dynamic
        evc.is_affected_by_link.return_value = True
        evc.is_active.return_value = True
        evc.get_static_standby_path.return_value = standby_down  # both down
        self.napp.get_evcs_by_svc_level = MagicMock(return_value=[evc])
        self.napp.execute_dyn_escape = MagicMock(
            return_value=([evc], [])
        )
        self.napp.execute_remove_ingress = MagicMock(return_value=([], []))
        self.napp.execute_undeploy = MagicMock(return_value=([], []))
        self.napp.mongo_controller = MagicMock()

        self.napp.handle_link_down(KytosEvent(content={"link": link}))

        self.napp.execute_dyn_escape.assert_called_once_with([evc])
        self.napp.execute_remove_ingress.assert_not_called()
        self.napp.execute_undeploy.assert_not_called()

    @patch("napps.kytos.mef_eline.main.send_flow_mods_http")
    @patch("napps.kytos.mef_eline.main.prepare_delete_flow")
    def test_execute_dyn_escape_on_dynamic_keeps_primary(
        self, prep_del_mock, send_mock
    ):
        """On a dynamic path, no failover, no fresh dynamic: clear the dynamic,
        keep primary, repoint current to primary, deactivate (EP041)."""
        prep_del_mock.side_effect = lambda f: {"1": ["del"]} if f else {}
        primary, dynamic = MagicMock(id="P"), MagicMock(id="D")
        evc = MagicMock(id="1")
        evc.primary_path = primary
        evc.current_path = dynamic          # forwarding on a dynamic path
        evc.failover_path = Path([])
        evc.setup_failover_path.return_value = False  # no fresh dynamic
        evc._prepare_uni_flows.return_value = {"1": ["ingress"]}
        self.napp.execute_swap_to_failover = MagicMock()

        done, not_done = self.napp.execute_dyn_escape([evc])

        assert done == [evc]
        send_mock.assert_called_once_with({"1": ["del"]}, "delete")
        # the dynamic path is cleared; primary is never removed
        evc.remove_path_flows.assert_called_once_with(dynamic)
        self.napp.execute_swap_to_failover.assert_not_called()
        assert evc.current_path is primary
        evc.deactivate.assert_called_once_with()

    @patch("napps.kytos.mef_eline.main.send_flow_mods_http")
    @patch("napps.kytos.mef_eline.main.prepare_delete_flow")
    def test_execute_dyn_escape_on_primary_keeps_primary(
        self, prep_del_mock, send_mock
    ):
        """On primary, dead failover, no fresh dynamic: clear the failover,
        keep primary, deactivate (EP041)."""
        prep_del_mock.side_effect = lambda f: {"1": ["del"]} if f else {}
        primary, dead = MagicMock(id="P"), MagicMock(id="D")
        evc = MagicMock(id="1")
        evc.primary_path = primary
        evc.current_path = primary          # forwarding on primary
        evc.failover_path = dead            # dead pre-installed dynamic
        evc.setup_failover_path.return_value = False  # no fresh dynamic
        evc._prepare_uni_flows.return_value = {"1": ["ingress"]}
        self.napp.execute_swap_to_failover = MagicMock()

        done, _ = self.napp.execute_dyn_escape([evc])

        assert done == [evc]
        # only the dead failover is cleared, primary is kept
        evc.remove_path_flows.assert_called_once_with(dead)
        self.napp.execute_swap_to_failover.assert_not_called()
        assert evc.current_path is primary
        evc.deactivate.assert_called_once_with()

    def test_execute_dyn_escape_recovers_on_fresh_dynamic(self):
        """A double failure with a third path available: recover onto a fresh
        dynamic (swap), keeping primary; do not deactivate (EP041)."""
        primary, dead = MagicMock(id="P"), MagicMock(id="D")
        fresh = MagicMock(id="D2", status=EntityStatus.UP)
        evc = MagicMock(id="1")
        evc.primary_path = primary
        evc.current_path = primary
        evc.failover_path = dead

        def _setup(warn_if_not_path=True):
            evc.failover_path = fresh   # a fresh disjoint dynamic is installed
            return True
        evc.setup_failover_path.side_effect = _setup
        self.napp.execute_swap_to_failover = MagicMock(
            return_value=([evc], [])
        )

        done, _ = self.napp.execute_dyn_escape([evc])

        assert done == [evc]
        # swapped onto the fresh dynamic, primary kept, not deactivated
        self.napp.execute_swap_to_failover.assert_called_once_with([evc])
        assert not evc.failover_path  # detached, primary is the standby
        evc.deactivate.assert_not_called()

    def test_execute_dyn_escape_activates_on_recovery(self):
        """On link_up a down EVC recovers onto a fresh dynamic and is
        activated (the swap alone does not activate an inactive EVC)
        (EP041)."""
        primary = MagicMock(id="P")
        fresh = MagicMock(id="D2", status=EntityStatus.UP)
        evc = MagicMock(id="1")
        evc.primary_path = primary
        evc.current_path = primary
        evc.failover_path = Path([])

        def _setup(warn_if_not_path=True):
            evc.failover_path = fresh
            return True
        evc.setup_failover_path.side_effect = _setup
        self.napp.execute_swap_to_failover = MagicMock(
            return_value=([evc], [])
        )

        done, _ = self.napp.execute_dyn_escape([evc])

        assert done == [evc]
        evc.try_to_activate.assert_called_once_with()
        evc.deactivate.assert_not_called()

    def test_execute_dyn_escape_dual_keeps_backup(self):
        """dual + dynamic: escaping to a fresh dynamic on a double failure must
        not tear down the backup, which is a configured static (EP041)."""
        primary, backup = MagicMock(id="P"), MagicMock(id="B")
        fresh = MagicMock(id="D2", status=EntityStatus.UP)
        evc = MagicMock(id="1")
        evc.primary_path = primary
        evc.backup_path = backup
        evc.current_path = backup          # was forwarding on backup
        evc.failover_path = Path([])

        def _setup(warn_if_not_path=True):
            evc.failover_path = fresh
            return True
        evc.setup_failover_path.side_effect = _setup
        self.napp.execute_swap_to_failover = MagicMock(
            return_value=([evc], [])
        )

        done, _ = self.napp.execute_dyn_escape([evc])

        assert done == [evc]
        # neither configured static (primary nor backup) is removed
        evc.remove_path_flows.assert_not_called()
        evc.try_to_activate.assert_called_once_with()

    def test_link_up_routes_dyn_recovery(self):
        """A down static EVC with a dynamic escape is routed to the dynamic
        recovery path (execute_dyn_escape), never the redeploy ladder
        that would break-before-make its configured paths (EP041)."""
        link = MagicMock(id="l")
        evc = MagicMock(id="1")
        evc.is_enabled.return_value = True
        evc.archived = False
        evc.is_eligible_for_static_revert.return_value = False
        evc.is_eligible_for_static_reactivation.return_value = False
        evc.is_eligible_for_standby_install.return_value = False
        evc.is_eligible_for_dyn_failover_recovery.return_value = True

        self.napp.get_evcs_by_svc_level = MagicMock(return_value=[evc])
        self.napp.execute_dyn_escape = MagicMock(
            return_value=([evc], [])
        )
        self.napp.execute_reactivate_static = MagicMock(return_value=([], []))
        self.napp.execute_revert_to_primary = MagicMock(return_value=([], []))
        self.napp.mongo_controller = MagicMock()

        self.napp.handle_link_up(KytosEvent(content={"link": link}))

        self.napp.execute_dyn_escape.assert_called_once_with([evc])
        evc.handle_link_up.assert_not_called()

    @patch("napps.kytos.mef_eline.main.emit_event")
    @patch("napps.kytos.mef_eline.main.send_flow_mods_http")
    def test_swap_to_standby_ensures_standby_installed(self, _send, _emit):
        """The swap ensures the standby is installed (deploy_static_standby is
        a no-op when kept, a cold install when it never was, e.g. a pre-EP041
        EVC) before moving the ingress onto it (EP041)."""
        evc = MagicMock(id="1")
        evc.deploy_static_standby.return_value = True
        evc.get_static_standby_path.return_value = MagicMock()
        evc.get_static_standby_ingress_flows.return_value = {"1": ["Ingress"]}
        self.napp.prepare_swap_to_failover_event = {evc: "E"}.get

        self.napp.execute_swap_to_standby([evc])

        evc.deploy_static_standby.assert_called_once_with()

    @patch("napps.kytos.mef_eline.main.emit_event")
    @patch("napps.kytos.mef_eline.main.send_flow_mods_http")
    def test_swap_to_standby_skips_when_cold_install_fails(self, _send, _emit):
        """A failed standby cold install (disconnected switch, VLAN exhaustion)
        must not swap the ingress onto a path with no egress/NNI: the EVC is
        left un-swapped for the undeploy/redeploy fallback (EP041)."""
        evc = MagicMock(id="1")
        evc.deploy_static_standby.return_value = False  # cold install failed
        evc.get_static_standby_path.return_value = MagicMock()

        swapped, not_swapped = self.napp.execute_swap_to_standby([evc])

        assert swapped == []
        assert not_swapped == [evc]
        evc.get_static_standby_ingress_flows.assert_not_called()

    @patch("napps.kytos.mef_eline.main.emit_event")
    @patch("napps.kytos.mef_eline.main.send_flow_mods_http")
    def test_swap_to_standby_removes_throwaway_dyn_escape(self, _send, _emit):
        """A dual static + dynamic EVC swapping off a throwaway dynamic escape
        (double-failure recovery) tears the escape down so its flows/VLANs are
        not orphaned when current_path is overwritten (EP041)."""
        primary, backup, escape = (
            MagicMock(id="P"), MagicMock(id="B"), MagicMock(id="D")
        )
        evc = MagicMock(id="1")
        evc.primary_path = primary
        evc.backup_path = backup
        evc.current_path = escape          # forwarding on the dynamic escape
        evc.get_static_standby_path.return_value = primary  # revert target
        evc.get_static_standby_ingress_flows.return_value = {"1": ["Ingress"]}
        self.napp.prepare_swap_to_failover_event = MagicMock(return_value="E")

        self.napp.execute_swap_to_standby([evc])

        assert evc.current_path is primary
        evc.remove_path_flows.assert_called_once_with(escape)

    @patch("napps.kytos.mef_eline.main.emit_event")
    @patch("napps.kytos.mef_eline.main.send_flow_mods_http")
    def test_swap_to_standby_keeps_old_configured_path(self, _send, _emit):
        """A normal dual static swap keeps the old configured path installed as
        the new standby - it is never torn down (EP041)."""
        primary, backup = MagicMock(id="P"), MagicMock(id="B")
        evc = MagicMock(id="1")
        evc.primary_path = primary
        evc.backup_path = backup
        evc.current_path = backup          # on backup, swapping to primary
        evc.get_static_standby_path.return_value = primary
        evc.get_static_standby_ingress_flows.return_value = {"1": ["Ingress"]}
        self.napp.prepare_swap_to_failover_event = MagicMock(return_value="E")

        self.napp.execute_swap_to_standby([evc])

        assert evc.current_path is primary
        evc.remove_path_flows.assert_not_called()

    @patch("napps.kytos.mef_eline.main.emit_event")
    @patch("napps.kytos.mef_eline.main.send_flow_mods_http")
    def test_swap_to_standby_single_dyn_keeps_old_dynamic(self, _send, _emit):
        """single static + dynamic revert: execute_swap_to_standby must not
        tear down the old dynamic (no backup); execute_revert_to_primary
        re-parks it as failover_path (EP041)."""
        primary, dyn = MagicMock(id="P"), MagicMock(id="D")
        evc = MagicMock(id="1")
        evc.primary_path = primary
        evc.backup_path = Path([])         # single static + dynamic, no backup
        evc.current_path = dyn
        evc.get_static_standby_path.return_value = primary
        evc.get_static_standby_ingress_flows.return_value = {"1": ["Ingress"]}
        self.napp.prepare_swap_to_failover_event = MagicMock(return_value="E")

        self.napp.execute_swap_to_standby([evc])

        evc.remove_path_flows.assert_not_called()
