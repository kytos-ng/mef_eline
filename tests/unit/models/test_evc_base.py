"""Module to test the EVCBase class."""
import sys
from unittest import TestCase
from unittest.mock import patch

# pylint: disable=wrong-import-position
sys.path.insert(0, "/var/lib/kytos/napps/..")
# pylint: enable=wrong-import-position
from napps.kytos.mef_eline.models import EVC  # NOQA  pycodestyle
from napps.kytos.mef_eline.scheduler import (
    CircuitSchedule,
)  # NOQA  pycodestyle
from napps.kytos.mef_eline.tests.helpers import (
    get_uni_mocked,
    get_controller_mock,
)  # NOQA  pycodestyle


class TestEVC(TestCase):  # pylint: disable=too-many-public-methods
    """Tests to verify EVC class."""

    def test_attributes_empty(self):
        """Test if the EVC raises an error with name is required."""
        attributes = {"controller": get_controller_mock()}
        error_message = "name is required."
        with self.assertRaises(ValueError) as handle_error:
            EVC(**attributes)
        self.assertEqual(str(handle_error.exception), error_message)

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
            "updated_at"
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
        with self.assertRaises(ValueError) as handle_error:
            EVC(**attributes)
        self.assertEqual(str(handle_error.exception), error_message)

    def test_with_invalid_uni_a(self):
        """Test if the EVC raises and error with invalid UNI A."""
        attributes = {
            "controller": get_controller_mock(),
            "name": "circuit_name",
            "uni_a": get_uni_mocked(tag_value=82),
        }
        error_message = "VLAN tag 82 is not available in uni_a"
        with self.assertRaises(ValueError) as handle_error:
            EVC(**attributes)
        self.assertEqual(str(handle_error.exception), error_message)

    def test_without_uni_z(self):
        """Test if the EVC raises and error with UNI Z is required."""
        attributes = {
            "controller": get_controller_mock(),
            "name": "circuit_name",
            "uni_a": get_uni_mocked(is_valid=True),
        }
        error_message = "uni_z is required."
        with self.assertRaises(ValueError) as handle_error:
            EVC(**attributes)
        self.assertEqual(str(handle_error.exception), error_message)

    def test_with_invalid_uni_z(self):
        """Test if the EVC raises and error with UNI Z is required."""
        attributes = {
            "controller": get_controller_mock(),
            "name": "circuit_name",
            "uni_a": get_uni_mocked(is_valid=True),
            "uni_z": get_uni_mocked(tag_value=83),
        }
        error_message = "VLAN tag 83 is not available in uni_z"
        with self.assertRaises(ValueError) as handle_error:
            EVC(**attributes)
        self.assertEqual(str(handle_error.exception), error_message)

    def test_update_read_only(self):
        """Test if raises an error when trying to update read only attr."""
        attributes = {
            "controller": get_controller_mock(),
            "name": "circuit_name",
            "uni_a": get_uni_mocked(is_valid=True),
            "uni_z": get_uni_mocked(is_valid=True),
        }
        update_attr = [
            ("archived", True),
            ("_id", True),
            ("active", True),
            ("current_path", []),
            ("creation_time", "date"),
        ]

        for name, value in update_attr:
            with self.subTest(name=name, value=value):
                update_dict = {name: value}
                error_message = f"{name} can't be updated."
                with self.assertRaises(ValueError) as handle_error:
                    evc = EVC(**attributes)
                    evc.update(**update_dict)
                self.assertEqual(str(handle_error.exception), error_message)

    def test_update_invalid(self):
        """Test updating with an invalid attr"""
        attributes = {
            "controller": get_controller_mock(),
            "name": "circuit_name",
            "uni_a": get_uni_mocked(is_valid=True),
            "uni_z": get_uni_mocked(is_valid=True),
        }
        evc = EVC(**attributes)
        with self.assertRaises(ValueError) as handle_error:
            evc.update(xyz="abc")
        self.assertEqual(
            str(handle_error.exception),
            'The attribute "xyz" is invalid.'
        )

    @patch("napps.kytos.mef_eline.models.EVC.sync")
    def test_update_disable(self, _sync_mock):
        """Test if evc is disabled."""
        attributes = {
            "controller": get_controller_mock(),
            "name": "circuit_name",
            "enable": True,
            "uni_a": get_uni_mocked(is_valid=True),
            "uni_z": get_uni_mocked(is_valid=True),
        }
        update_dict = {"enable": False}
        evc = EVC(**attributes)
        evc.update(**update_dict)
        self.assertIs(evc.is_enabled(), False)

    @patch("napps.kytos.mef_eline.models.EVC.sync")
    def test_update_queue(self, _sync_mock):
        """Test if evc is set to redeploy."""
        attributes = {
            "controller": get_controller_mock(),
            "name": "circuit_name",
            "enable": True,
            "uni_a": get_uni_mocked(is_valid=True),
            "uni_z": get_uni_mocked(is_valid=True),
        }
        update_dict = {"queue_id": 3}
        evc = EVC(**attributes)
        _, redeploy = evc.update(**update_dict)
        self.assertTrue(redeploy)

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
        self.assertEqual(str(evc), expected_value)

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

        self.assertEqual(evc1 == evc2, True)
        self.assertEqual(evc1 == evc3, False)
        self.assertEqual(evc2 == evc3, False)
        self.assertEqual(evc3 == evc4, True)

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
            self.assertEqual(value, actual)

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
