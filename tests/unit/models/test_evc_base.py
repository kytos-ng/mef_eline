"""Module to test the EVCBase class."""
import sys
from unittest.mock import MagicMock, patch, call
from kytos.core.exceptions import KytosTagError
from kytos.core.interface import TAGRange
from napps.kytos.mef_eline.models import Path
import pytest
# pylint: disable=wrong-import-position
sys.path.insert(0, "/var/lib/kytos/napps/..")
# pylint: enable=wrong-import-position, disable=ungrouped-imports
from napps.kytos.mef_eline.models import EVC  # NOQA  pycodestyle
from napps.kytos.mef_eline.scheduler import (
    CircuitSchedule,
)  # NOQA  pycodestyle
from napps.kytos.mef_eline.tests.helpers import (
    get_uni_mocked,
    get_controller_mock,
)  # NOQA  pycodestyle


class TestEVC():  # pylint: disable=too-many-public-methods, no-member
    """Tests to verify EVC class."""

    def test_attributes_empty(self):
        """Test if the EVC raises an error with name is required."""
        attributes = {"controller": get_controller_mock()}
        error_message = "name is required."
        with pytest.raises(ValueError) as handle_error:
            EVC(**attributes)
        assert error_message in str(handle_error)

    def test_expected_requiring_redeploy_attributes(self) -> None:
        """Test expected attributes_requiring_redeploy."""
        expected = [
            "primary_path",
            "backup_path",
            "dynamic_backup_path",
            "queue_id",
            "sb_priority",
            "primary_constraints",
            "secondary_constraints",
            "uni_a",
            "uni_z",
        ]
        assert EVC.attributes_requiring_redeploy == expected

    def test_expeted_read_only_attributes(self) -> None:
        """Test expected read_only_attributes."""
        expected = [
            "creation_time",
            "active",
            "current_path",
            "failover_path",
            "_id",
            "archived",
        ]
        assert EVC.read_only_attributes == expected

    def test_without_uni_a(self):
        """Test if the EVC raises and error with UNI A is required."""
        attributes = {
            "controller": get_controller_mock(),
            "name": "circuit_name",
        }
        error_message = "uni_a is required."
        with pytest.raises(ValueError) as handle_error:
            EVC(**attributes)
        assert error_message in str(handle_error)

    def test_without_uni_z(self):
        """Test if the EVC raises and error with UNI Z is required."""
        attributes = {
            "controller": get_controller_mock(),
            "name": "circuit_name",
            "uni_a": get_uni_mocked(is_valid=True),
        }
        error_message = "uni_z is required."
        with pytest.raises(ValueError) as handle_error:
            EVC(**attributes)
        assert error_message in str(handle_error)

    @pytest.mark.parametrize(
        "name,value",
        [
            ("archived", True),
            ("_id", True),
            ("active", True),
            ("current_path", []),
            ("creation_time", "date"),
        ]
    )
    def test_update_read_only(self, name, value):
        """Test if raises an error when trying to update read only attr."""
        attributes = {
            "controller": get_controller_mock(),
            "name": "circuit_name",
            "dynamic_backup_path": True,
            "uni_a": get_uni_mocked(is_valid=True),
            "uni_z": get_uni_mocked(is_valid=True),
        }

        update_dict = {name: value}
        error_message = f"{name} can't be updated."
        with pytest.raises(ValueError) as handle_error:
            evc = EVC(**attributes)
            evc.update(**update_dict)
        assert error_message in str(handle_error)

    def test_update_invalid(self):
        """Test updating with an invalid attr"""
        attributes = {
            "controller": get_controller_mock(),
            "name": "circuit_name",
            "dynamic_backup_path": True,
            "uni_a": get_uni_mocked(is_valid=True),
            "uni_z": get_uni_mocked(is_valid=True),
        }
        evc = EVC(**attributes)
        with pytest.raises(ValueError) as handle_error:
            evc.update(xyz="abc")
        assert (
            'The attribute "xyz" is invalid.'
            in str(handle_error)
        )

    @patch("napps.kytos.mef_eline.models.EVC.sync")
    def test_update_disable(self, _sync_mock):
        """Test if evc is disabled."""
        attributes = {
            "controller": get_controller_mock(),
            "name": "circuit_name",
            "dynamic_backup_path": True,
            "enable": True,
            "uni_a": get_uni_mocked(is_valid=True),
            "uni_z": get_uni_mocked(is_valid=True),
        }
        update_dict = {"enable": False}
        evc = EVC(**attributes)
        evc.update(**update_dict)
        assert evc.is_enabled() is False

    @patch("napps.kytos.mef_eline.models.EVC.sync")
    def test_update_empty_primary_path(self, _sync_mock):
        """Test if an empty primary path can be set."""
        initial_primary_path = Path([MagicMock(id=1), MagicMock(id=2)])
        attributes = {
            "controller": get_controller_mock(),
            "name": "circuit_name",
            "dynamic_backup_path": True,
            "primary_path": initial_primary_path,
            "enable": True,
            "uni_a": get_uni_mocked(is_valid=True),
            "uni_z": get_uni_mocked(is_valid=True),
        }
        update_dict = {"primary_path": Path([])}
        evc = EVC(**attributes)
        assert evc.primary_path == initial_primary_path
        evc.update(**update_dict)
        assert len(evc.primary_path) == 0

    @patch("napps.kytos.mef_eline.models.EVC.sync")
    def test_update_empty_path_non_dynamic_backup(self, _sync_mock):
        """Test if an empty primary path can't be set if dynamic."""
        initial_primary_path = Path([MagicMock(id=1), MagicMock(id=2)])
        attributes = {
            "controller": get_controller_mock(),
            "name": "circuit_name",
            "dynamic_backup_path": False,
            "primary_path": initial_primary_path,
            "enable": True,
            "uni_a": get_uni_mocked(is_valid=True),
            "uni_z": get_uni_mocked(is_valid=True),
        }
        update_dict = {"primary_path": Path([])}
        evc = EVC(**attributes)
        assert evc.primary_path == initial_primary_path
        with pytest.raises(ValueError) as handle_error:
            evc.update(**update_dict)
        assert (
            'The EVC must have a primary path or allow dynamic paths.'
            in str(handle_error)
        )

    @patch("napps.kytos.mef_eline.models.EVC.sync")
    def test_update_empty_backup_path(self, _sync_mock):
        """Test if an empty backup path can be set."""
        initial_backup_path = Path([MagicMock(id=1), MagicMock(id=2)])
        attributes = {
            "controller": get_controller_mock(),
            "name": "circuit_name",
            "dynamic_backup_path": True,
            "backup_path": initial_backup_path,
            "enable": True,
            "uni_a": get_uni_mocked(is_valid=True),
            "uni_z": get_uni_mocked(is_valid=True),
        }
        update_dict = {"backup_path": Path([])}
        evc = EVC(**attributes)
        assert evc.backup_path == initial_backup_path
        evc.update(**update_dict)
        assert len(evc.backup_path) == 0

    @patch("napps.kytos.mef_eline.models.EVC.sync")
    def test_update_empty_backup_path_non_dynamic(self, _sync_mock):
        """Test if an empty backup path can be set even if it's non dynamic."""
        initial_backup_path = Path([MagicMock(id=1), MagicMock(id=2)])
        primary_path = Path([MagicMock(id=3), MagicMock(id=4)])
        attributes = {
            "controller": get_controller_mock(),
            "name": "circuit_name",
            "dynamic_backup_path": False,
            "primary_path": primary_path,
            "backup_path": initial_backup_path,
            "enable": True,
            "uni_a": get_uni_mocked(is_valid=True),
            "uni_z": get_uni_mocked(is_valid=True),
        }
        update_dict = {"backup_path": Path([])}
        evc = EVC(**attributes)
        assert evc.primary_path == primary_path
        assert evc.backup_path == initial_backup_path
        evc.update(**update_dict)
        assert evc.primary_path == primary_path
        assert len(evc.backup_path) == 0

    @patch("napps.kytos.mef_eline.models.EVC.sync")
    def test_update_queue(self, _sync_mock):
        """Test if evc is set to redeploy."""
        attributes = {
            "controller": get_controller_mock(),
            "name": "circuit_name",
            "enable": True,
            "dynamic_backup_path": True,
            "uni_a": get_uni_mocked(is_valid=True),
            "uni_z": get_uni_mocked(is_valid=True),
        }
        update_dict = {"queue_id": 3}
        evc = EVC(**attributes)
        _, redeploy = evc.update(**update_dict)
        assert redeploy

    @patch("napps.kytos.mef_eline.models.EVC.sync")
    def test_update_queue_null(self, _sync_mock):
        """Test if evc is set to redeploy."""
        attributes = {
            "controller": get_controller_mock(),
            "name": "circuit_name",
            "enable": True,
            "dynamic_backup_path": True,
            "uni_a": get_uni_mocked(is_valid=True),
            "uni_z": get_uni_mocked(is_valid=True),
        }
        update_dict = {"queue_id": None}
        evc = EVC(**attributes)
        _, redeploy = evc.update(**update_dict)
        assert redeploy

    def test_update_different_tag_lists(self):
        """Test update when tag lists are different."""
        attributes = {
            "controller": get_controller_mock(),
            "name": "circuit_name",
            "enable": True,
            "dynamic_backup_path": True,
            "uni_a": get_uni_mocked(is_valid=True),
            "uni_z": get_uni_mocked(is_valid=True),
        }
        uni = MagicMock(user_tag=TAGRange("vlan", [[1, 10]]))
        update_dict = {"uni_a": uni}
        evc = EVC(**attributes)
        with pytest.raises(ValueError):
            evc.update(**update_dict)

    def test_circuit_representation(self):
        """Test the method __repr__."""
        attributes = {
            "controller": get_controller_mock(),
            "name": "circuit_name",
            "uni_a": get_uni_mocked(is_valid=True),
            "uni_z": get_uni_mocked(is_valid=True),
        }
        evc = EVC(**attributes)
        expected_value = f"EVC({evc.id}, {evc.name})"
        assert str(evc) == expected_value

    def test_comparison_method(self):
        """Test the method __eq__."""
        attributes = {
            "controller": get_controller_mock(),
            "name": "circuit_name",
            "uni_a": get_uni_mocked(is_valid=True),
            "uni_z": get_uni_mocked(is_valid=True),
        }
        evc1 = EVC(**attributes)
        evc2 = EVC(**attributes)

        attributes = {
            "controller": get_controller_mock(),
            "name": "circuit_name_2",
            "uni_a": get_uni_mocked(is_valid=True),
            "uni_z": get_uni_mocked(is_valid=True),
        }
        evc3 = EVC(**attributes)
        evc4 = EVC(**attributes)

        assert evc1 == evc2
        assert evc1 != evc3
        assert evc2 != evc3
        assert evc3 == evc4

    def test_as_dict(self):
        """Test the method as_dict."""
        attributes = {
            "controller": get_controller_mock(),
            "id": "custom_id",
            "name": "custom_name",
            "uni_a": get_uni_mocked(is_valid=True),
            "uni_z": get_uni_mocked(is_valid=True),
            "start_date": "2018-08-21T18:44:54",
            "end_date": "2018-08-21T18:44:55",
            "primary_links": [],
            "request_time": "2018-08-21T19:10:41",
            "creation_time": "2018-08-21T18:44:54",
            "owner": "my_name",
            "circuit_scheduler": [
                CircuitSchedule.from_dict(
                    {
                        "id": 234243247,
                        "action": "create",
                        "frequency": "1 * * * *",
                    }
                ),
                CircuitSchedule.from_dict(
                    {
                        "id": 234243239,
                        "action": "create",
                        "interval": {"hours": 2},
                    }
                ),
            ],
            "enabled": True,
            "sb_priority": 2,
            "service_level": 7,
        }
        evc = EVC(**attributes)

        expected_dict = {
            "id": "custom_id",
            "name": "custom_name",
            "uni_a": attributes["uni_a"].as_dict(),
            "uni_z": attributes["uni_z"].as_dict(),
            "start_date": "2018-08-21T18:44:54",
            "end_date": "2018-08-21T18:44:55",
            "bandwidth": 0,
            "primary_links": [],
            "backup_links": [],
            "current_path": [],
            "primary_path": [],
            "backup_path": [],
            "dynamic_backup_path": False,
            "request_time": "2018-08-21T19:10:41",
            "creation_time": "2018-08-21T18:44:54",
            "circuit_scheduler": [
                {
                    "id": 234243247,
                    "action": "create",
                    "frequency": "1 * * * *",
                },
                {
                    "id": 234243239,
                    "action": "create",
                    "interval": {"hours": 2},
                },
            ],
            "active": False,
            "enabled": True,
            "sb_priority": 2,
            "service_level": 7,
        }
        actual_dict = evc.as_dict()
        for name, value in expected_dict.items():
            actual = actual_dict.get(name)
            assert value == actual

        # Selected fields
        expected_dict = {
            "enabled": True,
            "uni_z": attributes["uni_z"].as_dict(),
            "circuit_scheduler": [
                {
                    "id": 234243247,
                    "action": "create",
                    "frequency": "1 * * * *",
                },
                {
                    "id": 234243239,
                    "action": "create",
                    "interval": {"hours": 2},
                },
            ],
            "sb_priority": 2,
        }
        selected_fields = {
            "enabled", "uni_z", "circuit_scheduler", "sb_priority"
        }
        actual_dict = evc.as_dict(selected_fields)
        for name, value in expected_dict.items():
            actual = actual_dict.get(name)
            assert value == actual

    @staticmethod
    def test_get_id_from_cookie():
        """Test get_id_from_cookie."""
        attributes = {
            "controller": get_controller_mock(),
            "name": "circuit_name",
            "enable": True,
            "uni_a": get_uni_mocked(is_valid=True),
            "uni_z": get_uni_mocked(is_valid=True)
        }
        evc = EVC(**attributes)
        evc_id = evc.id
        assert evc_id
        assert evc.get_id_from_cookie(evc.get_cookie()) == evc_id

    @staticmethod
    def test_get_id_from_cookie_with_leading_zeros():
        """Test get_id_from_cookie with leading zeros."""

        attributes = {
            "controller": get_controller_mock(),
            "name": "circuit_name",
            "enable": True,
            "uni_a": get_uni_mocked(is_valid=True),
            "uni_z": get_uni_mocked(is_valid=True)
        }
        evc = EVC(**attributes)
        evc_id = "0a2d672d99ff41"
        # pylint: disable=protected-access
        evc._id = evc_id
        # pylint: enable=protected-access
        assert EVC.get_id_from_cookie(evc.get_cookie()) == evc_id

    def test_is_intra_switch(self):
        """Test is_intra_switch method."""
        attributes = {
            "controller": get_controller_mock(),
            "name": "circuit_name",
            "enable": True,
            "uni_a": get_uni_mocked(is_valid=True),
            "uni_z": get_uni_mocked(is_valid=True)
        }
        evc = EVC(**attributes)
        assert not evc.is_intra_switch()

        evc.uni_a.interface.switch = evc.uni_z.interface.switch
        assert evc.is_intra_switch()

    def test_default_queue_id(self):
        """Test default queue_id"""

        attributes = {
            "controller": get_controller_mock(),
            "name": "circuit_1",
            "uni_a": get_uni_mocked(is_valid=True),
            "uni_z": get_uni_mocked(is_valid=True),
            "dynamic_backup_path": True,
        }

        evc = EVC(**attributes)
        assert evc.queue_id == -1

    def test_get_unis_use_tags(self):
        """Test _get_unis_use_tags"""
        old_uni_a = get_uni_mocked(
            interface_port=2,
            is_valid=True
        )
        old_uni_z = get_uni_mocked(
            interface_port=3,
            is_valid=True
        )
        attributes = {
            "controller": get_controller_mock(),
            "name": "circuit_name",
            "enable": True,
            "uni_a": old_uni_a,
            "uni_z": old_uni_z
        }
        evc = EVC(**attributes)
        evc._use_uni_vlan = MagicMock()
        evc.make_uni_vlan_available = MagicMock()
        new_uni_a = get_uni_mocked(tag_value=200, is_valid=True)
        new_uni_z = get_uni_mocked(tag_value=200, is_valid=True)
        unis = {"uni_a": new_uni_a}
        evc._get_unis_use_tags(**unis)
        assert evc._use_uni_vlan.call_count == 1
        assert evc._use_uni_vlan.call_args[0][0] == new_uni_a
        assert evc.make_uni_vlan_available.call_count == 1
        assert evc.make_uni_vlan_available.call_args[0][0] == old_uni_a

        # Two UNIs
        evc = EVC(**attributes)
        evc._use_uni_vlan = MagicMock()
        evc.make_uni_vlan_available = MagicMock()
        unis = {"uni_a": new_uni_a, "uni_z": new_uni_z}
        evc._get_unis_use_tags(**unis)

        expected = [
            call(new_uni_a, uni_dif=old_uni_a),
            call(new_uni_z, uni_dif=old_uni_z)
        ]
        evc._use_uni_vlan.assert_has_calls(expected)
        expected = [
            call(old_uni_z, uni_dif=new_uni_z),
            call(old_uni_a, uni_dif=new_uni_a)
        ]
        evc.make_uni_vlan_available.assert_has_calls(expected)

    def test_get_unis_use_tags_error(self):
        """Test _get_unis_use_tags with KytosTagError"""
        old_uni_a = get_uni_mocked(
            interface_port=2,
            is_valid=True
        )
        old_uni_z = get_uni_mocked(
            interface_port=3,
            is_valid=True
        )
        attributes = {
            "controller": get_controller_mock(),
            "name": "circuit_name",
            "enable": True,
            "uni_a": old_uni_a,
            "uni_z": old_uni_z
        }
        evc = EVC(**attributes)
        evc._use_uni_vlan = MagicMock()

        # UNI Z KytosTagError
        evc._use_uni_vlan.side_effect = [None, KytosTagError("")]
        evc.make_uni_vlan_available = MagicMock()
        new_uni_a = get_uni_mocked(tag_value=200, is_valid=True)
        new_uni_z = get_uni_mocked(tag_value=200, is_valid=True)
        unis = {"uni_a": new_uni_a, "uni_z": new_uni_z}
        with pytest.raises(KytosTagError):
            evc._get_unis_use_tags(**unis)
        expected = [
            call(new_uni_a, uni_dif=old_uni_a),
            call(new_uni_z, uni_dif=old_uni_z)
        ]
        evc._use_uni_vlan.assert_has_calls(expected)
        assert evc.make_uni_vlan_available.call_count == 1
        assert evc.make_uni_vlan_available.call_args[0][0] == new_uni_a

        # UNI A KytosTagError
        evc = EVC(**attributes)
        evc._use_uni_vlan = MagicMock()
        evc._use_uni_vlan.side_effect = [KytosTagError(""), None]
        evc.make_uni_vlan_available = MagicMock()
        new_uni_a = get_uni_mocked(tag_value=200, is_valid=True)
        new_uni_z = get_uni_mocked(tag_value=200, is_valid=True)
        unis = {"uni_a": new_uni_a, "uni_z": new_uni_z}
        with pytest.raises(KytosTagError):
            evc._get_unis_use_tags(**unis)
        assert evc._use_uni_vlan.call_count == 1
        assert evc._use_uni_vlan.call_args[0][0] == new_uni_a
        assert evc.make_uni_vlan_available.call_count == 0

    @patch("napps.kytos.mef_eline.models.evc.range_difference")
    def test_use_uni_vlan(self, mock_difference):
        """Test _use_uni_vlan"""
        attributes = {
            "controller": get_controller_mock(),
            "name": "circuit_name",
            "enable": True,
            "uni_a": get_uni_mocked(is_valid=True),
            "uni_z": get_uni_mocked(is_valid=True)
        }
        evc = EVC(**attributes)
        uni = get_uni_mocked(is_valid=True)
        uni.interface.use_tags = MagicMock()
        evc._use_uni_vlan(uni)
        args = uni.interface.use_tags.call_args[0]
        assert args[1] == uni.user_tag.value
        assert args[2] == uni.user_tag.tag_type
        assert uni.interface.use_tags.call_count == 1

        uni.user_tag.value = "any"
        evc._use_uni_vlan(uni)
        assert uni.interface.use_tags.call_count == 1

        uni.user_tag.value = [[1, 10]]
        uni_dif = get_uni_mocked(tag_value=[[1, 2]])
        mock_difference.return_value = [[3, 10]]
        evc._use_uni_vlan(uni, uni_dif)
        assert uni.interface.use_tags.call_count == 2

        mock_difference.return_value = []
        evc._use_uni_vlan(uni, uni_dif)
        assert uni.interface.use_tags.call_count == 2

        uni.interface.use_tags.side_effect = KytosTagError("")
        with pytest.raises(KytosTagError):
            evc._use_uni_vlan(uni)
        assert uni.interface.use_tags.call_count == 3

        uni.user_tag = None
        evc._use_uni_vlan(uni)
        assert uni.interface.use_tags.call_count == 3

    @patch("napps.kytos.mef_eline.models.evc.log")
    def test_make_uni_vlan_available(self, mock_log):
        """Test make_uni_vlan_available"""
        attributes = {
            "controller": get_controller_mock(),
            "name": "circuit_name",
            "enable": True,
            "uni_a": get_uni_mocked(is_valid=True),
            "uni_z": get_uni_mocked(is_valid=True)
        }
        evc = EVC(**attributes)
        uni = get_uni_mocked(is_valid=True)
        uni.interface.make_tags_available = MagicMock()

        evc.make_uni_vlan_available(uni)
        args = uni.interface.make_tags_available.call_args[0]
        assert args[1] == uni.user_tag.value
        assert args[2] == uni.user_tag.tag_type
        assert uni.interface.make_tags_available.call_count == 1

        uni.user_tag.value = None
        evc.make_uni_vlan_available(uni)
        assert uni.interface.make_tags_available.call_count == 1

        uni.user_tag.value = [[1, 10]]
        uni_dif = get_uni_mocked(tag_value=[[1, 2]])
        evc.make_uni_vlan_available(uni, uni_dif)
        assert uni.interface.make_tags_available.call_count == 2

        uni.interface.make_tags_available.side_effect = KytosTagError("")
        evc.make_uni_vlan_available(uni)
        assert mock_log.error.call_count == 1

        uni.user_tag = None
        evc.make_uni_vlan_available(uni)
        assert uni.interface.make_tags_available.call_count == 3

    def test_remove_uni_tags(self):
        """Test remove_uni_tags"""
        attributes = {
            "controller": get_controller_mock(),
            "name": "circuit_name",
            "enable": True,
            "uni_a": get_uni_mocked(is_valid=True),
            "uni_z": get_uni_mocked(is_valid=True)
        }
        evc = EVC(**attributes)
        evc.make_uni_vlan_available = MagicMock()
        evc.remove_uni_tags()
        assert evc.make_uni_vlan_available.call_count == 2

    def test_tag_lists_equal(self):
        """Test _tag_lists_equal"""
        attributes = {
            "controller": get_controller_mock(),
            "name": "circuit_name",
            "enable": True,
            "uni_a": get_uni_mocked(is_valid=True),
            "uni_z": get_uni_mocked(is_valid=True)
        }
        evc = EVC(**attributes)
        uni = MagicMock(user_tag=TAGRange("vlan", [[1, 10]]))
        update_dict = {"uni_z": uni}
        assert evc._tag_lists_equal(**update_dict) is False

        update_dict = {"uni_a": uni, "uni_z": uni}
        assert evc._tag_lists_equal(**update_dict)
