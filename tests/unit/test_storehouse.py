"""Module to test the schedule.py file."""
from unittest import TestCase
from unittest.mock import patch, Mock

from napps.kytos.mef_eline.storehouse import StoreHouse
from napps.kytos.mef_eline.tests.helpers import get_controller_mock


class TestStoreHouse(TestCase):
    """Tests to verify StoreHouse class."""

    def setUp(self):
        """Execute steps before each tests."""
        self.storehouse = StoreHouse(get_controller_mock())

    def test_get_stored_box(self):
        """Test get_stored_box method."""
        self.storehouse.controller.buffers = Mock()
        self.storehouse.get_stored_box(1)
        self.storehouse.controller.buffers.app.put.assert_called_once()

    def test_create_box(self):
        """Test get_stored_box method."""
        self.storehouse.controller.buffers = Mock()
        self.storehouse.create_box()
        self.storehouse.controller.buffers.app.put.assert_called_once()

    @patch("napps.kytos.mef_eline.storehouse.log")
    def test_save_evc_callback_no_error(self, log_mock):
        # pylint: disable=protected-access
        """Test _save_evc_callback method."""
        self.storehouse._lock = Mock()
        data = Mock()
        data.box_id = 1
        self.storehouse._save_evc_callback("event", data, None)
        self.storehouse._lock.release.assert_called_once()
        log_mock.error.assert_not_called()

    @patch("napps.kytos.mef_eline.storehouse.log")
    def test_save_evc_callback_with_error(self, log_mock):
        # pylint: disable=protected-access
        """Test _save_evc_callback method."""
        self.storehouse._lock = Mock()
        self.storehouse.box = Mock()
        self.storehouse.box.box_id = 1
        data = Mock()
        data.box_id = 1
        self.storehouse._save_evc_callback("event", data, "error")
        self.storehouse._lock.release.assert_called_once()
        log_mock.error.assert_called_once()

    @patch("napps.kytos.mef_eline.storehouse.StoreHouse.get_stored_box")
    def test_get_data(self, get_stored_box_mock):
        """Test get_data method."""
        self.storehouse.box = Mock()
        self.storehouse.box.box_id = 2
        self.storehouse.get_data()
        get_stored_box_mock.assert_called_once_with(2)

    @patch('napps.kytos.mef_eline.storehouse.log')
    def test_create_box_callback(self, log_mock):
        # pylint: disable=protected-access
        """Test _create_box_callback method."""
        data = Mock()
        data.box_id = 1
        self.storehouse._create_box_callback('event', data, None)
        log_mock.error.assert_not_called()
        log_mock.debug.assert_called_once()

        # test with error
        log_mock.debug.call_count = 0
        self.storehouse._create_box_callback('event', data, 'error')
        log_mock.error.assert_called_once()
        log_mock.debug.assert_called_once()

    @patch('napps.kytos.mef_eline.storehouse.StoreHouse.get_stored_box')
    @patch('napps.kytos.mef_eline.storehouse.StoreHouse.create_box')
    def test_get_or_create_box(self, create_box_mock, get_stored_box_mock):
        """Test _get_or_create_a_box_from_list_of_boxes method."""
        # pylint: disable=protected-access
        self.storehouse._get_or_create_a_box_from_list_of_boxes(
            'event', [2], None
        )
        get_stored_box_mock.assert_called_once_with(2)

        self.storehouse._get_or_create_a_box_from_list_of_boxes(
            'event', None, 'error'
        )
        create_box_mock.assert_called_once()

    @patch('napps.kytos.mef_eline.storehouse.log')
    def test_get_box_callback(self, log_mock):
        # pylint: disable=protected-access
        """Test _get_box_callback method."""
        self.storehouse._lock = Mock()
        data = Mock()
        data.box_id = 1
        self.storehouse._get_box_callback('event', data, None)
        self.storehouse._lock.release.assert_called_once()
        log_mock.error.assert_not_called()

        # test with error
        self.storehouse._lock.release.call_count = 0
        log_mock.debug.call_count = 0
        self.storehouse._get_box_callback('event', data, 'error')
        self.storehouse._lock.release.assert_called_once()
        log_mock.error.assert_called_once()
        self.assertEqual(log_mock.debug.call_count, 2)
