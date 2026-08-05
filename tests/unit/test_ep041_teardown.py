# pylint: disable=too-many-lines
"""Tests for EP041, fast convergence for static EVCs: teardown of the kept
configured paths, link and UNI convergence, and the dynamic escape."""
import asyncio
from unittest.mock import MagicMock, patch

import pytest
from kytos.lib.helpers import get_controller_mock, get_test_client
from kytos.core.common import EntityStatus
from kytos.core.events import KytosEvent
from napps.kytos.mef_eline.models import EVC, Path
from napps.kytos.mef_eline.tests.helpers import (
    get_link_mocked,
    get_uni_mocked,
)


# pylint: disable=too-many-public-methods
class TestEP041Teardown:
    """EP041 static EVCs convergence and teardown."""

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
        """Updating the standby path of an inactive dual static EVC still
        holding its flows sweeps the old standby, once the update is
        stored (EP041)."""
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
        evc._validate_static_paths = MagicMock()
        evc._get_unis_use_tags = MagicMock(return_value=(evc.uni_a, evc.uni_z))
        old_backup = evc.backup_path
        parent = MagicMock()
        evc.sync = parent.sync
        evc.remove_path_flows = parent.remove_path_flows

        new_backup = Path([get_link_mocked(endpoint_a_port=15,
                                           endpoint_b_port=16,
                                           metadata={"s_vlan": 7})])
        evc.update(backup_path=new_backup)

        assert not evc.is_active()
        evc.remove_path_flows.assert_called_once_with(old_backup)
        names = [c[0] for c in parent.method_calls]
        assert names == ["sync", "remove_path_flows"]

    @patch("napps.kytos.mef_eline.models.path.Path.is_valid")
    def test_update_rejected_keeps_standby(self, _is_valid_mock):
        """A PATCH rejected by a UNI tag conflict leaves the kept standby
        installed: the sweep only runs once nothing can reject it (EP041)."""
        # pylint: disable=import-outside-toplevel
        from kytos.core.exceptions import KytosTagError
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
        evc._validate_static_paths = MagicMock()
        evc._get_unis_use_tags = MagicMock(side_effect=KytosTagError("x"))
        evc.remove_path_flows = MagicMock()

        new_backup = Path([get_link_mocked(endpoint_a_port=15,
                                           endpoint_b_port=16)])
        with pytest.raises(KytosTagError):
            evc.update(backup_path=new_backup)
        evc.remove_path_flows.assert_not_called()

        # storing it can still reject it, nothing swept then either
        # pylint: disable=import-outside-toplevel
        from pydantic import ValidationError
        evc._get_unis_use_tags = MagicMock(return_value=(evc.uni_a, evc.uni_z))
        evc.sync = MagicMock(
            side_effect=ValidationError.from_exception_data("EVC", [])
        )
        with pytest.raises(ValidationError):
            evc.update(backup_path=new_backup)
        evc.remove_path_flows.assert_not_called()

    @patch("napps.kytos.mef_eline.models.path.Path.is_valid")
    def test_update_backup_on_dynamic_escape_sweeps_standbys(
        self, _is_valid_mock
    ):
        """A dual static + dynamic EVC on a dynamic escape keeps both statics
        installed, so both are standbys: updating only backup_path sweeps
        both (EP041)."""
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
        evc._validate_static_paths = MagicMock()
        evc._get_unis_use_tags = MagicMock(return_value=(evc.uni_a, evc.uni_z))
        old_primary, old_backup = evc.primary_path, evc.backup_path
        evc.sync = MagicMock()
        evc.remove_path_flows = MagicMock()

        new_backup = Path([get_link_mocked(endpoint_a_port=15,
                                           endpoint_b_port=16,
                                           metadata={"s_vlan": 7})])
        evc.update(backup_path=new_backup)

        assert evc.remove_path_flows.call_count == 2
        swept = [c[0][0] for c in evc.remove_path_flows.call_args_list]
        assert swept[0] is old_primary and swept[1] is old_backup

    @staticmethod
    def _static_evc(evc_id="1", **attrs):
        """A static EVC mock with the defaults classify_static_link_down
        reads: forwarding path hit, nothing usable (EP041)."""
        evc = MagicMock(id=evc_id)
        evc.keeps_static_paths.return_value = True
        evc.is_affected_by_link.return_value = True
        evc.failover_path = Path([])
        evc.get_static_standby_path.return_value = Path([])
        evc.has_single_static_dynamic_path.return_value = False
        evc.dynamic_backup_path = False
        for attr, value in attrs.items():
            setattr(evc, attr, value)
        return evc

    def test_standby_link_down_left_alone(self):
        """A dual static EVC forwarding on one path whose standby's link goes
        down is left alone, its flows untouched: it is only stored, so its
        stored link status follows. An EVC not using the link isn't
        (EP041)."""
        link = MagicMock()
        evc = self._static_evc("1")
        evc.is_affected_by_link.return_value = False  # not on the current path
        evc.is_static_path_affected_by_link.return_value = True
        unrelated = self._static_evc("2")
        unrelated.is_affected_by_link.return_value = False
        unrelated.is_static_path_affected_by_link.return_value = False
        self.napp.get_evcs_by_svc_level = MagicMock(
            return_value=[evc, unrelated]
        )
        self.napp.mongo_controller = MagicMock()

        self.napp.handle_link_down(KytosEvent(content={"link": link}))

        self.napp.mongo_controller.update_evcs.assert_called_once_with(
            [evc.as_dict()]
        )
        evc.remove_static_standby_flows.assert_not_called()
        evc.deactivate.assert_not_called()

    def test_single_static_link_down_removes_ingress(self):
        """A single static EVC (lone primary) on link_down drops only its UNI
        ingress and keeps egress/NNI, instead of undeploying (EP041)."""
        link = MagicMock()
        # lone primary: no standby, no dynamic escape
        evc = self._static_evc()
        self.napp.get_evcs_by_svc_level = MagicMock(return_value=[evc])
        self.napp.execute_remove_ingress = MagicMock(return_value=([evc], []))
        self.napp.execute_undeploy = MagicMock(return_value=([], []))
        self.napp.mongo_controller = MagicMock()

        self.napp.handle_link_down(KytosEvent(content={"link": link}))

        self.napp.execute_remove_ingress.assert_called_once_with([evc])
        self.napp.execute_undeploy.assert_not_called()

    def test_dual_dynamic_on_escape_swaps_to_recovered_backup(self):
        """On an escape with a down primary but a recovered backup, the EVC
        swaps onto that kept-installed backup instead of hunting another
        dynamic or removing the ingress (EP041)."""
        link = MagicMock()
        standby_up = MagicMock(status=EntityStatus.UP)
        standby_up.is_affected_by_link.return_value = False
        evc = MagicMock(id="1")
        evc.has_dual_static_paths.return_value = True
        evc.dynamic_backup_path = True          # dual + dynamic
        evc.is_affected_by_link.return_value = True   # the escape went down
        evc.is_active.return_value = True
        evc.get_static_standby_path.return_value = standby_up
        self.napp.get_evcs_by_svc_level = MagicMock(return_value=[evc])
        self.napp.execute_swap_to_standby = MagicMock(
            return_value=([evc], [])
        )
        self.napp.execute_dyn_escape = MagicMock(return_value=([], []))
        self.napp.execute_remove_ingress = MagicMock(return_value=([], []))
        self.napp.execute_undeploy = MagicMock(return_value=([], []))
        self.napp.mongo_controller = MagicMock()

        self.napp.handle_link_down(KytosEvent(content={"link": link}))

        self.napp.execute_swap_to_standby.assert_called_once_with([evc])
        self.napp.execute_dyn_escape.assert_not_called()
        self.napp.execute_remove_ingress.assert_not_called()
        self.napp.execute_undeploy.assert_not_called()

    def test_dual_dynamic_link_down_tries_dyn_escape(self):
        """dual + dynamic on a double failure routes to the dynamic escape
        (execute_dyn_escape), keeping both statics installed, instead
        of only removing the ingress like a plain dual EVC (EP041)."""
        link = MagicMock()
        standby_down = MagicMock(status=EntityStatus.DOWN)
        evc = self._static_evc(dynamic_backup_path=True)  # dual + dynamic
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
        """On a dynamic path with no usable failover: the ingress installed on
        the dynamic is removed in one batch, current_path goes to the kept
        static, the dynamic is cleared afterwards, and the escape is
        scheduled, never computed under the link event's locks (EP041)."""
        prep_del_mock.side_effect = lambda f: {"1": ["del"]} if f else {}
        primary, dynamic = MagicMock(id="P"), MagicMock(id="D")
        evc = MagicMock(id="1")
        evc.primary_path = primary
        evc.current_path = dynamic
        evc.failover_path = Path([])
        evc._prepare_uni_flows.return_value = {"1": ["ingress"]}
        evc.get_installed_static_path.return_value = primary
        calls = []
        send_mock.side_effect = lambda *args: calls.append("ingress")
        self.napp.execute_clear_paths = MagicMock(
            side_effect=lambda items: calls.append(("clear", items))
        )

        scheduled, failed = self.napp.execute_dyn_escape([evc])

        assert scheduled == [evc]
        assert not failed
        send_mock.assert_called_once_with({"1": ["del"]}, "delete")
        evc._prepare_uni_flows.assert_called_once_with(dynamic, skip_out=True)
        evc.setup_failover_path.assert_not_called()
        evc.remove_path_flows.assert_not_called()
        assert evc.current_path is primary
        evc.deactivate.assert_called_with()
        evc.request_dyn_escape.assert_called_once_with()
        assert calls == ["ingress", ("clear", [(evc, dynamic)])]

    @patch("napps.kytos.mef_eline.main.send_flow_mods_http")
    @patch("napps.kytos.mef_eline.main.prepare_delete_flow")
    def test_execute_dyn_escape_on_primary_keeps_primary(
        self, prep_del_mock, _send_mock
    ):
        """On primary with a down failover: drop the ingress, clear the
        failover, keep primary (EP041)."""
        prep_del_mock.side_effect = lambda f: {"1": ["del"]} if f else {}
        primary, down = MagicMock(id="P"), MagicMock(id="D")
        evc = MagicMock(id="1")
        evc.primary_path = primary
        evc.current_path = primary
        evc.failover_path = down
        evc._prepare_uni_flows.return_value = {"1": ["ingress"]}
        evc.get_installed_static_path.return_value = primary
        self.napp.execute_clear_paths = MagicMock()

        scheduled, _ = self.napp.execute_dyn_escape([evc])

        assert scheduled == [evc]
        evc._prepare_uni_flows.assert_called_once_with(primary, skip_out=True)
        evc.remove_path_flows.assert_not_called()
        assert evc.current_path is primary
        assert not evc.failover_path
        self.napp.execute_clear_paths.assert_called_once_with([(evc, down)])

    @patch("napps.kytos.mef_eline.main.send_flow_mods_http")
    @patch("napps.kytos.mef_eline.main.prepare_delete_flow")
    def test_execute_dyn_escape_ingress_removal_fails(
        self, prep_del_mock, send_mock
    ):
        """If the ingress can't be removed nothing is detached or scheduled,
        the EVC is left for the undeploy fallback (EP041)."""
        # pylint: disable=import-outside-toplevel
        from napps.kytos.mef_eline.exceptions import FlowModException
        prep_del_mock.side_effect = lambda f: {"1": ["del"]} if f else {}
        send_mock.side_effect = FlowModException("err")
        primary, dynamic = MagicMock(id="P"), MagicMock(id="D")
        evc = MagicMock(id="1")
        evc.primary_path = primary
        evc.current_path = dynamic
        evc.failover_path = Path([])
        evc._prepare_uni_flows.return_value = {"1": ["ingress"]}

        scheduled, failed = self.napp.execute_dyn_escape([evc])

        assert not scheduled
        assert failed == [evc]
        assert evc.current_path is dynamic
        evc.request_dyn_escape.assert_not_called()

    def test_execute_dyn_escape_nothing_installed_redeploys(self):
        """With no configured path installed there is nothing to keep, so the
        EVC goes to the undeploy/redeploy fallback (EP041)."""
        evc = MagicMock(id="1")
        evc.is_active.return_value = False
        evc.current_path = Path([])
        evc.get_installed_static_path.return_value = Path([])

        scheduled, failed = self.napp.execute_dyn_escape([evc])

        assert not scheduled
        assert failed == [evc]
        evc.request_dyn_escape.assert_not_called()

    def _escape_evc(self, fresh=None):
        """A down EVC with its ingress removed on primary."""
        primary = MagicMock(id="P")
        evc = MagicMock(id="1")
        evc.primary_path = primary
        evc.current_path = primary
        evc.failover_path = Path([])

        def _setup(**kwargs):
            assert kwargs["reference_path"] is primary
            if fresh:
                evc.failover_path = fresh
            return bool(fresh)
        evc.setup_failover_path.side_effect = _setup
        return evc

    def test_handle_evc_need_dyn_escape(self):
        """The escape runs holding only the EVC lock, and only while still
        eligible (EP041)."""
        evc = MagicMock(id="1", archived=False)
        self.napp.circuits = {"1": evc}
        self.napp.escape_to_dynamic = MagicMock()
        event = KytosEvent(content={"evc_id": "1"})

        evc.is_eligible_for_dyn_failover_recovery.return_value = True
        self.napp.handle_evc_need_dyn_escape(event)
        self.napp.escape_to_dynamic.assert_called_once_with(evc)
        evc.lock.__enter__.assert_called_once()

        # a failed escape leaves it down on its kept configured paths
        self.napp.escape_to_dynamic.return_value = False
        self.napp.handle_evc_need_dyn_escape(event)
        evc.deploy.assert_not_called()
        evc.remove.assert_not_called()

        # a configured path recovered or it was handled meanwhile
        self.napp.escape_to_dynamic.reset_mock()
        evc.is_eligible_for_dyn_failover_recovery.return_value = False
        self.napp.handle_evc_need_dyn_escape(event)
        self.napp.escape_to_dynamic.assert_not_called()

        self.napp.circuits = {}
        self.napp.handle_evc_need_dyn_escape(event)
        self.napp.escape_to_dynamic.assert_not_called()

    def test_escape_to_dynamic_swaps_onto_fresh(self):
        """A fresh dynamic disjoint from primary is swapped onto and the EVC
        activated, primary kept installed (EP041)."""
        fresh = MagicMock(id="F", status=EntityStatus.UP)
        evc = self._escape_evc(fresh)

        def _swap(evcs, activate=False):
            assert activate is True
            evcs[0].current_path, evcs[0].failover_path = (
                fresh, evcs[0].current_path
            )
            return evcs, []
        self.napp.execute_swap_to_failover = MagicMock(side_effect=_swap)
        self.napp.execute_clear_paths = MagicMock()

        assert self.napp.escape_to_dynamic(evc) is True
        assert evc.current_path is fresh
        assert not evc.failover_path
        # activated by the swap, before its event is built
        evc.try_to_activate.assert_not_called()
        evc.remove_path_flows.assert_not_called()
        self.napp.execute_clear_paths.assert_not_called()
        evc.sync.assert_called_once_with()

    def test_escape_to_dynamic_no_fresh(self):
        """No fresh dynamic: the EVC stays down on its kept static (EP041)."""
        evc = self._escape_evc()
        self.napp.execute_swap_to_failover = MagicMock()
        self.napp.execute_clear_paths = MagicMock()

        assert self.napp.escape_to_dynamic(evc) is False
        self.napp.execute_swap_to_failover.assert_not_called()
        self.napp.execute_clear_paths.assert_not_called()
        evc.try_to_activate.assert_not_called()

    def test_escape_to_dynamic_failed_swap_removes_ingress_first(self):
        """A failed swap may have partially installed the fresh ingress: it is
        removed before the fresh path is cleared (EP041)."""
        fresh = MagicMock(id="F", status=EntityStatus.UP)
        evc = self._escape_evc(fresh)
        calls = []
        self.napp.execute_swap_to_failover = MagicMock(return_value=([], []))
        self.napp.execute_remove_ingress = MagicMock(
            side_effect=lambda evcs: calls.append("ingress") or (evcs, [])
        )
        self.napp.execute_clear_paths = MagicMock(
            side_effect=lambda items: calls.append(("clear", items))
        )

        assert self.napp.escape_to_dynamic(evc) is False
        assert calls == ["ingress", ("clear", [(evc, fresh)])]
        assert not evc.failover_path

        # cleared even if that ingress removal fails too
        evc = self._escape_evc(fresh)
        self.napp.execute_remove_ingress = MagicMock(return_value=([], [evc]))
        self.napp.execute_clear_paths.reset_mock()
        assert self.napp.escape_to_dynamic(evc) is False
        self.napp.execute_clear_paths.assert_called_once_with([(evc, fresh)])
        assert not evc.failover_path

    def test_escape_to_dynamic_clears_old_dynamic(self):
        """Escaping off a down dynamic current_path clears it once the
        ingress was swapped away from it (EP041)."""
        fresh = MagicMock(id="F", status=EntityStatus.UP)
        evc = self._escape_evc(fresh)
        down = MagicMock(id="D")
        evc.current_path = down

        def _swap(evcs, activate=False):
            assert activate is True
            evcs[0].current_path, evcs[0].failover_path = (
                fresh, evcs[0].current_path
            )
            return evcs, []
        self.napp.execute_swap_to_failover = MagicMock(side_effect=_swap)
        self.napp.execute_clear_paths = MagicMock()

        assert self.napp.escape_to_dynamic(evc) is True
        self.napp.execute_clear_paths.assert_called_once_with([(evc, down)])
        assert evc.current_path is fresh

    def test_escape_to_dynamic_rejects_path_equal_to_static(self):
        """A fresh path over a configured path's links would be mistaken for
        it, so it's cleared unused (EP041)."""
        fresh = MagicMock(id="F", status=EntityStatus.UP)
        evc = self._escape_evc(fresh)
        evc.backup_path = Path([MagicMock()])
        fresh.__eq__ = lambda self, other: other is evc.backup_path
        self.napp.execute_swap_to_failover = MagicMock()
        self.napp.execute_clear_paths = MagicMock()

        assert self.napp.escape_to_dynamic(evc) is False
        self.napp.execute_swap_to_failover.assert_not_called()
        self.napp.execute_clear_paths.assert_called_once_with([(evc, fresh)])

    def test_link_up_routes_dyn_recovery(self):
        """A down static EVC with a dynamic escape is scheduled for it off the
        link_up locks, never the redeploy ladder that would break-before-make
        its configured paths (EP041)."""
        link = MagicMock(id="l")
        evc = MagicMock(id="1")
        evc.is_enabled.return_value = True
        evc.archived = False
        evc.is_eligible_for_static_revert.return_value = False
        evc.is_eligible_for_static_resume.return_value = False
        evc.is_eligible_for_dyn_failover_recovery.return_value = True

        self.napp.get_evcs_by_svc_level = MagicMock(return_value=[evc])
        self.napp.execute_dyn_escape = MagicMock()
        self.napp.execute_swap_to_standby = MagicMock(return_value=([], []))
        self.napp.mongo_controller = MagicMock()

        self.napp.handle_link_up(KytosEvent(content={"link": link}))

        evc.request_dyn_escape.assert_called_once_with()
        self.napp.execute_dyn_escape.assert_not_called()
        evc.handle_link_up.assert_not_called()

    def test_link_up_stores_evcs_left_as_is(self):
        """An EVC left as is by a link_up on one of its configured paths,
        e.g. on an escape while its backup recovers, is stored so its stored
        link status follows. An EVC not using the link isn't (EP041)."""
        link = MagicMock(id="l")

        def make(evc_id, on_link):
            evc = MagicMock(id=evc_id, archived=False)
            evc.is_eligible_for_static_revert.return_value = False
            evc.is_eligible_for_static_resume.return_value = False
            evc.is_eligible_for_dyn_failover_recovery.return_value = False
            evc.has_dual_static_paths.return_value = False
            evc.is_static_path_affected_by_link.return_value = on_link
            return evc
        on_escape, unrelated = make("1", True), make("2", False)
        self.napp.get_evcs_by_svc_level = MagicMock(
            return_value=[on_escape, unrelated]
        )
        self.napp.mongo_controller = MagicMock()

        self.napp.handle_link_up(KytosEvent(content={"link": link}))

        self.napp.mongo_controller.update_evcs.assert_called_once_with(
            [on_escape.as_dict()]
        )
        on_escape.handle_link_up.assert_called_once_with(link)
        unrelated.handle_link_up.assert_called_once_with(link)

    @patch("napps.kytos.mef_eline.main.emit_event")
    @patch("napps.kytos.mef_eline.main.send_flow_mods_http")
    def test_swap_to_standby_ensures_standby_installed(self, _send, _emit):
        """The swap ensures the standby is installed, in one batch for every
        EVC (a no-op when kept, a cold install when it never was, e.g. a
        pre-EP041 EVC) before moving the ingress onto it (EP041)."""
        evc = MagicMock(id="1")
        evc.get_static_standby_path.return_value = MagicMock()
        evc._prepare_uni_flows.return_value = {"1": ["Ingress"]}
        self.napp.prepare_swap_to_failover_event = {evc: "E"}.get
        self.napp.execute_install_standby = MagicMock(return_value=([evc], []))

        self.napp.execute_clear_paths = MagicMock()
        self.napp.execute_swap_to_standby([evc])

        standby = evc.get_static_standby_path.return_value
        self.napp.execute_install_standby.assert_called_once_with(
            [(evc, standby)]
        )
        # the ingress targets that same standby
        evc._prepare_uni_flows.assert_called_once_with(
            standby, skip_out=True
        )

    @patch("napps.kytos.mef_eline.main.emit_event")
    @patch("napps.kytos.mef_eline.main.send_flow_mods_http")
    def test_swap_to_standby_skips_when_cold_install_fails(self, _send, _emit):
        """A failed standby cold install (disconnected switch, VLAN exhaustion)
        must not swap the ingress onto a path with no egress/NNI: the EVC is
        left un-swapped for the undeploy/redeploy fallback (EP041)."""
        self.napp.execute_install_standby = MagicMock(
            side_effect=lambda items: ([], [evc for evc, _ in items])
        )
        evc = MagicMock(id="1")
        evc.get_static_standby_path.return_value = MagicMock()

        swapped, not_swapped = self.napp.execute_swap_to_standby([evc])

        assert swapped == []
        assert not_swapped == [evc]
        evc._prepare_uni_flows.assert_not_called()

    @patch("napps.kytos.mef_eline.main.emit_event")
    @patch("napps.kytos.mef_eline.main.send_flow_mods_http")
    def test_swap_to_standby_clears_old_dynamic(self, _send, _emit):
        """Swapping off a dynamic path clears it once the ingress moved away,
        in one batch, while an old configured path is kept as the standby
        (EP041)."""
        self.napp.execute_install_standby = MagicMock(
            side_effect=lambda items: ([evc for evc, _ in items], [])
        )
        self.napp.prepare_swap_to_failover_event = MagicMock(return_value="E")
        self.napp.execute_clear_paths = MagicMock()
        primary, backup, escape = (
            MagicMock(id="P"), MagicMock(id="B"), MagicMock(id="D")
        )
        evc = MagicMock(id="1", execution_rounds=3)
        evc.primary_path, evc.backup_path = primary, backup
        evc.current_path, evc.failover_path = escape, Path([])
        evc.has_single_static_dynamic_path.return_value = False
        evc.get_static_standby_path.return_value = primary
        evc._prepare_uni_flows.return_value = {"1": ["Ingress"]}

        self.napp.execute_swap_to_standby([evc])

        assert evc.current_path is primary
        assert evc.execution_rounds == 0
        evc.remove_path_flows.assert_not_called()
        self.napp.execute_clear_paths.assert_called_once_with([(evc, escape)])

        # from a configured path: kept as the new standby
        self.napp.execute_clear_paths.reset_mock()
        evc.current_path = backup
        self.napp.execute_swap_to_standby([evc])
        self.napp.execute_clear_paths.assert_not_called()

    @patch("napps.kytos.mef_eline.main.emit_event")
    @patch("napps.kytos.mef_eline.main.send_flow_mods_http")
    def test_swap_to_standby_single_static_dyn_old_dynamic(self, _send, _emit):
        """A single static + dynamic EVC swapping back to primary keeps its
        old dynamic as its failover while UP and disjoint from primary,
        else clears it (EP041)."""
        self.napp.execute_install_standby = MagicMock(
            side_effect=lambda items: ([evc for evc, _ in items], [])
        )
        self.napp.prepare_swap_to_failover_event = MagicMock(return_value="E")
        self.napp.execute_clear_paths = MagicMock()
        primary, dynamic = MagicMock(id="P"), MagicMock(id="D")
        evc = MagicMock(id="1")
        evc.primary_path, evc.backup_path = primary, Path([])
        evc.current_path, evc.failover_path = dynamic, Path([])
        evc.has_single_static_dynamic_path.return_value = True
        evc.get_static_standby_path.return_value = primary
        evc._prepare_uni_flows.return_value = {"1": ["Ingress"]}
        evc.is_failover_reusable_after_revert.return_value = True

        self.napp.execute_swap_to_standby([evc])
        assert evc.current_path is primary
        assert evc.failover_path is dynamic
        self.napp.execute_clear_paths.assert_not_called()

        evc.current_path, evc.failover_path = dynamic, Path([])
        evc.is_failover_reusable_after_revert.return_value = False
        self.napp.execute_swap_to_standby([evc])
        assert not evc.failover_path
        self.napp.execute_clear_paths.assert_called_once_with([(evc, dynamic)])

    @patch("napps.kytos.mef_eline.main.emit_event")
    @patch("napps.kytos.mef_eline.main.send_flow_mods_http")
    @patch("napps.kytos.mef_eline.main.prepare_delete_flow")
    def test_execute_clear_paths_batched(self, prep_mock, send_mock, emit):
        """Stale paths are cleared with one batched delete, their VLANs freed
        and failover_old_path emitted with the removed flows (EP041)."""
        prep_mock.side_effect = lambda flows: {"s1": [flows["tag"]]}
        path_a, path_b = MagicMock(id="A"), MagicMock(id="B")
        evc = MagicMock(id="1")
        evc._prepare_uni_flows.side_effect = (
            lambda path, skip_in: {"tag": f"uni-{path.id}"}
        )
        evc._prepare_nni_flows.return_value = {}

        self.napp.execute_clear_paths([(evc, path_a), (evc, path_b)])

        send_mock.assert_called_once_with(
            {"s1": ["uni-A", "uni-B"]}, "delete"
        )
        path_a.make_vlans_available.assert_called_once()
        path_b.make_vlans_available.assert_called_once()
        evc.remove_path_flows.assert_not_called()
        assert emit.call_args[0][1] == "failover_old_path"
        content = emit.call_args[1]["content"]
        assert content["1"]["removed_flows"] == {"s1": ["uni-A", "uni-B"]}

    @patch("napps.kytos.mef_eline.main.emit_event")
    @patch("napps.kytos.mef_eline.main.send_flow_mods_http")
    @patch("napps.kytos.mef_eline.main.prepare_delete_flow")
    def test_execute_clear_paths_frees_vlans_on_failure(
        self, prep_mock, send_mock, emit
    ):
        """A failed batched delete still frees the VLANs, like
        remove_path_flows, as nothing else references a detached path
        (EP041)."""
        # pylint: disable=import-outside-toplevel
        from napps.kytos.mef_eline.exceptions import FlowModException
        prep_mock.return_value = {"s1": ["del"]}
        send_mock.side_effect = FlowModException("err")
        path = MagicMock(id="A")
        evc = MagicMock(id="1")

        self.napp.execute_clear_paths([(evc, path)])

        path.make_vlans_available.assert_called_once()
        emit.assert_not_called()

    @patch("napps.kytos.mef_eline.main.emit_event")
    @patch("napps.kytos.mef_eline.main.send_flow_mods_http")
    def test_execute_install_standby(self, send_mock, emit_mock):
        """Installed paths are a no op, the others are cold installed in one
        batch, a down one fails (EP041)."""
        installed = MagicMock(status=EntityStatus.UP)
        cold = MagicMock(status=EntityStatus.UP)
        cold.is_deployed.return_value = False
        down = MagicMock(status=EntityStatus.DOWN)
        evc1, evc2, evc3 = (MagicMock(id=evc_id) for evc_id in "123")
        evc2._prepare_nni_flows.return_value = {"s1": ["nni"]}
        evc2._prepare_uni_flows.return_value = {"s2": ["egress"]}

        ready, failed = self.napp.execute_install_standby(
            [(evc1, installed), (evc2, cold), (evc3, down)]
        )

        assert ready == [evc1, evc2]
        assert failed == [evc3]
        cold.choose_vlans.assert_called_once()
        installed.choose_vlans.assert_not_called()
        evc2._prepare_uni_flows.assert_called_once_with(cold, skip_in=True)
        send_mock.assert_called_once_with(
            {"s1": ["nni"], "s2": ["egress"]}, "install"
        )
        assert emit_mock.call_args[0][1] == "static.standby_installed"

    @patch("napps.kytos.mef_eline.main.emit_event")
    @patch("napps.kytos.mef_eline.main.send_flow_mods_http")
    def test_execute_install_standby_per_evc_failures(
        self, send_mock, emit_mock
    ):
        """An EVC failing to choose VLANs or to build its flows does not
        abort the batch, and the tags it took are freed (EP041)."""
        # pylint: disable=import-outside-toplevel
        from kytos.core.exceptions import KytosNoTagAvailableError

        def cold_path():
            path = MagicMock(status=EntityStatus.UP)
            path.is_deployed.return_value = False
            return path

        ok_path, no_tag, bad_flows = cold_path(), cold_path(), cold_path()
        no_tag.choose_vlans.side_effect = KytosNoTagAvailableError(MagicMock())
        evc_ok, evc_no_tag, evc_bad = (
            MagicMock(id=evc_id) for evc_id in ("ok", "no_tag", "bad")
        )
        evc_ok._prepare_nni_flows.return_value = {"s1": ["nni"]}
        evc_ok._prepare_uni_flows.return_value = {}
        evc_bad._prepare_nni_flows.side_effect = ValueError("boom")

        ready, failed = self.napp.execute_install_standby([
            (evc_no_tag, no_tag), (evc_bad, bad_flows), (evc_ok, ok_path),
        ])

        assert ready == [evc_ok]
        assert failed == [evc_no_tag, evc_bad]
        # nothing was allocated for the first, the second frees what it took
        no_tag.make_vlans_available.assert_not_called()
        bad_flows.make_vlans_available.assert_called_once()
        send_mock.assert_called_once_with({"s1": ["nni"]}, "install")
        assert emit_mock.call_args[0][1] == "static.standby_installed"

        # nothing installable -> no FlowMods and no event at all
        send_mock.reset_mock()
        emit_mock.reset_mock()
        ready, failed = self.napp.execute_install_standby(
            [(evc_no_tag, no_tag)]
        )
        assert not ready and failed == [evc_no_tag]
        send_mock.assert_not_called()
        emit_mock.assert_not_called()

    @patch("napps.kytos.mef_eline.main.send_flow_mods_http")
    @patch("napps.kytos.mef_eline.main.prepare_delete_flow")
    def test_execute_install_standby_rolls_back(
        self, prep_del_mock, send_mock
    ):
        """A failed batch install is deleted and its VLANs freed, even when
        that delete fails too, like remove_path_flows (EP041)."""
        # pylint: disable=import-outside-toplevel
        from napps.kytos.mef_eline.exceptions import FlowModException
        prep_del_mock.side_effect = lambda flows: flows
        cold = Path([MagicMock()])
        cold.choose_vlans = MagicMock()
        cold.make_vlans_available = MagicMock()
        evc = MagicMock(id="1")
        evc._prepare_nni_flows.return_value = {"s1": ["nni"]}
        evc._prepare_uni_flows.return_value = {}
        with patch.object(Path, "status", EntityStatus.UP), \
                patch.object(Path, "is_deployed", return_value=False):
            send_mock.side_effect = [FlowModException("x"), None]
            ready, failed = self.napp.execute_install_standby([(evc, cold)])
            assert not ready and failed == [evc]
            cold.make_vlans_available.assert_called_once()

            send_mock.side_effect = FlowModException("x")
            cold.make_vlans_available.reset_mock()
            self.napp.execute_install_standby([(evc, cold)])
            cold.make_vlans_available.assert_called_once()

    @patch("napps.kytos.mef_eline.main.emit_event")
    @patch("napps.kytos.mef_eline.main.send_flow_mods_http")
    def test_execute_clear_paths_skips_unprepared(self, send_mock, emit):
        """A path whose delete could not be built still has its VLANs freed,
        like remove_path_flows; the others are cleared in the batch
        (EP041)."""
        good, bad = MagicMock(id="A"), MagicMock(id="B")
        evc = MagicMock(id="1")
        self.napp.prepare_clear_failover_flow = MagicMock(
            side_effect=lambda _evc, path: {"s1": ["del"]}
            if path is good else {}
        )

        self.napp.execute_clear_paths([(evc, good), (evc, bad)])

        send_mock.assert_called_once_with({"s1": ["del"]}, "delete")
        good.make_vlans_available.assert_called_once()
        bad.make_vlans_available.assert_called_once()
        emit.assert_called_once()

    def test_link_down_undeploys_failed_escape(self):
        """A failed dyn_escape falls back to a full teardown, its standby
        swept by the undeploy's batch (EP041)."""
        link = MagicMock()
        standby = MagicMock(status=EntityStatus.UP)
        standby.is_affected_by_link.return_value = False
        escape = MagicMock(id="D")
        swapped = self._static_evc("1", current_path=escape)
        swapped.get_static_standby_path.return_value = standby
        stuck = self._static_evc("2", dynamic_backup_path=True)
        stuck.get_static_standby_path.return_value = MagicMock(
            status=EntityStatus.DOWN
        )

        def _swap(evcs):
            for evc in evcs:
                evc.current_path = standby
            return evcs, []
        self.napp.get_evcs_by_svc_level = MagicMock(
            return_value=[swapped, stuck]
        )
        self.napp.execute_swap_to_standby = MagicMock(side_effect=_swap)
        self.napp.execute_dyn_escape = MagicMock(return_value=([], [stuck]))
        self.napp.execute_clear_paths = MagicMock()
        self.napp.execute_undeploy = MagicMock(return_value=([stuck], []))
        self.napp.mongo_controller = MagicMock()

        self.napp.handle_link_down(KytosEvent(content={"link": link}))

        self.napp.execute_swap_to_standby.assert_called_once_with([swapped])
        # its standby is swept by execute_undeploy's batch
        stuck.remove_static_standby_flows.assert_not_called()
        self.napp.execute_undeploy.assert_called_once_with([stuck])

    @patch("napps.kytos.mef_eline.main.emit_event")
    @patch("napps.kytos.mef_eline.main.send_flow_mods_http")
    def test_resume_on_static_clears_old_dynamic(self, send_mock, _emit):
        """A static EVC resumed off a dynamic current_path gets that dynamic
        cleared once the ingress moved away from it, a configured old
        current_path is kept (EP041)."""
        primary, dynamic = MagicMock(id="P"), MagicMock(id="D")
        evc = MagicMock(id="1")
        evc.primary_path = primary
        evc.current_path = dynamic
        evc.get_reactivation_path.return_value = primary
        evc.has_dual_static_paths.return_value = False
        evc._prepare_uni_flows.return_value = {"1": ["ingress"]}
        self.napp.execute_install_standby = MagicMock(return_value=([evc], []))
        self.napp.execute_clear_paths = MagicMock()
        self.napp.mongo_controller = MagicMock()

        assert self.napp.resume_on_static([evc]) == [evc]
        assert evc.current_path is primary
        send_mock.assert_called_once()
        self.napp.execute_clear_paths.assert_called_once_with(
            [(evc, dynamic)]
        )

        # from a configured path: nothing to clear
        backup = MagicMock(id="B")
        evc.backup_path, evc.current_path = backup, backup
        self.napp.execute_clear_paths.reset_mock()
        self.napp.resume_on_static([evc])
        self.napp.execute_clear_paths.assert_not_called()

    def test_consistency_skips_static_with_nothing_to_carry_it(self):
        """Consistency traces EVCs inactive on their kept configured paths
        like any other, redeploying after WAIT_FOR_OLD_PATH failed traces,
        except one with none UP and no dynamic backup: nothing can carry it
        and a redeploy would only tear down its kept paths (EP041)."""
        def make(evc_id, dynamic, target):
            evc = MagicMock(id=evc_id)
            evc.lock.locked.return_value = False
            evc.is_active.return_value = False
            evc.has_recent_removed_flow.return_value = False
            evc.is_recent_updated.return_value = False
            evc.needs_static_standby.return_value = False
            evc.is_inactive_on_static.return_value = True
            evc.dynamic_backup_path = dynamic
            evc.get_reactivation_path.return_value = target
            evc.execution_rounds = 99
            return evc
        stuck = make("1", False, Path([]))
        recovered = make("2", False, MagicMock())
        with_dynamic = make("3", True, Path([]))
        self.napp.get_evcs_by_svc_level = MagicMock(
            return_value=[stuck, recovered, with_dynamic]
        )
        with patch(
            "napps.kytos.mef_eline.main.EVCDeploy.check_list_traces",
            return_value={},
        ) as traces_mock:
            self.napp.execute_consistency()

        traces_mock.assert_called_once_with([recovered, with_dynamic])
        stuck.deploy.assert_not_called()
        recovered.deploy.assert_called_once_with()
        with_dynamic.deploy.assert_called_once_with()

    def test_consistency_skips_evc_changed_while_traced(self):
        """A link event may change an EVC while it's traced without a lock:
        the result is ignored then, never activating or redeploying a state
        that wasn't traced (EP041)."""
        evc = MagicMock(id="1")
        evc.lock.locked.return_value = False
        evc.is_inactive_on_static.return_value = False
        evc.is_active.return_value = False
        evc.has_recent_removed_flow.return_value = False
        evc.is_recent_updated.return_value = False
        evc.needs_static_standby.return_value = False
        evc.execution_rounds = 99
        self.napp.get_evcs_by_svc_level = MagicMock(return_value=[evc])

        def _trace(evcs):
            evcs[0].current_path = MagicMock()  # changed meanwhile
            return {}
        with patch(
            "napps.kytos.mef_eline.main.EVCDeploy.check_list_traces",
            side_effect=_trace,
        ):
            self.napp.execute_consistency()

        evc.deploy.assert_not_called()
        evc.activate.assert_not_called()
        assert evc.execution_rounds == 99

    def test_link_down_single_static_dyn_swaps_back_to_up_primary(self):
        """A single static + dynamic EVC whose dynamic fails while primary is
        UP swaps back to primary instead of escaping to another dynamic
        (EP041)."""
        link = MagicMock()
        primary = MagicMock(status=EntityStatus.UP)
        primary.is_affected_by_link.return_value = False
        evc = self._static_evc(dynamic_backup_path=True, primary_path=primary)
        evc.has_single_static_dynamic_path.return_value = True
        # on its dynamic, the standby is primary
        evc.get_static_standby_path.return_value = primary
        self.napp.get_evcs_by_svc_level = MagicMock(return_value=[evc])
        self.napp.execute_swap_to_standby = MagicMock(return_value=([evc], []))
        self.napp.execute_dyn_escape = MagicMock(return_value=([], []))
        self.napp.execute_clear_paths = MagicMock()
        self.napp.mongo_controller = MagicMock()

        self.napp.request_failover_path = MagicMock()
        self.napp.handle_link_down(KytosEvent(content={"link": link}))

        self.napp.execute_swap_to_standby.assert_called_once_with([evc])
        self.napp.execute_dyn_escape.assert_not_called()
        self.napp.request_failover_path.assert_called_once_with(evc)

        # primary down too -> dynamic escape
        primary.status = EntityStatus.DOWN
        self.napp.execute_swap_to_standby.reset_mock()
        self.napp.handle_link_down(KytosEvent(content={"link": link}))
        self.napp.execute_swap_to_standby.assert_not_called()
        self.napp.execute_dyn_escape.assert_called_once_with([evc])

    @patch("napps.kytos.mef_eline.main.emit_event")
    @patch("napps.kytos.mef_eline.main.send_flow_mods_http")
    def test_swap_to_standby_activates_inactive(self, _send, _emit):
        """An inactive EVC swapped onto an UP standby forwards again, so it is
        activated when its UNIs are up, and not otherwise (EP041)."""
        self.napp.execute_install_standby = MagicMock(
            side_effect=lambda items: ([evc for evc, _ in items], [])
        )
        evc = MagicMock(id="1")
        evc.is_active.return_value = False
        evc.are_unis_active.return_value = True
        evc._prepare_uni_flows.return_value = {"1": ["In"]}
        self.napp.prepare_swap_to_failover_event = MagicMock(return_value="E")

        self.napp.execute_swap_to_standby([evc])
        evc.try_to_activate.assert_called_once_with()

        evc.try_to_activate.reset_mock()
        evc.are_unis_active.return_value = False
        self.napp.execute_swap_to_standby([evc])
        evc.try_to_activate.assert_not_called()

    @patch("napps.kytos.mef_eline.main.emit_event")
    def test_request_failover_path(self, emit_mock):
        """need_failover is only asked for an active eligible EVC with no
        failover_path (EP041)."""
        evc = MagicMock(id="1")
        evc.is_active.return_value = True
        evc.failover_path = Path([])
        evc.is_eligible_for_failover_path.return_value = True
        self.napp.request_failover_path(evc)
        assert emit_mock.call_args[0][1] == "need_failover"

        emit_mock.reset_mock()
        evc.is_eligible_for_failover_path.return_value = False
        self.napp.request_failover_path(evc)
        emit_mock.assert_not_called()

    def test_need_redeploy_skips_evc_on_kept_statics(self):
        """A stale need_redeploy never redeploys an EVC moved onto its kept
        configured paths meanwhile (EP041)."""
        evc = MagicMock(id="1")
        evc.is_active.return_value = False
        evc.is_inactive_on_static.return_value = True
        self.napp.circuits = {"1": evc}

        self.napp.handle_evc_need_redeploy(
            KytosEvent(content={"evc_id": "1"})
        )
        evc.deploy.assert_not_called()

        evc.is_inactive_on_static.return_value = False
        self.napp.handle_evc_need_redeploy(
            KytosEvent(content={"evc_id": "1"})
        )
        evc.deploy.assert_called_once_with()

    @patch("napps.kytos.mef_eline.main.emit_event")
    @patch("napps.kytos.mef_eline.main.send_flow_mods_http")
    @patch("napps.kytos.mef_eline.main.prepare_delete_flow",
           side_effect=lambda flows: flows)
    def test_execute_undeploy_sweeps_standbys(self, _prep, send_mock, _emit):
        """The kept standbys are swept in the undeploy's single batch, their
        VLANs freed only once deleted (EP041)."""
        # pylint: disable=import-outside-toplevel
        from napps.kytos.mef_eline.exceptions import FlowModException
        standby = MagicMock(id="B")
        evc = MagicMock(id="1")
        evc.get_kept_standby_paths.return_value = [standby]
        evc._prepare_uni_flows.side_effect = (
            lambda path, skip_in: {"s": [f"uni-{getattr(path, 'id', '')}"]}
        )
        evc._prepare_nni_flows.return_value = {}

        undeployed, _ = self.napp.execute_undeploy([evc])

        assert undeployed == [evc]
        send_mock.assert_called_once()
        assert "uni-B" in str(send_mock.call_args)
        standby.make_vlans_available.assert_called_once()

        send_mock.side_effect = FlowModException("x")
        standby.make_vlans_available.reset_mock()
        self.napp.execute_undeploy([evc])
        standby.make_vlans_available.assert_not_called()

    def test_classify_static_link_down(self):
        """The link_down bucket of an EVC keeping its configured paths
        (EP041)."""
        link = MagicMock()
        classify = self.napp.classify_static_link_down

        evc = self._static_evc()
        assert classify(evc, link) == "remove_ingress"
        evc.dynamic_backup_path = True
        assert classify(evc, link) == "dyn_escape"

        # a usable pre-installed failover only for single static + dynamic
        evc = self._static_evc()
        evc.failover_path = MagicMock(status=EntityStatus.UP)
        evc.is_failover_path_affected_by_link.return_value = False
        assert classify(evc, link) == "remove_ingress"
        evc.has_single_static_dynamic_path.return_value = True
        assert classify(evc, link) == "swap_to_failover"

        # a configured standby UP comes first
        standby = MagicMock(status=EntityStatus.UP)
        standby.is_affected_by_link.return_value = False
        evc.get_static_standby_path.return_value = standby
        assert classify(evc, link) == "swap_to_standby"

        # not on the forwarding path
        evc = self._static_evc()
        evc.is_affected_by_link.return_value = False
        assert classify(evc, link) == ""
        evc.failover_path = MagicMock()
        evc.is_failover_path_affected_by_link.return_value = True
        assert classify(evc, link) == "clear_failover"

    def _uni_up_evc(self, evc_id, interface, **attrs):
        """An inactive EVC whose UNIs are both UP again."""
        evc = self._static_evc(evc_id, **attrs)
        evc.is_active.return_value = False
        evc.uni_a.interface = interface
        evc.uni_z.interface = MagicMock(status=EntityStatus.UP)
        interface.status = EntityStatus.UP
        return evc

    def test_interface_link_up_routes_static_evcs(self):
        """A UNI coming up never redeploys an EVC keeping its configured
        paths: it resumes on an UP one (primary preferred), a live
        current_path is just activated, else it stays down asking for a
        dynamic escape. Other EVCs keep the model's handling (EP041)."""
        interface = MagicMock()
        resumable = self._uni_up_evc("1", interface)
        resumable.is_eligible_for_static_resume.return_value = True
        on_live_dyn = self._uni_up_evc("2", interface)
        on_live_dyn.is_eligible_for_static_resume.return_value = False
        on_live_dyn.current_path = MagicMock(status=EntityStatus.UP)
        all_down = self._uni_up_evc("3", interface)
        all_down.is_eligible_for_static_resume.return_value = False
        all_down.current_path = MagicMock(status=EntityStatus.DOWN)
        dynamic = self._uni_up_evc("4", interface)
        dynamic.keeps_static_paths.return_value = False
        dynamic.is_eligible_for_static_resume.return_value = False
        # handled one EVC lock at a time as on master, never under the
        # global lock, which may be held for a while by a redeploy
        dynamic.handle_interface_link_up.side_effect = (
            lambda _intf: self.assert_multi_lock_free()
        )
        self.napp.get_evcs_by_svc_level = MagicMock(
            return_value=[resumable, on_live_dyn, all_down, dynamic]
        )
        self.napp.resume_on_static = MagicMock(return_value=[resumable])

        with patch("napps.kytos.mef_eline.main.emit_event") as emit_mock:
            self.napp.handle_interface_link_up(interface)

        self.napp.resume_on_static.assert_called_once_with([resumable])
        # reported active, as a UNI coming up does on master
        assert emit_mock.call_args[0][1] == "uni_active_updated"
        resumable.handle_interface_link_up.assert_not_called()
        on_live_dyn.handle_interface_link_up.assert_called_once_with(
            interface
        )
        all_down.handle_interface_link_up.assert_not_called()
        all_down.request_dyn_escape.assert_called_once_with()
        dynamic.handle_interface_link_up.assert_called_once_with(interface)

    @patch("napps.kytos.mef_eline.main.send_flow_mods_http")
    def test_resume_on_static(self, send_mock):
        """A resumed EVC starts over its failed rounds and asks for its
        dynamic failover; with nothing installed no ingress is sent (EP041)."""
        target = MagicMock()
        evc = MagicMock(id="1", execution_rounds=3)
        evc.get_reactivation_path.return_value = target
        evc.failover_path = Path([])
        evc._prepare_uni_flows.return_value = {"1": ["ingress"]}
        self.napp.execute_install_standby = MagicMock(return_value=([evc], []))
        self.napp.request_failover_path = MagicMock()
        self.napp.mongo_controller = MagicMock()

        with patch("napps.kytos.mef_eline.main.emit_event"):
            assert self.napp.resume_on_static([evc]) == [evc]

        assert evc.execution_rounds == 0
        self.napp.request_failover_path.assert_called_once_with(evc)

        self.napp.execute_install_standby.return_value = ([], [evc])
        send_mock.reset_mock()
        assert not self.napp.resume_on_static([evc])
        send_mock.assert_not_called()

    def test_install_static_standby(self):
        """A missing standby goes through the batched install and is stored;
        an installed one is a no op (EP041)."""
        evc = MagicMock(id="1")
        standby = MagicMock()
        standby.is_deployed.return_value = False
        evc.get_static_standby_path.return_value = standby
        self.napp.execute_install_standby = MagicMock(return_value=([evc], []))

        assert self.napp.install_static_standby(evc) is True
        self.napp.execute_install_standby.assert_called_once_with(
            [(evc, standby)]
        )
        evc.sync.assert_called_once_with()

        standby.is_deployed.return_value = True
        self.napp.execute_install_standby.reset_mock()
        assert self.napp.install_static_standby(evc) is True
        self.napp.execute_install_standby.assert_not_called()

    def assert_multi_lock_free(self):
        """The global EVC lock isn't held."""
        assert not self.napp.multi_evc_lock.locked()

    def test_interface_link_up_rechecks_under_lock(self):
        """An EVC that changed while waiting for its lock, e.g. it escaped
        onto a dynamic path or its other UNI went down, isn't resumed
        (EP041)."""
        interface = MagicMock()
        evc = self._uni_up_evc("1", interface)
        evc.is_eligible_for_static_resume.return_value = True
        # inactive when checked, active (escaped) once its lock is taken
        evc.is_active.side_effect = [False, False, True]
        self.napp.get_evcs_by_svc_level = MagicMock(return_value=[evc])
        self.napp.resume_on_static = MagicMock(return_value=[])

        self.napp.handle_interface_link_up(interface)

        self.napp.resume_on_static.assert_called_once_with([])

    @patch("napps.kytos.mef_eline.main.emit_event")
    @patch("napps.kytos.mef_eline.main.send_flow_mods_http")
    def test_swap_to_failover_activate(self, _send, emit_mock):
        """Only on request an EVC is activated once swapped, the event built
        afterwards reporting it active; master's default is unchanged
        (EP041)."""
        evc = MagicMock(id="1")
        evc.failover_path = MagicMock()
        states = []
        self.napp.prepare_swap_to_failover_flow = MagicMock(
            return_value={"s1": ["flow"]}
        )
        self.napp.prepare_swap_to_failover_event = MagicMock(
            side_effect=lambda evc, _flows: states.append(
                evc.try_to_activate.called
            ) or "E"
        )

        self.napp.execute_swap_to_failover([evc])
        evc.try_to_activate.assert_not_called()
        assert states == [False]

        states.clear()
        self.napp.execute_swap_to_failover([evc], activate=True)
        evc.try_to_activate.assert_called_once_with()
        # built again after activating
        assert states == [False, True]
        assert emit_mock.call_args[0][1] == "failover_link_down"

    @patch("napps.kytos.mef_eline.main.emit_event")
    @patch("napps.kytos.mef_eline.main.send_flow_mods_http")
    def test_swap_to_standby_event_after_activation(self, _send, emit_mock):
        """static.ingress_swapped is built once the EVC is repointed and
        activated, so consumers see it forwarding (EP041)."""
        evc = MagicMock(id="1")
        evc.is_active.return_value = False
        evc.are_unis_active.return_value = True
        evc.failover_path = Path([])
        evc._prepare_uni_flows.return_value = {"1": ["In"]}
        self.napp.execute_install_standby = MagicMock(return_value=([evc], []))
        self.napp.prepare_swap_to_failover_event = MagicMock(
            side_effect=lambda evc, _flows: evc.try_to_activate.called
        )

        self.napp.execute_swap_to_standby([evc])

        assert emit_mock.call_args[0][1] == "static.ingress_swapped"
        assert emit_mock.call_args[1]["content"] == {"1": True}

    def test_consistency_path_down_after_trace(self):
        """A trace that passed doesn't activate an EVC whose path went down
        since, left to the next round; a failed trace still counts toward the
        redeploy, as on master (EP041)."""
        def make(evc_id, rounds):
            evc = MagicMock(id=evc_id)
            evc.lock.locked.return_value = False
            evc.is_inactive_on_static.return_value = False
            evc.is_active.return_value = False
            evc.has_recent_removed_flow.return_value = False
            evc.is_recent_updated.return_value = False
            evc.needs_static_standby.return_value = False
            evc.current_path.status = EntityStatus.DOWN
            evc.execution_rounds = rounds
            return evc
        traced_ok, trace_failed = make("1", 0), make("2", 99)
        self.napp.get_evcs_by_svc_level = MagicMock(
            return_value=[traced_ok, trace_failed]
        )
        with patch(
            "napps.kytos.mef_eline.main.EVCDeploy.check_list_traces",
            return_value={"1": True, "2": False},
        ):
            self.napp.execute_consistency()

        traced_ok.activate.assert_not_called()
        assert traced_ok.execution_rounds == 0
        trace_failed.deploy.assert_called_once_with()
