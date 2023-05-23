"""Module to test the main napp file."""
from unittest.mock import (AsyncMock, MagicMock, PropertyMock, call,
                           create_autospec, patch)

import pytest
from kytos.lib.helpers import get_controller_mock, get_test_client

from kytos.core.events import KytosEvent
from kytos.core.interface import UNI, Interface
from napps.kytos.mef_eline.exceptions import InvalidPath
from napps.kytos.mef_eline.models import EVC
from napps.kytos.mef_eline.tests.helpers import get_uni_mocked


async def test_on_table_enabled():
    """Test on_table_enabled"""
    # pylint: disable=import-outside-toplevel
    from napps.kytos.mef_eline.main import Main
    controller = get_controller_mock()
    controller.buffers.app.aput = AsyncMock()
    Main.get_eline_controller = MagicMock()
    napp = Main(controller)

    # Succesfully setting table groups
    content = {"mef_eline": {"epl": 2}}
    event = KytosEvent(name="kytos/of_multi_table.enable_table",
                       content=content)
    await napp.on_table_enabled(event)
    assert napp.table_group["epl"] == 2
    assert napp.table_group["evpl"] == 0
    assert controller.buffers.app.aput.call_count == 1

    # Failure at setting table groups
    content = {"mef_eline": {"unknown": 123}}
    event = KytosEvent(name="kytos/of_multi_table.enable_table",
                       content=content)
    await napp.on_table_enabled(event)
    assert controller.buffers.app.aput.call_count == 1


# pylint: disable=too-many-public-methods, too-many-lines
# pylint: disable=too-many-arguments,too-many-locals
class TestMain:
    """Test the Main class."""

    def setup_method(self):
        """Execute steps before each tests.

        Set the server_name_url_url from kytos/mef_eline
        """

        # The decorator run_on_thread is patched, so methods that listen
        # for events do not run on threads while tested.
        # Decorators have to be patched before the methods that are
        # decorated with them are imported.
        patch("kytos.core.helpers.run_on_thread", lambda x: x).start()
        # pylint: disable=import-outside-toplevel
        from napps.kytos.mef_eline.main import Main
        Main.get_eline_controller = MagicMock()
        controller = get_controller_mock()
        self.napp = Main(controller)
        self.api_client = get_test_client(controller, self.napp)
        self.base_endpoint = "kytos/mef_eline"

    def test_get_event_listeners(self):
        """Verify all event listeners registered."""
        expected_events = [
            "kytos/core.shutdown",
            "kytos/core.shutdown.kytos/mef_eline",
            "kytos/topology.link_up",
            "kytos/topology.link_down",
        ]
        actual_events = self.napp.listeners()

        for _event in expected_events:
            assert _event in actual_events, _event

    @patch('napps.kytos.mef_eline.main.log')
    @patch('napps.kytos.mef_eline.main.Main.execute_consistency')
    def test_execute(self, mock_execute_consistency, mock_log):
        """Test execute."""
        self.napp.execution_rounds = 0
        self.napp.execute()
        mock_execute_consistency.assert_called()
        assert mock_log.debug.call_count == 2

        # Test locked should return
        mock_execute_consistency.call_count = 0
        mock_log.info.call_count = 0
        # pylint: disable=protected-access
        self.napp._lock = MagicMock()
        self.napp._lock.locked.return_value = True
        # pylint: enable=protected-access
        self.napp.execute()
        mock_execute_consistency.assert_not_called()
        mock_log.info.assert_not_called()

    @patch('napps.kytos.mef_eline.main.settings')
    @patch('napps.kytos.mef_eline.main.Main._load_evc')
    @patch("napps.kytos.mef_eline.controllers.ELineController.upsert_evc")
    @patch("napps.kytos.mef_eline.models.evc.EVCDeploy.check_list_traces")
    def test_execute_consistency(self, mock_check_list_traces, *args):
        """Test execute_consistency."""
        (mongo_controller_upsert_mock, mock_load_evc, mock_settings) = args

        stored_circuits = {'1': {'name': 'circuit_1'},
                           '2': {'name': 'circuit_2'},
                           '3': {'name': 'circuit_3'}}
        mongo_controller_upsert_mock.return_value = True
        self.napp.mongo_controller.get_circuits.return_value = {
            "circuits": stored_circuits
        }

        mock_settings.WAIT_FOR_OLD_PATH = -1
        evc1 = MagicMock(id=1, service_level=0, creation_time=1)
        evc1.is_enabled.return_value = True
        evc1.is_active.return_value = False
        evc1.lock.locked.return_value = False
        evc1.has_recent_removed_flow.return_value = False
        evc1.is_recent_updated.return_value = False
        evc1.execution_rounds = 0
        evc2 = MagicMock(id=2, service_level=7, creation_time=1)
        evc2.is_enabled.return_value = True
        evc2.is_active.return_value = False
        evc2.lock.locked.return_value = False
        evc2.has_recent_removed_flow.return_value = False
        evc2.is_recent_updated.return_value = False
        evc2.execution_rounds = 0
        self.napp.circuits = {'1': evc1, '2': evc2}
        assert self.napp.get_evcs_by_svc_level() == [evc2, evc1]

        mock_check_list_traces.return_value = {
                                                1: True,
                                                2: False
                                            }

        self.napp.execute_consistency()
        assert evc1.activate.call_count == 1
        assert evc1.sync.call_count == 1
        assert evc2.deploy.call_count == 1
        mock_load_evc.assert_called_with(stored_circuits['3'])

    @patch('napps.kytos.mef_eline.main.settings')
    @patch('napps.kytos.mef_eline.main.Main._load_evc')
    @patch("napps.kytos.mef_eline.controllers.ELineController.upsert_evc")
    @patch("napps.kytos.mef_eline.models.evc.EVCDeploy.check_list_traces")
    def test_execute_consistency_wait_for(self, mock_check_list_traces, *args):
        """Test execute and wait for setting."""
        (mongo_controller_upsert_mock, _, mock_settings) = args

        stored_circuits = {'1': {'name': 'circuit_1'}}
        mongo_controller_upsert_mock.return_value = True
        self.napp.mongo_controller.get_circuits.return_value = {
            "circuits": stored_circuits
        }

        mock_settings.WAIT_FOR_OLD_PATH = -1
        evc1 = MagicMock(id=1, service_level=0, creation_time=1)
        evc1.is_enabled.return_value = True
        evc1.is_active.return_value = False
        evc1.lock.locked.return_value = False
        evc1.has_recent_removed_flow.return_value = False
        evc1.is_recent_updated.return_value = False
        evc1.execution_rounds = 0
        evc1.deploy.call_count = 0
        self.napp.circuits = {'1': evc1}
        assert self.napp.get_evcs_by_svc_level() == [evc1]
        mock_settings.WAIT_FOR_OLD_PATH = 1

        mock_check_list_traces.return_value = {1: False}

        self.napp.execute_consistency()
        assert evc1.deploy.call_count == 0
        self.napp.execute_consistency()
        assert evc1.deploy.call_count == 1

    @patch('napps.kytos.mef_eline.main.Main._uni_from_dict')
    @patch('napps.kytos.mef_eline.models.evc.EVCBase._validate')
    def test_evc_from_dict(self, _validate_mock, uni_from_dict_mock):
        """
        Test the helper method that create an EVN from dict.

        Verify object creation with circuit data and schedule data.
        """
        _validate_mock.return_value = True
        uni_from_dict_mock.side_effect = ["uni_a", "uni_z"]
        payload = {
            "name": "my evc1",
            "uni_a": {
                "interface_id": "00:00:00:00:00:00:00:01:1",
                "tag": {"tag_type": 1, "value": 80},
            },
            "uni_z": {
                "interface_id": "00:00:00:00:00:00:00:02:2",
                "tag": {"tag_type": 1, "value": 1},
            },
            "circuit_scheduler": [
                {"frequency": "* * * * *", "action": "create"}
            ],
            "queue_id": 5,
        }
        # pylint: disable=protected-access
        evc_response = self.napp._evc_from_dict(payload)
        assert evc_response is not None
        assert evc_response.uni_a is not None
        assert evc_response.uni_z is not None
        assert evc_response.circuit_scheduler is not None
        assert evc_response.name is not None
        assert evc_response.queue_id is not None

    @patch("napps.kytos.mef_eline.main.Main._uni_from_dict")
    @patch("napps.kytos.mef_eline.models.evc.EVCBase._validate")
    @patch("kytos.core.Controller.get_interface_by_id")
    def test_evc_from_dict_paths(
        self, _get_interface_by_id_mock, _validate_mock, uni_from_dict_mock
    ):
        """
        Test the helper method that create an EVN from dict.

        Verify object creation with circuit data and schedule data.
        """

        _get_interface_by_id_mock.return_value = get_uni_mocked().interface
        _validate_mock.return_value = True
        uni_from_dict_mock.side_effect = ["uni_a", "uni_z"]
        payload = {
            "name": "my evc1",
            "uni_a": {
                "interface_id": "00:00:00:00:00:00:00:01:1",
                "tag": {"tag_type": 1, "value": 80},
            },
            "uni_z": {
                "interface_id": "00:00:00:00:00:00:00:02:2",
                "tag": {"tag_type": 1, "value": 1},
            },
            "current_path": [],
            "primary_path": [
                {
                    "endpoint_a": {
                        "interface_id": "00:00:00:00:00:00:00:01:1"
                    },
                    "endpoint_b": {
                        "interface_id": "00:00:00:00:00:00:00:02:2"
                    },
                }
            ],
            "backup_path": [],
        }

        # pylint: disable=protected-access
        evc_response = self.napp._evc_from_dict(payload)
        assert evc_response is not None
        assert evc_response.uni_a is not None
        assert evc_response.uni_z is not None
        assert evc_response.circuit_scheduler is not None
        assert evc_response.name is not None
        assert len(evc_response.current_path) == 0
        assert len(evc_response.backup_path) == 0
        assert len(evc_response.primary_path) == 1

    @patch("napps.kytos.mef_eline.main.Main._uni_from_dict")
    @patch("napps.kytos.mef_eline.models.evc.EVCBase._validate")
    @patch("kytos.core.Controller.get_interface_by_id")
    def test_evc_from_dict_links(
        self, _get_interface_by_id_mock, _validate_mock, uni_from_dict_mock
    ):
        """
        Test the helper method that create an EVN from dict.

        Verify object creation with circuit data and schedule data.
        """
        _get_interface_by_id_mock.return_value = get_uni_mocked().interface
        _validate_mock.return_value = True
        uni_from_dict_mock.side_effect = ["uni_a", "uni_z"]
        payload = {
            "name": "my evc1",
            "uni_a": {
                "interface_id": "00:00:00:00:00:00:00:01:1",
                "tag": {"tag_type": 1, "value": 80},
            },
            "uni_z": {
                "interface_id": "00:00:00:00:00:00:00:02:2",
                "tag": {"tag_type": 1, "value": 1},
            },
            "primary_links": [
                {
                    "endpoint_a": {
                        "interface_id": "00:00:00:00:00:00:00:01:1"
                    },
                    "endpoint_b": {
                        "interface_id": "00:00:00:00:00:00:00:02:2"
                    },
                    "metadata": {
                        "s_vlan": {
                            "tag_type": 1,
                            "value": 100
                        }
                    },
                }
            ],
            "backup_links": [],
        }

        # pylint: disable=protected-access
        evc_response = self.napp._evc_from_dict(payload)
        assert evc_response is not None
        assert evc_response.uni_a is not None
        assert evc_response.uni_z is not None
        assert evc_response.circuit_scheduler is not None
        assert evc_response.name is not None
        assert len(evc_response.current_links_cache) == 0
        assert len(evc_response.backup_links) == 0
        assert len(evc_response.primary_links) == 1

    async def test_list_without_circuits(self):
        """Test if list circuits return 'no circuit stored.'."""
        circuits = {"circuits": {}}
        self.napp.mongo_controller.get_circuits.return_value = circuits
        url = f"{self.base_endpoint}/v2/evc/"
        response = await self.api_client.get(url)
        assert response.status_code == 200, response.data
        assert not response.json()

    async def test_list_no_circuits_stored(self):
        """Test if list circuits return all circuits stored."""
        circuits = {"circuits": {}}
        self.napp.mongo_controller.get_circuits.return_value = circuits

        url = f"{self.base_endpoint}/v2/evc/"
        response = await self.api_client.get(url)
        expected_result = circuits["circuits"]
        assert response.json() == expected_result

    async def test_list_with_circuits_stored(self):
        """Test if list circuits return all circuits stored."""
        circuits = {
            'circuits':
            {"1": {"name": "circuit_1"}, "2": {"name": "circuit_2"}}
        }
        get_circuits = self.napp.mongo_controller.get_circuits
        get_circuits.return_value = circuits

        url = f"{self.base_endpoint}/v2/evc/"
        response = await self.api_client.get(url)
        expected_result = circuits["circuits"]
        get_circuits.assert_called_with(archived="false", metadata={})
        assert response.json() == expected_result

    async def test_list_with_archived_circuits_archived(self):
        """Test if list circuits only archived circuits."""
        circuits = {
            'circuits':
            {
                "1": {"name": "circuit_1", "archived": True},
            }
        }
        get_circuits = self.napp.mongo_controller.get_circuits
        get_circuits.return_value = circuits

        url = f"{self.base_endpoint}/v2/evc/?archived=true&metadata.a=1"
        response = await self.api_client.get(url)
        get_circuits.assert_called_with(archived="true",
                                        metadata={"metadata.a": "1"})
        expected_result = {"1": circuits["circuits"]["1"]}
        assert response.json() == expected_result

    async def test_list_with_archived_circuits_all(self):
        """Test if list circuits return all circuits."""
        circuits = {
            'circuits': {
                "1": {"name": "circuit_1"},
                "2": {"name": "circuit_2", "archived": True},
            }
        }
        self.napp.mongo_controller.get_circuits.return_value = circuits

        url = f"{self.base_endpoint}/v2/evc/?archived=null"
        response = await self.api_client.get(url)
        expected_result = circuits["circuits"]
        assert response.json() == expected_result

    async def test_circuit_with_valid_id(self):
        """Test if get_circuit return the circuit attributes."""
        circuit = {"name": "circuit_1"}
        self.napp.mongo_controller.get_circuit.return_value = circuit

        url = f"{self.base_endpoint}/v2/evc/1"
        response = await self.api_client.get(url)
        expected_result = circuit
        assert response.json() == expected_result

    async def test_circuit_with_invalid_id(self):
        """Test if get_circuit return invalid circuit_id."""
        self.napp.mongo_controller.get_circuit.return_value = None
        url = f"{self.base_endpoint}/v2/evc/3"
        response = await self.api_client.get(url)
        expected_result = "circuit_id 3 not found"
        assert response.json()["description"] == expected_result

    @patch("napps.kytos.mef_eline.models.evc.EVC.deploy")
    @patch("napps.kytos.mef_eline.scheduler.Scheduler.add")
    @patch("napps.kytos.mef_eline.main.Main._uni_from_dict")
    @patch("napps.kytos.mef_eline.controllers.ELineController.upsert_evc")
    @patch("napps.kytos.mef_eline.main.EVC.as_dict")
    @patch("napps.kytos.mef_eline.models.evc.EVC._validate")
    async def test_create_a_circuit_case_1(
        self,
        validate_mock,
        evc_as_dict_mock,
        mongo_controller_upsert_mock,
        uni_from_dict_mock,
        sched_add_mock,
        evc_deploy_mock,
        event_loop
    ):
        """Test create a new circuit."""
        # pylint: disable=too-many-locals
        self.napp.controller.loop = event_loop
        validate_mock.return_value = True
        mongo_controller_upsert_mock.return_value = True
        evc_deploy_mock.return_value = True
        uni1 = create_autospec(UNI)
        uni2 = create_autospec(UNI)
        uni1.interface = create_autospec(Interface)
        uni2.interface = create_autospec(Interface)
        uni1.interface.switch = MagicMock()
        uni1.interface.switch.return_value = "00:00:00:00:00:00:00:01"
        uni1.interface.switch.is_enabled.return_value = True
        uni2.interface.switch = MagicMock()
        uni2.interface.switch.return_value = "00:00:00:00:00:00:00:02"
        uni2.interface.switch.is_enabled.return_value = True
        uni_from_dict_mock.side_effect = [uni1, uni2]
        evc_as_dict_mock.return_value = {}
        sched_add_mock.return_value = True
        self.napp.mongo_controller.get_circuits.return_value = {}

        url = f"{self.base_endpoint}/v2/evc/"
        payload = {
            "name": "my evc1",
            "frequency": "* * * * *",
            "uni_a": {
                "interface_id": "00:00:00:00:00:00:00:01:1",
                "tag": {"tag_type": 1, "value": 80},
            },
            "uni_z": {
                "interface_id": "00:00:00:00:00:00:00:02:2",
                "tag": {"tag_type": 1, "value": 1},
            },
            "dynamic_backup_path": True,
            "primary_constraints": {
                "spf_max_path_cost": 8,
                "mandatory_metrics": {
                    "ownership": "red"
                }
            },
            "secondary_constraints": {
                "mandatory_metrics": {
                    "ownership": "blue"
                }
            }
        }

        response = await self.api_client.post(url, json=payload)
        current_data = response.json()

        # verify expected result from request
        assert 201 == response.status_code
        assert "circuit_id" in current_data

        # verify uni called
        uni_from_dict_mock.called_twice()
        uni_from_dict_mock.assert_any_call(payload["uni_z"])
        uni_from_dict_mock.assert_any_call(payload["uni_a"])

        # verify validation called
        validate_mock.assert_called_once()
        validate_mock.assert_called_with(
            table_group={'evpl': 0, 'epl': 0},
            frequency="* * * * *",
            name="my evc1",
            uni_a=uni1,
            uni_z=uni2,
            dynamic_backup_path=True,
            primary_constraints=payload["primary_constraints"],
            secondary_constraints=payload["secondary_constraints"],
        )
        # verify save method is called
        mongo_controller_upsert_mock.assert_called_once()

        # verify evc as dict is called to save in the box
        evc_as_dict_mock.assert_called()
        # verify add circuit in sched
        sched_add_mock.assert_called_once()

    async def test_create_a_circuit_case_2(self, event_loop):
        """Test create a new circuit trying to send request without a json."""
        self.napp.controller.loop = event_loop
        url = f"{self.base_endpoint}/v2/evc/"

        response = await self.api_client.post(url)
        current_data = response.json()
        assert 400 == response.status_code
        assert "Missing required request body" in current_data["description"]

    async def test_create_a_circuit_case_3(self, event_loop):
        """Test create a new circuit trying to send request with an
        invalid json."""
        self.napp.controller.loop = event_loop
        url = f"{self.base_endpoint}/v2/evc/"

        response = await self.api_client.post(
            url,
            json="This is an {Invalid:} JSON",
        )
        current_data = response.json()
        assert 400 == response.status_code
        assert "contains invalid" in current_data["description"]

    @patch("napps.kytos.mef_eline.main.Main._uni_from_dict")
    @patch("napps.kytos.mef_eline.controllers.ELineController.upsert_evc")
    async def test_create_a_circuit_case_4(
        self,
        mongo_controller_upsert_mock,
        uni_from_dict_mock,
        event_loop
    ):
        """Test create a new circuit trying to send request with an
        invalid value."""
        self.napp.controller.loop = event_loop
        # pylint: disable=too-many-locals
        uni_from_dict_mock.side_effect = ValueError("Could not instantiate")
        mongo_controller_upsert_mock.return_value = True
        url = f"{self.base_endpoint}/v2/evc/"

        payload = {
            "name": "my evc1",
            "frequency": "* * * * *",
            "uni_a": {
                "interface_id": "00:00:00:00:00:00:00:01:76",
                "tag": {"tag_type": 1, "value": 80},
            },
            "uni_z": {
                "interface_id": "00:00:00:00:00:00:00:02:2",
                "tag": {"tag_type": 1, "value": 1},
            },
        }

        response = await self.api_client.post(url, json=payload)
        current_data = response.json()
        expected_data = "Error creating UNI: Invalid value"
        assert 400 == response.status_code
        assert current_data["description"] == expected_data

        payload["name"] = 1
        response = await self.api_client.post(url, json=payload)
        assert 400 == response.status_code, response.data

    async def test_create_a_circuit_invalid_queue_id(self, event_loop):
        """Test create a new circuit with invalid queue_id."""
        self.napp.controller.loop = event_loop
        url = f"{self.base_endpoint}/v2/evc/"

        payload = {
            "name": "my evc1",
            "queue_id": 8,
            "uni_a": {
                "interface_id": "00:00:00:00:00:00:00:01:76",
                "tag": {"tag_type": 1, "value": 80},
            },
            "uni_z": {
                "interface_id": "00:00:00:00:00:00:00:02:2",
                "tag": {"tag_type": 1, "value": 1},
            },
        }
        response = await self.api_client.post(url, json=payload)
        current_data = response.json()
        expected_data = "8 is greater than the maximum of 7"

        assert response.status_code == 400
        assert expected_data in current_data["description"]

    @patch("napps.kytos.mef_eline.models.evc.EVC.deploy")
    @patch("napps.kytos.mef_eline.scheduler.Scheduler.add")
    @patch("napps.kytos.mef_eline.main.Main._uni_from_dict")
    @patch("napps.kytos.mef_eline.controllers.ELineController.upsert_evc")
    @patch("napps.kytos.mef_eline.models.evc.EVC._validate")
    @patch("napps.kytos.mef_eline.main.EVC.as_dict")
    async def test_create_circuit_already_enabled(
        self,
        evc_as_dict_mock,
        validate_mock,
        mongo_controller_upsert_mock,
        uni_from_dict_mock,
        sched_add_mock,
        evc_deploy_mock,
        event_loop
    ):
        """Test create an already created circuit."""
        # pylint: disable=too-many-locals
        self.napp.controller.loop = event_loop
        validate_mock.return_value = True
        mongo_controller_upsert_mock.return_value = True
        sched_add_mock.return_value = True
        evc_deploy_mock.return_value = True
        uni1 = create_autospec(UNI)
        uni2 = create_autospec(UNI)
        uni1.interface = create_autospec(Interface)
        uni2.interface = create_autospec(Interface)
        uni1.interface.switch = MagicMock()
        uni1.interface.switch.return_value = "00:00:00:00:00:00:00:01"
        uni1.interface.switch.is_enabled.return_value = True
        uni2.interface.switch = MagicMock()
        uni2.interface.switch.return_value = "00:00:00:00:00:00:00:02"
        uni2.interface.switch.is_enabled.return_value = True
        uni_from_dict_mock.side_effect = [uni1, uni2, uni1, uni2]

        payload = {
            "name": "my evc1",
            "uni_a": {
                "interface_id": "00:00:00:00:00:00:00:01:1",
                "tag": {"tag_type": 1, "value": 80},
            },
            "uni_z": {
                "interface_id": "00:00:00:00:00:00:00:02:2",
                "tag": {"tag_type": 1, "value": 1},
            },
            "dynamic_backup_path": True,
        }

        evc_as_dict_mock.return_value = payload
        response = await self.api_client.post(
            f"{self.base_endpoint}/v2/evc/",
            json=payload
        )
        assert 201 == response.status_code

        response = await self.api_client.post(
            f"{self.base_endpoint}/v2/evc/",
            json=payload
        )
        current_data = response.json()
        expected_data = "The EVC already exists."
        assert current_data["description"] == expected_data
        assert 409 == response.status_code

    @patch("napps.kytos.mef_eline.main.Main._uni_from_dict")
    async def test_create_circuit_case_5(self, uni_from_dict_mock, event_loop):
        """Test when neither primary path nor dynamic_backup_path is set."""
        self.napp.controller.loop = event_loop
        url = f"{self.base_endpoint}/v2/evc/"
        uni1 = create_autospec(UNI)
        uni2 = create_autospec(UNI)
        uni1.interface = create_autospec(Interface)
        uni2.interface = create_autospec(Interface)
        uni1.interface.switch = MagicMock()
        uni1.interface.switch.return_value = "00:00:00:00:00:00:00:01"
        uni1.interface.switch.is_enabled.return_value = True
        uni2.interface.switch = MagicMock()
        uni2.interface.switch.return_value = "00:00:00:00:00:00:00:02"
        uni2.interface.switch.is_enabled.return_value = True
        uni_from_dict_mock.side_effect = [uni1, uni2, uni1, uni2]

        payload = {
            "name": "my evc1",
            "frequency": "* * * * *",
            "uni_a": {
                "interface_id": "00:00:00:00:00:00:00:01:1",
                "tag": {"tag_type": 1, "value": 80},
            },
            "uni_z": {
                "interface_id": "00:00:00:00:00:00:00:02:2",
                "tag": {"tag_type": 1, "value": 1},
            },
        }

        response = await self.api_client.post(url, json=payload)
        current_data = response.json()
        expected_data = "The EVC must have a primary path "
        expected_data += "or allow dynamic paths."
        assert 400 == response.status_code, response.data
        assert current_data["description"] == expected_data

    @patch("napps.kytos.mef_eline.main.Main._uni_from_dict")
    async def test_create_circuit_case_6(
        self,
        uni_from_dict_mock,
        event_loop
    ):
        """Test create a circuit with a disabled switch."""
        # pylint: disable=too-many-locals
        self.napp.controller.loop = event_loop
        uni1 = create_autospec(UNI)
        uni2 = create_autospec(UNI)
        uni1.interface = create_autospec(Interface)
        uni2.interface = create_autospec(Interface)
        uni1.interface.switch = MagicMock()
        uni1.interface.switch.return_value = "00:00:00:00:00:00:00:01"
        uni1.interface.switch.is_enabled.return_value = True
        uni2.interface.switch = MagicMock()
        uni2.interface.switch.return_value = "00:00:00:00:00:00:00:02"
        uni2.interface.switch.is_enabled.return_value = False
        uni_from_dict_mock.side_effect = [uni1, uni2, uni1, uni2]

        payload = {
            "name": "my evc1",
            "uni_a": {
                "interface_id": "00:00:00:00:00:00:00:01:1",
                "tag": {"tag_type": 1, "value": 80},
            },
            "uni_z": {
                "interface_id": "00:00:00:00:00:00:00:02:2",
                "tag": {"tag_type": 1, "value": 1},
            },
            "dynamic_backup_path": True,
        }

        response = await self.api_client.post(
            f"{self.base_endpoint}/v2/evc/",
            json=payload
        )
        assert 409 == response.status_code

    @patch("napps.kytos.mef_eline.main.Main._link_from_dict")
    @patch("napps.kytos.mef_eline.main.Main._uni_from_dict")
    async def test_create_circuit_case_7(
        self,
        uni_from_dict_mock,
        link_from_dict_mock,
        event_loop
    ):
        """Test create a circuit with a disabled switch in static path."""
        # pylint: disable=too-many-locals
        self.napp.controller.loop = event_loop
        link_from_dict_mock.return_value = 1
        uni1 = create_autospec(UNI)
        uni2 = create_autospec(UNI)
        uni1.interface = create_autospec(Interface)
        uni2.interface = create_autospec(Interface)
        uni1.interface.switch = MagicMock()
        uni1.interface.switch.return_value = "00:00:00:00:00:00:00:01"
        uni1.interface.switch.is_enabled.return_value = True
        uni2.interface.switch = MagicMock()
        uni2.interface.switch.return_value = "00:00:00:00:00:00:00:02"
        uni2.interface.switch.is_enabled.return_value = False
        uni_from_dict_mock.side_effect = [uni1, uni2, uni1, uni2]

        payload = {
            "name": "my evc1",
            "uni_a": {
                "interface_id": "00:00:00:00:00:00:00:01:1",
                "tag": {"tag_type": 1, "value": 80},
            },
            "uni_z": {
                "interface_id": "00:00:00:00:00:00:00:03:2",
                "tag": {"tag_type": 1, "value": 1},
            },
            "primary_path": [
                {"endpoint_a": {"id": "00:00:00:00:00:00:00:01:3"},
                 "endpoint_b": {"id": "00:00:00:00:00:00:00:02:2"}},
                {"endpoint_a": {"id": "00:00:00:00:00:00:00:02:3"},
                 "endpoint_b": {"id": "00:00:00:00:00:00:00:03:2"}}
            ],
        }

        response = await self.api_client.post(
            f"{self.base_endpoint}/v2/evc/",
            json=payload
        )
        assert 409 == response.status_code

    async def test_redeploy_evc(self):
        """Test endpoint to redeploy an EVC."""
        evc1 = MagicMock()
        evc1.is_enabled.return_value = True
        self.napp.circuits = {"1": evc1, "2": MagicMock()}
        url = f"{self.base_endpoint}/v2/evc/1/redeploy"
        response = await self.api_client.patch(url)
        assert response.status_code == 202, response.data

    async def test_redeploy_evc_disabled(self):
        """Test endpoint to redeploy an EVC."""
        evc1 = MagicMock()
        evc1.is_enabled.return_value = False
        self.napp.circuits = {"1": evc1, "2": MagicMock()}
        url = f"{self.base_endpoint}/v2/evc/1/redeploy"
        response = await self.api_client.patch(url)
        assert response.status_code == 409, response.data

    async def test_redeploy_evc_deleted(self):
        """Test endpoint to redeploy an EVC."""
        evc1 = MagicMock()
        evc1.is_enabled.return_value = True
        self.napp.circuits = {"1": evc1, "2": MagicMock()}
        url = f"{self.base_endpoint}/v2/evc/3/redeploy"
        response = await self.api_client.patch(url)
        assert response.status_code == 404, response.data

    async def test_list_schedules__no_data_stored(self):
        """Test if list circuits return all circuits stored."""
        self.napp.mongo_controller.get_circuits.return_value = {"circuits": {}}

        url = f"{self.base_endpoint}/v2/evc/schedule"

        response = await self.api_client.get(url)
        assert response.status_code == 200
        assert not response.json()

    def _add_mongodb_schedule_data(self, data_mock):
        """Add schedule data to mongodb mock object."""
        circuits = {"circuits": {}}
        payload_1 = {
            "id": "aa:aa:aa",
            "name": "my evc1",
            "uni_a": {
                "interface_id": "00:00:00:00:00:00:00:01:1",
                "tag": {"tag_type": 1, "value": 80},
            },
            "uni_z": {
                "interface_id": "00:00:00:00:00:00:00:02:2",
                "tag": {"tag_type": 1, "value": 1},
            },
            "circuit_scheduler": [
                {"id": "1", "frequency": "* * * * *", "action": "create"},
                {"id": "2", "frequency": "1 * * * *", "action": "remove"},
            ],
        }
        circuits["circuits"].update({"aa:aa:aa": payload_1})
        payload_2 = {
            "id": "bb:bb:bb",
            "name": "my second evc2",
            "uni_a": {
                "interface_id": "00:00:00:00:00:00:00:01:2",
                "tag": {"tag_type": 1, "value": 90},
            },
            "uni_z": {
                "interface_id": "00:00:00:00:00:00:00:03:2",
                "tag": {"tag_type": 1, "value": 100},
            },
            "circuit_scheduler": [
                {"id": "3", "frequency": "1 * * * *", "action": "create"},
                {"id": "4", "frequency": "2 * * * *", "action": "remove"},
            ],
        }
        circuits["circuits"].update({"bb:bb:bb": payload_2})
        payload_3 = {
            "id": "cc:cc:cc",
            "name": "my third evc3",
            "uni_a": {
                "interface_id": "00:00:00:00:00:00:00:03:1",
                "tag": {"tag_type": 1, "value": 90},
            },
            "uni_z": {
                "interface_id": "00:00:00:00:00:00:00:04:2",
                "tag": {"tag_type": 1, "value": 100},
            },
        }
        circuits["circuits"].update({"cc:cc:cc": payload_3})
        # Add one circuit to the mongodb.
        data_mock.return_value = circuits

    async def test_list_schedules_from_mongodb(self):
        """Test if list circuits return specific circuits stored."""
        self._add_mongodb_schedule_data(
            self.napp.mongo_controller.get_circuits
        )

        url = f"{self.base_endpoint}/v2/evc/schedule"

        # Call URL
        response = await self.api_client.get(url)
        # Expected JSON data from response
        expected = [
            {
                "circuit_id": "aa:aa:aa",
                "schedule": {
                    "action": "create",
                    "frequency": "* * * * *",
                    "id": "1",
                },
                "schedule_id": "1",
            },
            {
                "circuit_id": "aa:aa:aa",
                "schedule": {
                    "action": "remove",
                    "frequency": "1 * * * *",
                    "id": "2",
                },
                "schedule_id": "2",
            },
            {
                "circuit_id": "bb:bb:bb",
                "schedule": {
                    "action": "create",
                    "frequency": "1 * * * *",
                    "id": "3",
                },
                "schedule_id": "3",
            },
            {
                "circuit_id": "bb:bb:bb",
                "schedule": {
                    "action": "remove",
                    "frequency": "2 * * * *",
                    "id": "4",
                },
                "schedule_id": "4",
            },
        ]

        assert response.status_code == 200
        assert expected == response.json()

    async def test_get_specific_schedule_from_mongodb(self):
        """Test get schedules from a circuit."""
        self._add_mongodb_schedule_data(
            self.napp.mongo_controller.get_circuits
        )

        requested_circuit_id = "bb:bb:bb"
        evc = self.napp.mongo_controller.get_circuits()
        evc = evc["circuits"][requested_circuit_id]
        self.napp.mongo_controller.get_circuit.return_value = evc
        url = f"{self.base_endpoint}/v2/evc/{requested_circuit_id}"

        # Call URL
        response = await self.api_client.get(url)

        # Expected JSON data from response
        expected = [
            {"action": "create", "frequency": "1 * * * *", "id": "3"},
            {"action": "remove", "frequency": "2 * * * *", "id": "4"},
        ]

        assert response.status_code == 200
        assert expected == response.json()["circuit_scheduler"]

    async def test_get_specific_schedules_from_mongodb_not_found(self):
        """Test get specific schedule ID that does not exist."""
        requested_id = "blah"
        self.napp.mongo_controller.get_circuit.return_value = None
        url = f"{self.base_endpoint}/v2/evc/{requested_id}"

        # Call URL
        response = await self.api_client.get(url)

        expected = "circuit_id blah not found"
        # Assert response not found
        assert response.status_code == 404
        assert expected == response.json()["description"]

    def _uni_from_dict_side_effect(self, uni_dict):
        interface_id = uni_dict.get("interface_id")
        tag_dict = uni_dict.get("tag")
        interface = Interface(interface_id, "0", MagicMock(id="1"))
        return UNI(interface, tag_dict)

    @patch("apscheduler.schedulers.background.BackgroundScheduler.add_job")
    @patch("napps.kytos.mef_eline.scheduler.Scheduler.add")
    @patch("napps.kytos.mef_eline.main.Main._uni_from_dict")
    @patch("napps.kytos.mef_eline.controllers.ELineController.upsert_evc")
    @patch("napps.kytos.mef_eline.main.EVC.as_dict")
    @patch("napps.kytos.mef_eline.models.evc.EVC._validate")
    async def test_create_schedule(
        self,
        validate_mock,
        evc_as_dict_mock,
        mongo_controller_upsert_mock,
        uni_from_dict_mock,
        sched_add_mock,
        scheduler_add_job_mock,
        event_loop
    ):
        """Test create a circuit schedule."""
        self.napp.controller.loop = event_loop
        validate_mock.return_value = True
        mongo_controller_upsert_mock.return_value = True
        uni_from_dict_mock.side_effect = self._uni_from_dict_side_effect
        evc_as_dict_mock.return_value = {}
        sched_add_mock.return_value = True

        self._add_mongodb_schedule_data(
            self.napp.mongo_controller.get_circuits
        )

        requested_id = "bb:bb:bb"
        url = f"{self.base_endpoint}/v2/evc/schedule/"

        payload = {
            "circuit_id": requested_id,
            "schedule": {"frequency": "1 * * * *", "action": "create"},
            "metadata": {"metadata1": "test_data"},
        }

        # Call URL
        response = await self.api_client.post(url, json=payload)
        response_json = response.json()

        assert response.status_code == 201
        scheduler_add_job_mock.assert_called_once()
        mongo_controller_upsert_mock.assert_called_once()
        assert payload["schedule"]["frequency"] == response_json["frequency"]
        assert payload["schedule"]["action"] == response_json["action"]
        assert response_json["id"] is not None

        # Case 2: there is no schedule
        payload = {
              "circuit_id": "cc:cc:cc",
              "schedule": {
                "frequency": "1 * * * *",
                "action": "create"
              }
            }
        response = await self.api_client.post(url, json=payload)
        assert response.status_code == 201

    async def test_create_schedule_invalid_request(self, event_loop):
        """Test create schedule API with invalid request."""
        self.napp.controller.loop = event_loop
        evc1 = MagicMock()
        self.napp.circuits = {'bb:bb:bb': evc1}
        url = f'{self.base_endpoint}/v2/evc/schedule/'

        # case 1: empty post
        response = await self.api_client.post(url, json={})
        assert response.status_code == 400

        # case 2: content-type not specified
        payload = {
            "circuit_id": "bb:bb:bb",
            "schedule": {
                "frequency": "1 * * * *",
                "action": "create"
            }
        }
        response = await self.api_client.post(url, json=payload)
        assert response.status_code == 409

        # case 3: not a dictionary
        payload = []
        response = await self.api_client.post(url, json=payload)
        assert response.status_code == 400

        # case 4: missing circuit id
        payload = {
            "schedule": {
                "frequency": "1 * * * *",
                "action": "create"
            }
        }
        response = await self.api_client.post(url, json=payload)
        assert response.status_code == 400

        # case 5: missing schedule
        payload = {
            "circuit_id": "bb:bb:bb"
        }
        response = await self.api_client.post(url, json=payload)
        assert response.status_code == 400

        # case 6: invalid circuit
        payload = {
            "circuit_id": "xx:xx:xx",
            "schedule": {
                "frequency": "1 * * * *",
                "action": "create"
            }
        }
        response = await self.api_client.post(url, json=payload)
        assert response.status_code == 404

        # case 7: archived or deleted evc
        evc1.archived.return_value = True
        payload = {
            "circuit_id": "bb:bb:bb",
            "schedule": {
                "frequency": "1 * * * *",
                "action": "create"
            }
        }
        response = await self.api_client.post(url, json=payload)
        assert response.status_code == 409

        # case 8: invalid json
        response = await self.api_client.post(url, json="test")
        assert response.status_code == 400

    @patch('apscheduler.schedulers.background.BackgroundScheduler.remove_job')
    @patch('napps.kytos.mef_eline.scheduler.Scheduler.add')
    @patch('napps.kytos.mef_eline.main.Main._uni_from_dict')
    @patch("napps.kytos.mef_eline.controllers.ELineController.upsert_evc")
    @patch('napps.kytos.mef_eline.main.EVC.as_dict')
    @patch('napps.kytos.mef_eline.models.evc.EVC._validate')
    async def test_update_schedule(
        self,
        validate_mock,
        evc_as_dict_mock,
        mongo_controller_upsert_mock,
        uni_from_dict_mock,
        sched_add_mock,
        scheduler_remove_job_mock,
        event_loop
    ):
        """Test create a circuit schedule."""
        self.napp.controller.loop = event_loop
        mongo_payload_1 = {
            "circuits": {
                "aa:aa:aa": {
                    "id": "aa:aa:aa",
                    "name": "my evc1",
                    "uni_a": {
                        "interface_id": "00:00:00:00:00:00:00:01:1",
                        "tag": {"tag_type": 1, "value": 80},
                    },
                    "uni_z": {
                        "interface_id": "00:00:00:00:00:00:00:02:2",
                        "tag": {"tag_type": 1, "value": 1},
                    },
                    "circuit_scheduler": [
                        {
                            "id": "1",
                            "frequency": "* * * * *",
                            "action": "create"
                        }
                    ],
                }
            }
        }

        validate_mock.return_value = True
        mongo_controller_upsert_mock.return_value = True
        sched_add_mock.return_value = True
        uni_from_dict_mock.side_effect = ["uni_a", "uni_z"]
        evc_as_dict_mock.return_value = {}
        self.napp.mongo_controller.get_circuits.return_value = mongo_payload_1
        scheduler_remove_job_mock.return_value = True

        requested_schedule_id = "1"
        url = f"{self.base_endpoint}/v2/evc/schedule/{requested_schedule_id}"

        payload = {"frequency": "*/1 * * * *", "action": "create"}

        # Call URL
        response = await self.api_client.patch(url, json=payload)
        response_json = response.json()

        assert response.status_code == 200
        scheduler_remove_job_mock.assert_called_once()
        mongo_controller_upsert_mock.assert_called_once()
        assert payload["frequency"] == response_json["frequency"]
        assert payload["action"] == response_json["action"]
        assert response_json["id"] is not None

    @patch('napps.kytos.mef_eline.main.Main._find_evc_by_schedule_id')
    async def test_update_no_schedule(
        self, find_evc_by_schedule_id_mock, event_loop
    ):
        """Test update a circuit schedule."""
        self.napp.controller.loop = event_loop
        url = f"{self.base_endpoint}/v2/evc/schedule/1"
        payload = {"frequency": "*/1 * * * *", "action": "create"}

        find_evc_by_schedule_id_mock.return_value = None, None

        response = await self.api_client.patch(url, json=payload)
        assert response.status_code == 404

    @patch("napps.kytos.mef_eline.scheduler.Scheduler.add")
    @patch("napps.kytos.mef_eline.main.Main._uni_from_dict")
    @patch("napps.kytos.mef_eline.main.EVC.as_dict")
    @patch("napps.kytos.mef_eline.models.evc.EVC._validate")
    async def test_update_schedule_archived(
        self,
        validate_mock,
        evc_as_dict_mock,
        uni_from_dict_mock,
        sched_add_mock,
        event_loop
    ):
        """Test create a circuit schedule."""
        self.napp.controller.loop = event_loop
        mongo_payload_1 = {
            "circuits": {
                "aa:aa:aa": {
                    "id": "aa:aa:aa",
                    "name": "my evc1",
                    "archived": True,
                    "circuit_scheduler": [
                        {
                            "id": "1",
                            "frequency": "* * * * *",
                            "action": "create"
                        }
                    ],
                }
            }
        }

        validate_mock.return_value = True
        sched_add_mock.return_value = True
        uni_from_dict_mock.side_effect = ["uni_a", "uni_z"]
        evc_as_dict_mock.return_value = {}
        self.napp.mongo_controller.get_circuits.return_value = mongo_payload_1

        requested_schedule_id = "1"
        url = f"{self.base_endpoint}/v2/evc/schedule/{requested_schedule_id}"

        payload = {"frequency": "*/1 * * * *", "action": "create"}

        # Call URL
        response = await self.api_client.patch(url, json=payload)
        assert response.status_code == 409

    @patch("apscheduler.schedulers.background.BackgroundScheduler.remove_job")
    @patch("napps.kytos.mef_eline.main.Main._uni_from_dict")
    @patch("napps.kytos.mef_eline.controllers.ELineController.upsert_evc")
    @patch("napps.kytos.mef_eline.main.EVC.as_dict")
    @patch("napps.kytos.mef_eline.models.evc.EVC._validate")
    async def test_delete_schedule(self, *args):
        """Test create a circuit schedule."""
        (
            validate_mock,
            evc_as_dict_mock,
            mongo_controller_upsert_mock,
            uni_from_dict_mock,
            scheduler_remove_job_mock,
        ) = args

        mongo_payload_1 = {
            "circuits": {
                "2": {
                    "id": "2",
                    "name": "my evc1",
                    "uni_a": {
                        "interface_id": "00:00:00:00:00:00:00:01:1",
                        "tag": {"tag_type": 1, "value": 80},
                    },
                    "uni_z": {
                        "interface_id": "00:00:00:00:00:00:00:02:2",
                        "tag": {"tag_type": 1, "value": 1},
                    },
                    "circuit_scheduler": [
                        {
                            "id": "1",
                            "frequency": "* * * * *",
                            "action": "create"
                        }
                    ],
                }
            }
        }
        validate_mock.return_value = True
        mongo_controller_upsert_mock.return_value = True
        uni_from_dict_mock.side_effect = ["uni_a", "uni_z"]
        evc_as_dict_mock.return_value = {}
        self.napp.mongo_controller.get_circuits.return_value = mongo_payload_1
        scheduler_remove_job_mock.return_value = True

        requested_schedule_id = "1"
        url = f"{self.base_endpoint}/v2/evc/schedule/{requested_schedule_id}"

        # Call URL
        response = await self.api_client.delete(url)

        assert response.status_code == 200
        scheduler_remove_job_mock.assert_called_once()
        mongo_controller_upsert_mock.assert_called_once()
        assert "Schedule removed" in f"{response.json()}"

    @patch("napps.kytos.mef_eline.main.Main._uni_from_dict")
    @patch("napps.kytos.mef_eline.main.EVC.as_dict")
    @patch("napps.kytos.mef_eline.models.evc.EVC._validate")
    async def test_delete_schedule_archived(self, *args):
        """Test create a circuit schedule."""
        (
            validate_mock,
            evc_as_dict_mock,
            uni_from_dict_mock,
        ) = args

        mongo_payload_1 = {
            "circuits": {
                "2": {
                    "id": "2",
                    "name": "my evc1",
                    "archived": True,
                    "circuit_scheduler": [
                        {
                            "id": "1",
                            "frequency": "* * * * *",
                            "action": "create"
                        }
                    ],
                }
            }
        }

        validate_mock.return_value = True
        uni_from_dict_mock.side_effect = ["uni_a", "uni_z"]
        evc_as_dict_mock.return_value = {}
        self.napp.mongo_controller.get_circuits.return_value = mongo_payload_1

        requested_schedule_id = "1"
        url = f"{self.base_endpoint}/v2/evc/schedule/{requested_schedule_id}"

        # Call URL
        response = await self.api_client.delete(url)
        assert response.status_code == 409

    @patch('napps.kytos.mef_eline.main.Main._find_evc_by_schedule_id')
    async def test_delete_schedule_not_found(self, mock_find_evc_by_sched):
        """Test delete a circuit schedule - unexisting."""
        mock_find_evc_by_sched.return_value = (None, False)
        url = f'{self.base_endpoint}/v2/evc/schedule/1'
        response = await self.api_client.delete(url)
        assert response.status_code == 404

    def test_get_evcs_by_svc_level(self) -> None:
        """Test get_evcs_by_svc_level."""
        levels = [1, 2, 4, 2, 7]
        evcs = {i: MagicMock(service_level=v, creation_time=1)
                for i, v in enumerate(levels)}
        self.napp.circuits = evcs
        expected_levels = sorted(levels, reverse=True)
        evcs_by_level = self.napp.get_evcs_by_svc_level()
        assert evcs_by_level

        for evc, exp_level in zip(evcs_by_level, expected_levels):
            assert evc.service_level == exp_level

        evcs = {i: MagicMock(service_level=1, creation_time=i)
                for i in reversed(range(2))}
        self.napp.circuits = evcs
        evcs_by_level = self.napp.get_evcs_by_svc_level()
        for i in range(2):
            assert evcs_by_level[i].creation_time == i

    async def test_get_circuit_not_found(self):
        """Test /v2/evc/<circuit_id> 404."""
        self.napp.mongo_controller.get_circuit.return_value = None
        url = f'{self.base_endpoint}/v2/evc/1234'
        response = await self.api_client.get(url)
        assert response.status_code == 404

    @patch('requests.post')
    @patch('napps.kytos.mef_eline.scheduler.Scheduler.add')
    @patch("napps.kytos.mef_eline.controllers.ELineController.upsert_evc")
    @patch('napps.kytos.mef_eline.models.evc.EVC._validate')
    @patch('kytos.core.Controller.get_interface_by_id')
    @patch('napps.kytos.mef_eline.models.path.Path.is_valid')
    @patch('napps.kytos.mef_eline.models.evc.EVCDeploy.deploy')
    @patch('napps.kytos.mef_eline.main.Main._uni_from_dict')
    @patch('napps.kytos.mef_eline.main.EVC.as_dict')
    async def test_update_circuit(
        self,
        evc_as_dict_mock,
        uni_from_dict_mock,
        evc_deploy,
        _is_valid_mock,
        interface_by_id_mock,
        _mock_validate,
        _mongo_controller_upsert_mock,
        _sched_add_mock,
        requests_mock,
        event_loop,
    ):
        """Test update a circuit circuit."""
        self.napp.controller.loop = event_loop
        interface_by_id_mock.return_value = get_uni_mocked().interface
        unis = [
            get_uni_mocked(switch_dpid="00:00:00:00:00:00:00:01"),
            get_uni_mocked(switch_dpid="00:00:00:00:00:00:00:02"),
        ]
        uni_from_dict_mock.side_effect = 2 * unis

        response = MagicMock()
        response.status_code = 201
        requests_mock.return_value = response

        payloads = [
            {
                "name": "my evc1",
                "uni_a": {
                    "interface_id": "00:00:00:00:00:00:00:01:1",
                    "tag": {"tag_type": 1, "value": 80},
                },
                "uni_z": {
                    "interface_id": "00:00:00:00:00:00:00:02:2",
                    "tag": {"tag_type": 1, "value": 1},
                },
                "dynamic_backup_path": True,
            },
            {
                "primary_path": [
                    {
                        "endpoint_a": {"id": "00:00:00:00:00:00:00:01:1"},
                        "endpoint_b": {"id": "00:00:00:00:00:00:00:02:2"},
                    }
                ]
            },
            {
                "sb_priority": 3
            },
            {
                # It works only with 'enable' and not with 'enabled'
                "enable": True
            },
            {
                "name": "my evc1",
                "active": True,
                "enable": True,
                "uni_a": {
                    "interface_id": "00:00:00:00:00:00:00:01:1",
                    "tag": {
                        "tag_type": 1,
                        "value": 80
                    }
                },
                "uni_z": {
                    "interface_id": "00:00:00:00:00:00:00:02:2",
                    "tag": {
                        "tag_type": 1,
                        "value": 1
                    }
                },
                "priority": 3,
                "bandwidth": 1000,
                "dynamic_backup_path": True
            }
        ]

        evc_as_dict_mock.return_value = payloads[0]
        response = await self.api_client.post(
            f"{self.base_endpoint}/v2/evc/",
            json=payloads[0],
        )
        assert 201 == response.status_code

        evc_deploy.reset_mock()
        evc_as_dict_mock.return_value = payloads[1]
        current_data = response.json()
        circuit_id = current_data["circuit_id"]
        response = await self.api_client.patch(
            f"{self.base_endpoint}/v2/evc/{circuit_id}",
            json=payloads[1],
        )
        # evc_deploy.assert_called_once()
        assert 200 == response.status_code

        evc_deploy.reset_mock()
        evc_as_dict_mock.return_value = payloads[2]
        response = await self.api_client.patch(
            f"{self.base_endpoint}/v2/evc/{circuit_id}",
            json=payloads[2],
        )
        evc_deploy.assert_not_called()
        assert 200 == response.status_code

        evc_deploy.reset_mock()
        evc_as_dict_mock.return_value = payloads[3]
        response = await self.api_client.patch(
            f"{self.base_endpoint}/v2/evc/{circuit_id}",
            json=payloads[3],
        )
        evc_deploy.assert_called_once()
        assert 200 == response.status_code

        evc_deploy.reset_mock()
        response = await self.api_client.patch(
            f"{self.base_endpoint}/v2/evc/{circuit_id}",
            content=b'{"priority":5,}',
            headers={"Content-Type": "application/json"}
        )
        evc_deploy.assert_not_called()
        assert 400 == response.status_code

        response = await self.api_client.patch(
            f"{self.base_endpoint}/v2/evc/1234",
            json=payloads[1],
        )
        current_data = response.json()
        expected_data = "circuit_id 1234 not found"
        assert current_data["description"] == expected_data
        assert 404 == response.status_code

        await self.api_client.delete(
            f"{self.base_endpoint}/v2/evc/{circuit_id}"
        )
        evc_deploy.reset_mock()
        response = await self.api_client.patch(
            f"{self.base_endpoint}/v2/evc/{circuit_id}",
            json=payloads[1],
        )
        evc_deploy.assert_not_called()
        assert 409 == response.status_code
        assert "Can't update archived EVC" in response.json()["description"]

    @patch("napps.kytos.mef_eline.models.evc.EVC.deploy")
    @patch("napps.kytos.mef_eline.scheduler.Scheduler.add")
    @patch("napps.kytos.mef_eline.main.Main._uni_from_dict")
    @patch("napps.kytos.mef_eline.controllers.ELineController.upsert_evc")
    @patch("napps.kytos.mef_eline.models.evc.EVC._validate")
    @patch("napps.kytos.mef_eline.main.EVC.as_dict")
    async def test_update_circuit_invalid_json(
        self,
        evc_as_dict_mock,
        validate_mock,
        mongo_controller_upsert_mock,
        uni_from_dict_mock,
        sched_add_mock,
        evc_deploy_mock,
        event_loop
    ):
        """Test update a circuit circuit."""
        self.napp.controller.loop = event_loop
        validate_mock.return_value = True
        mongo_controller_upsert_mock.return_value = True
        sched_add_mock.return_value = True
        evc_deploy_mock.return_value = True
        uni1 = create_autospec(UNI)
        uni2 = create_autospec(UNI)
        uni1.interface = create_autospec(Interface)
        uni2.interface = create_autospec(Interface)
        uni1.interface.switch = MagicMock()
        uni1.interface.switch.return_value = "00:00:00:00:00:00:00:01"
        uni1.interface.switch.is_enabled.return_value = True
        uni2.interface.switch = MagicMock()
        uni2.interface.switch.return_value = "00:00:00:00:00:00:00:02"
        uni2.interface.switch.is_enabled.return_value = True
        uni_from_dict_mock.side_effect = [uni1, uni2, uni1, uni2]

        payload1 = {
            "name": "my evc1",
            "uni_a": {
                "interface_id": "00:00:00:00:00:00:00:01:1",
                "tag": {"tag_type": 1, "value": 80},
            },
            "uni_z": {
                "interface_id": "00:00:00:00:00:00:00:02:2",
                "tag": {"tag_type": 1, "value": 1},
            },
            "dynamic_backup_path": True,
        }

        payload2 = {
            "dynamic_backup_path": False,
        }

        evc_as_dict_mock.return_value = payload1
        response = await self.api_client.post(
            f"{self.base_endpoint}/v2/evc/",
            json=payload1
        )
        assert 201 == response.status_code

        evc_as_dict_mock.return_value = payload2
        current_data = response.json()
        circuit_id = current_data["circuit_id"]
        response = await self.api_client.patch(
            f"{self.base_endpoint}/v2/evc/{circuit_id}",
            json=payload2
        )
        current_data = response.json()
        assert 400 == response.status_code
        assert "must have a primary path or" in current_data["description"]

    @patch("napps.kytos.mef_eline.models.evc.EVC.deploy")
    @patch("napps.kytos.mef_eline.scheduler.Scheduler.add")
    @patch("napps.kytos.mef_eline.main.Main._uni_from_dict")
    @patch("napps.kytos.mef_eline.main.Main._link_from_dict")
    @patch("napps.kytos.mef_eline.controllers.ELineController.upsert_evc")
    @patch("napps.kytos.mef_eline.models.evc.EVC._validate")
    @patch("napps.kytos.mef_eline.main.EVC.as_dict")
    @patch("napps.kytos.mef_eline.models.path.Path.is_valid")
    async def test_update_circuit_invalid_path(
        self,
        is_valid_mock,
        evc_as_dict_mock,
        validate_mock,
        mongo_controller_upsert_mock,
        link_from_dict_mock,
        uni_from_dict_mock,
        sched_add_mock,
        evc_deploy_mock,
        event_loop
    ):
        """Test update a circuit circuit."""
        self.napp.controller.loop = event_loop
        is_valid_mock.side_effect = InvalidPath("error")
        validate_mock.return_value = True
        mongo_controller_upsert_mock.return_value = True
        sched_add_mock.return_value = True
        evc_deploy_mock.return_value = True
        link_from_dict_mock.return_value = 1
        uni1 = create_autospec(UNI)
        uni2 = create_autospec(UNI)
        uni1.interface = create_autospec(Interface)
        uni2.interface = create_autospec(Interface)
        uni1.interface.switch = MagicMock()
        uni1.interface.switch.return_value = "00:00:00:00:00:00:00:01"
        uni1.interface.switch.is_enabled.return_value = True
        uni2.interface.switch = MagicMock()
        uni2.interface.switch.return_value = "00:00:00:00:00:00:00:02"
        uni2.interface.switch.is_enabled.return_value = True
        uni_from_dict_mock.side_effect = [uni1, uni2, uni1, uni2]

        payload1 = {
            "name": "my evc1",
            "uni_a": {
                "interface_id": "00:00:00:00:00:00:00:01:1",
                "tag": {"tag_type": 1, "value": 80},
            },
            "uni_z": {
                "interface_id": "00:00:00:00:00:00:00:02:2",
                "tag": {"tag_type": 1, "value": 1},
            },
            "dynamic_backup_path": True,
        }

        payload2 = {
            "primary_path": [
                {
                    "endpoint_a": {"id": "00:00:00:00:00:00:00:01:1"},
                    "endpoint_b": {"id": "00:00:00:00:00:00:00:02:2"},
                }
            ]
        }

        evc_as_dict_mock.return_value = payload1
        response = await self.api_client.post(
            f"{self.base_endpoint}/v2/evc/",
            json=payload1,
        )
        assert 201 == response.status_code

        evc_as_dict_mock.return_value = payload2
        current_data = response.json()
        circuit_id = current_data["circuit_id"]
        response = await self.api_client.patch(
            f"{self.base_endpoint}/v2/evc/{circuit_id}",
            json=payload2,
        )
        current_data = response.json()
        expected_data = "primary_path is not a valid path: error"
        assert 400 == response.status_code
        assert current_data["description"] == expected_data

    def test_link_from_dict_non_existent_intf(self):
        """Test _link_from_dict non existent intf."""
        self.napp.controller.get_interface_by_id = MagicMock(return_value=None)
        link_dict = {
            "endpoint_a": {"id": "a"},
            "endpoint_b": {"id": "b"}
        }
        with pytest.raises(ValueError):
            self.napp._link_from_dict(link_dict)

    def test_uni_from_dict_non_existent_intf(self):
        """Test _link_from_dict non existent intf."""
        self.napp.controller.get_interface_by_id = MagicMock(return_value=None)
        uni_dict = {
            "interface_id": "aaa",
        }
        with pytest.raises(ValueError):
            self.napp._uni_from_dict(uni_dict)

    @patch("napps.kytos.mef_eline.models.evc.EVC.deploy")
    @patch("napps.kytos.mef_eline.scheduler.Scheduler.add")
    @patch("napps.kytos.mef_eline.main.Main._uni_from_dict")
    @patch("napps.kytos.mef_eline.models.evc.EVC._validate")
    @patch("napps.kytos.mef_eline.controllers.ELineController.upsert_evc")
    async def test_update_evc_no_json_mime(
        self,
        mongo_controller_upsert_mock,
        validate_mock,
        uni_from_dict_mock,
        sched_add_mock,
        evc_deploy_mock,
        event_loop
    ):
        """Test update a circuit with wrong mimetype."""
        self.napp.controller.loop = event_loop
        validate_mock.return_value = True
        sched_add_mock.return_value = True
        evc_deploy_mock.return_value = True
        uni1 = create_autospec(UNI)
        uni2 = create_autospec(UNI)
        uni1.interface = create_autospec(Interface)
        uni2.interface = create_autospec(Interface)
        uni1.interface.switch = MagicMock()
        uni1.interface.switch.return_value = "00:00:00:00:00:00:00:01"
        uni1.interface.switch.is_enabled.return_value = True
        uni2.interface.switch = MagicMock()
        uni2.interface.switch.return_value = "00:00:00:00:00:00:00:02"
        uni2.interface.switch.is_enabled.return_value = True
        uni_from_dict_mock.side_effect = [uni1, uni2, uni1, uni2]
        mongo_controller_upsert_mock.return_value = True

        payload1 = {
            "name": "my evc1",
            "uni_a": {
                "interface_id": "00:00:00:00:00:00:00:01:1",
                "tag": {"tag_type": 1, "value": 80},
            },
            "uni_z": {
                "interface_id": "00:00:00:00:00:00:00:02:2",
                "tag": {"tag_type": 1, "value": 1},
            },
            "dynamic_backup_path": True,
        }

        payload2 = {"dynamic_backup_path": False}

        response = await self.api_client.post(
            f"{self.base_endpoint}/v2/evc/",
            json=payload1,
        )
        assert 201 == response.status_code

        current_data = response.json()
        circuit_id = current_data["circuit_id"]
        response = await self.api_client.patch(
            f"{self.base_endpoint}/v2/evc/{circuit_id}", data=payload2
        )
        current_data = response.json()
        assert 415 == response.status_code
        assert "application/json" in current_data["description"]

    async def test_delete_no_evc(self):
        """Test delete when EVC does not exist."""
        url = f"{self.base_endpoint}/v2/evc/123"
        response = await self.api_client.delete(url)
        current_data = response.json()
        expected_data = "circuit_id 123 not found"
        assert current_data["description"] == expected_data
        assert 404 == response.status_code

    @patch("napps.kytos.mef_eline.models.evc.EVC.remove_current_flows")
    @patch("napps.kytos.mef_eline.models.evc.EVC.deploy")
    @patch("napps.kytos.mef_eline.scheduler.Scheduler.add")
    @patch("napps.kytos.mef_eline.main.Main._uni_from_dict")
    @patch("napps.kytos.mef_eline.controllers.ELineController.upsert_evc")
    @patch("napps.kytos.mef_eline.models.evc.EVC._validate")
    @patch("napps.kytos.mef_eline.main.EVC.as_dict")
    async def test_delete_archived_evc(
        self,
        evc_as_dict_mock,
        validate_mock,
        mongo_controller_upsert_mock,
        uni_from_dict_mock,
        sched_add_mock,
        evc_deploy_mock,
        remove_current_flows_mock,
        event_loop
    ):
        """Try to delete an archived EVC"""
        self.napp.controller.loop = event_loop
        validate_mock.return_value = True
        mongo_controller_upsert_mock.return_value = True
        sched_add_mock.return_value = True
        evc_deploy_mock.return_value = True
        remove_current_flows_mock.return_value = True
        uni1 = create_autospec(UNI)
        uni2 = create_autospec(UNI)
        uni1.interface = create_autospec(Interface)
        uni2.interface = create_autospec(Interface)
        uni1.interface.switch = MagicMock()
        uni1.interface.switch.return_value = "00:00:00:00:00:00:00:01"
        uni1.interface.switch.is_enabled.return_value = True
        uni2.interface.switch = MagicMock()
        uni2.interface.switch.return_value = "00:00:00:00:00:00:00:02"
        uni2.interface.switch.is_enabled.return_value = True
        uni_from_dict_mock.side_effect = [uni1, uni2, uni1, uni2]

        payload1 = {
            "name": "my evc1",
            "uni_a": {
                "interface_id": "00:00:00:00:00:00:00:01:1",
                "tag": {"tag_type": 1, "value": 80},
            },
            "uni_z": {
                "interface_id": "00:00:00:00:00:00:00:02:2",
                "tag": {"tag_type": 1, "value": 1},
            },
            "dynamic_backup_path": True,
        }

        evc_as_dict_mock.return_value = payload1
        response = await self.api_client.post(
            f"{self.base_endpoint}/v2/evc/",
            json=payload1
        )
        assert 201 == response.status_code

        current_data = response.json()
        circuit_id = current_data["circuit_id"]
        response = await self.api_client.delete(
            f"{self.base_endpoint}/v2/evc/{circuit_id}"
        )
        assert 200 == response.status_code

        response = await self.api_client.delete(
            f"{self.base_endpoint}/v2/evc/{circuit_id}"
        )
        current_data = response.json()
        expected_data = f"Circuit {circuit_id} already removed"
        assert current_data["description"] == expected_data
        assert 404 == response.status_code

    def test_handle_link_up(self):
        """Test handle_link_up method."""
        evc_mock = create_autospec(EVC)
        evc_mock.service_level, evc_mock.creation_time = 0, 1
        evc_mock.is_enabled = MagicMock(side_effect=[True, False, True])
        evc_mock.lock = MagicMock()
        type(evc_mock).archived = PropertyMock(
            side_effect=[True, False, False]
        )
        evcs = [evc_mock, evc_mock, evc_mock]
        event = KytosEvent(name="test", content={"link": "abc"})
        self.napp.circuits = dict(zip(["1", "2", "3"], evcs))
        self.napp.handle_link_up(event)
        evc_mock.handle_link_up.assert_called_once_with("abc")

    @patch("time.sleep", return_value=None)
    @patch("napps.kytos.mef_eline.main.settings")
    @patch("napps.kytos.mef_eline.main.emit_event")
    def test_handle_link_down(self, emit_event_mock, settings_mock, _):
        """Test handle_link_down method."""
        uni = create_autospec(UNI)
        evc1 = MagicMock(id="1", service_level=0, creation_time=1,
                         metadata="mock", _active="true", _enabled="true",
                         uni_a=uni, uni_z=uni)
        evc1.name = "name"
        evc1.is_affected_by_link.return_value = True
        evc1.handle_link_down.return_value = True
        evc1.failover_path = None
        evc2 = MagicMock(id="2", service_level=6, creation_time=1)
        evc2.is_affected_by_link.return_value = False
        evc3 = MagicMock(id="3", service_level=5, creation_time=1,
                         metadata="mock", _active="true", _enabled="true",
                         uni_a=uni, uni_z=uni)
        evc3.name = "name"
        evc3.is_affected_by_link.return_value = True
        evc3.handle_link_down.return_value = True
        evc3.failover_path = None
        evc4 = MagicMock(id="4", service_level=4, creation_time=1,
                         metadata="mock", _active="true", _enabled="true",
                         uni_a=uni, uni_z=uni)
        evc4.name = "name"
        evc4.is_affected_by_link.return_value = True
        evc4.is_failover_path_affected_by_link.return_value = False
        evc4.failover_path = ["2"]
        evc4.get_failover_flows.return_value = {
            "2": ["flow1", "flow2"],
            "3": ["flow3", "flow4", "flow5", "flow6"],
        }
        evc5 = MagicMock(id="5", service_level=7, creation_time=1)
        evc5.is_affected_by_link.return_value = True
        evc5.is_failover_path_affected_by_link.return_value = False
        evc5.failover_path = ["3"]
        evc5.get_failover_flows.return_value = {
            "4": ["flow7", "flow8"],
            "5": ["flow9", "flow10"],
        }
        link = MagicMock(id="123")
        event = KytosEvent(name="test", content={"link": link})
        self.napp.circuits = {"1": evc1, "2": evc2, "3": evc3, "4": evc4,
                              "5": evc5}
        settings_mock.BATCH_SIZE = 2
        self.napp.handle_link_down(event)

        assert evc5.service_level > evc4.service_level
        # evc5 batched flows should be sent first
        emit_event_mock.assert_has_calls([
            call(
                self.napp.controller,
                context="kytos.flow_manager",
                name="flows.install",
                content={
                    "dpid": "4",
                    "flow_dict": {"flows": ["flow7", "flow8"]},
                }
            ),
            call(
                self.napp.controller,
                context="kytos.flow_manager",
                name="flows.install",
                content={
                    "dpid": "5",
                    "flow_dict": {"flows": ["flow9", "flow10"]},
                }
            ),
            call(
                self.napp.controller,
                context="kytos.flow_manager",
                name="flows.install",
                content={
                    "dpid": "2",
                    "flow_dict": {"flows": ["flow1", "flow2"]},
                }
            ),
            call(
                self.napp.controller,
                context="kytos.flow_manager",
                name="flows.install",
                content={
                    "dpid": "3",
                    "flow_dict": {"flows": ["flow3", "flow4"]},
                }
            ),
            call(
                self.napp.controller,
                context="kytos.flow_manager",
                name="flows.install",
                content={
                    "dpid": "3",
                    "flow_dict": {"flows": ["flow5", "flow6"]},
                }
            ),
        ])
        event_name = "evc_affected_by_link_down"
        assert evc3.service_level > evc1.service_level
        # evc3 should be handled before evc1
        emit_event_mock.assert_has_calls([
            call(self.napp.controller, event_name, content={
                "link_id": "123",
                "evc_id": "3",
                "name": "name",
                "metadata": "mock",
                "active": "true",
                "enabled": "true",
                "uni_a": uni.as_dict(),
                "uni_z": uni.as_dict(),
            }),
            call(self.napp.controller, event_name, content={
                "link_id": "123",
                "evc_id": "1",
                "name": "name",
                "metadata": "mock",
                "active": "true",
                "enabled": "true",
                "uni_a": uni.as_dict(),
                "uni_z": uni.as_dict(),
            }),
        ])
        evc4.sync.assert_called_once()
        event_name = "redeployed_link_down"
        emit_event_mock.assert_has_calls([
            call(self.napp.controller, event_name, content={
                "evc_id": "4",
                "name": "name",
                "metadata": "mock",
                "active": "true",
                "enabled": "true",
                "uni_a": uni.as_dict(),
                "uni_z": uni.as_dict(),
            }),
        ])

    @patch("napps.kytos.mef_eline.main.emit_event")
    def test_handle_evc_affected_by_link_down(self, emit_event_mock):
        """Test handle_evc_affected_by_link_down method."""
        uni = create_autospec(UNI)
        evc1 = MagicMock(
            id="1",
            metadata="data_mocked",
            _active="true",
            _enabled="false",
            uni_a=uni,
            uni_z=uni,
        )
        evc1.name = "name_mocked"
        evc1.handle_link_down.return_value = True
        evc2 = MagicMock(
            id="2",
            metadata="mocked_data",
            _active="false",
            _enabled="true",
            uni_a=uni,
            uni_z=uni,
        )
        evc2.name = "mocked_name"
        evc2.handle_link_down.return_value = False
        self.napp.circuits = {"1": evc1, "2": evc2}

        event = KytosEvent(name="e1", content={
            "evc_id": "3",
            "link_id": "1",
        })
        self.napp.handle_evc_affected_by_link_down(event)
        emit_event_mock.assert_not_called()
        event.content["evc_id"] = "1"
        self.napp.handle_evc_affected_by_link_down(event)
        emit_event_mock.assert_called_with(
            self.napp.controller, "redeployed_link_down", content={
                "evc_id": "1",
                "name": "name_mocked",
                "metadata": "data_mocked",
                "active": "true",
                "enabled": "false",
                "uni_a": uni.as_dict(),
                "uni_z": uni.as_dict(),
            }
        )

        event.content["evc_id"] = "2"
        self.napp.handle_evc_affected_by_link_down(event)
        emit_event_mock.assert_called_with(
            self.napp.controller, "error_redeploy_link_down", content={
                "evc_id": "2",
                "name": "mocked_name",
                "metadata": "mocked_data",
                "active": "false",
                "enabled": "true",
                "uni_a": uni.as_dict(),
                "uni_z": uni.as_dict(),
            }
        )

    def test_handle_evc_deployed(self):
        """Test handle_evc_deployed method."""
        evc = create_autospec(EVC, id="1")
        evc.lock = MagicMock()
        self.napp.circuits = {"1": evc}

        event = KytosEvent(name="e1", content={"evc_id": "2"})
        self.napp.handle_evc_deployed(event)
        evc.setup_failover_path.assert_not_called()

        event.content["evc_id"] = "1"
        self.napp.handle_evc_deployed(event)
        evc.setup_failover_path.assert_called()

    async def test_add_metadata(self, event_loop):
        """Test method to add metadata"""
        self.napp.controller.loop = event_loop
        evc_mock = create_autospec(EVC)
        evc_mock.metadata = {}
        evc_mock.id = 1234
        self.napp.circuits = {"1234": evc_mock}

        payload = {"metadata1": 1, "metadata2": 2}
        response = await self.api_client.post(
            f"{self.base_endpoint}/v2/evc/1234/metadata",
            json=payload
        )

        assert response.status_code == 201
        evc_mock.extend_metadata.assert_called_with(payload)

    async def test_add_metadata_malformed_json(self, event_loop):
        """Test method to add metadata with a malformed json"""
        self.napp.controller.loop = event_loop
        payload = b'{"metadata1": 1, "metadata2": 2,}'
        response = await self.api_client.post(
            f"{self.base_endpoint}/v2/evc/1234/metadata",
            content=payload,
            headers={"Content-Type": "application/json"}
        )

        assert response.status_code == 400
        assert "Failed to deserialize" in response.json()["description"]

    async def test_add_metadata_no_body(self, event_loop):
        """Test method to add metadata with no body"""
        self.napp.controller.loop = event_loop
        response = await self.api_client.post(
            f"{self.base_endpoint}/v2/evc/1234/metadata"
        )
        assert response.status_code == 400
        assert response.json()["description"] == \
            "Missing required request body"

    async def test_add_metadata_no_evc(self, event_loop):
        """Test method to add metadata with no evc"""
        self.napp.controller.loop = event_loop
        payload = {"metadata1": 1, "metadata2": 2}
        response = await self.api_client.post(
            f"{self.base_endpoint}/v2/evc/1234/metadata",
            json=payload,
        )
        assert response.status_code == 404
        assert response.json()["description"] == \
            "circuit_id 1234 not found."

    async def test_add_metadata_wrong_content_type(self, event_loop):
        """Test method to add metadata with wrong content type"""
        self.napp.controller.loop = event_loop
        payload = {"metadata1": 1, "metadata2": 2}
        response = await self.api_client.post(
            f"{self.base_endpoint}/v2/evc/1234/metadata",
            data=payload,
            headers={"Content-Type": "application/xml"}
        )
        assert response.status_code == 415
        assert "application/xml" in response.json()["description"]

    async def test_get_metadata(self):
        """Test method to get metadata"""
        evc_mock = create_autospec(EVC)
        evc_mock.metadata = {'metadata1': 1, 'metadata2': 2}
        evc_mock.id = 1234
        self.napp.circuits = {"1234": evc_mock}

        response = await self.api_client.get(
            f"{self.base_endpoint}/v2/evc/1234/metadata",
        )
        assert response.status_code == 200
        assert response.json() == {"metadata": evc_mock.metadata}

    async def test_delete_metadata(self):
        """Test method to delete metadata"""
        evc_mock = create_autospec(EVC)
        evc_mock.metadata = {'metadata1': 1, 'metadata2': 2}
        evc_mock.id = 1234
        self.napp.circuits = {"1234": evc_mock}

        response = await self.api_client.delete(
            f"{self.base_endpoint}/v2/evc/1234/metadata/metadata1",
        )
        assert response.status_code == 200

    async def test_delete_metadata_no_evc(self):
        """Test method to delete metadata with no evc"""
        response = await self.api_client.delete(
            f"{self.base_endpoint}/v2/evc/1234/metadata/metadata1",
        )
        assert response.status_code == 404
        assert response.json()["description"] == \
            "circuit_id 1234 not found."

    @patch('napps.kytos.mef_eline.main.Main._load_evc')
    def test_load_all_evcs(self, load_evc_mock):
        """Test load_evcs method"""
        mock_circuits = {
            'circuits': {
                1: 'circuit_1',
                2: 'circuit_2',
                3: 'circuit_3',
                4: 'circuit_4'
            }
        }
        self.napp.mongo_controller.get_circuits.return_value = mock_circuits
        self.napp.circuits = {2: 'circuit_2', 3: 'circuit_3'}
        self.napp.load_all_evcs()
        load_evc_mock.assert_has_calls([call('circuit_1'), call('circuit_4')])

    @patch('napps.kytos.mef_eline.main.Main._evc_from_dict')
    def test_load_evc(self, evc_from_dict_mock):
        """Test _load_evc method"""
        # pylint: disable=protected-access
        # case 1: early return with ValueError exception
        evc_from_dict_mock.side_effect = ValueError("err")
        evc_dict = MagicMock()
        assert not self.napp._load_evc(evc_dict)

        # case2: archived evc
        evc = MagicMock()
        evc.archived = True
        evc_from_dict_mock.side_effect = None
        evc_from_dict_mock.return_value = evc
        assert not self.napp._load_evc(evc_dict)

        # case3: success creating
        evc.archived = False
        evc.id = 1
        self.napp.sched = MagicMock()

        result = self.napp._load_evc(evc_dict)
        assert result == evc
        evc.deactivate.assert_called()
        evc.sync.assert_called()
        self.napp.sched.add.assert_called_with(evc)
        assert self.napp.circuits[1] == evc

    def test_handle_flow_mod_error(self):
        """Test handle_flow_mod_error method"""
        flow = MagicMock()
        flow.cookie = 0xaa00000000000011
        event = MagicMock()
        event.content = {'flow': flow, 'error_command': 'add'}
        evc = create_autospec(EVC)
        evc.remove_current_flows = MagicMock()
        self.napp.circuits = {"00000000000011": evc}
        self.napp.handle_flow_mod_error(event)
        evc.remove_current_flows.assert_called_once()

    @patch("kytos.core.Controller.get_interface_by_id")
    def test_uni_from_dict(self, _get_interface_by_id_mock):
        """Test _uni_from_dict method."""
        # pylint: disable=protected-access
        # case1: early return on empty dict
        assert not self.napp._uni_from_dict(None)

        # case2: invalid interface raises ValueError
        _get_interface_by_id_mock.return_value = None
        uni_dict = {
            "interface_id": "00:01:1",
            "tag": {"tag_type": 1, "value": 81},
        }
        with pytest.raises(ValueError):
            self.napp._uni_from_dict(uni_dict)

        # case3: success creation
        uni_mock = get_uni_mocked(switch_id="00:01")
        _get_interface_by_id_mock.return_value = uni_mock.interface
        uni = self.napp._uni_from_dict(uni_dict)
        assert uni == uni_mock

        # case4: success creation without tag
        uni_mock.user_tag = None
        del uni_dict["tag"]
        uni = self.napp._uni_from_dict(uni_dict)
        assert uni == uni_mock

    def test_handle_flow_delete(self):
        """Test handle_flow_delete method"""
        flow = MagicMock()
        flow.cookie = 0xaa00000000000011
        event = MagicMock()
        event.content = {'flow': flow}
        evc = create_autospec(EVC)
        evc.set_flow_removed_at = MagicMock()
        self.napp.circuits = {"00000000000011": evc}
        self.napp.handle_flow_delete(event)
        evc.set_flow_removed_at.assert_called_once()

    async def test_add_bulk_metadata(self, event_loop):
        """Test add_bulk_metadata method"""
        self.napp.controller.loop = event_loop
        evc_mock = create_autospec(EVC)
        evc_mock.id = 1234
        self.napp.circuits = {"1234": evc_mock}
        payload = {
            "circuit_ids": ["1234"],
            "metadata1": 1,
            "metadata2": 2
        }
        response = await self.api_client.post(
            f"{self.base_endpoint}/v2/evc/metadata",
            json=payload
        )
        assert response.status_code == 201
        args = self.napp.mongo_controller.update_evcs.call_args[0]
        ids = payload.pop("circuit_ids")
        assert args[0] == ids
        assert args[1] == payload
        assert args[2] == "add"
        calls = self.napp.mongo_controller.update_evcs.call_count
        assert calls == 1
        evc_mock.extend_metadata.assert_called_with(payload)

    async def test_add_bulk_metadata_no_id(self, event_loop):
        """Test add_bulk_metadata with unknown evc id"""
        self.napp.controller.loop = event_loop
        evc_mock = create_autospec(EVC)
        evc_mock.id = 1234
        self.napp.circuits = {"1234": evc_mock}
        payload = {
            "circuit_ids": ["1234", "4567"]
        }
        response = await self.api_client.post(
            f"{self.base_endpoint}/v2/evc/metadata",
            json=payload
        )
        assert response.status_code == 404

    async def test_add_bulk_metadata_no_circuits(self, event_loop):
        """Test add_bulk_metadata without circuit_ids"""
        self.napp.controller.loop = event_loop
        evc_mock = create_autospec(EVC)
        evc_mock.id = 1234
        self.napp.circuits = {"1234": evc_mock}
        payload = {
            "metadata": "data"
        }
        response = await self.api_client.post(
            f"{self.base_endpoint}/v2/evc/metadata",
            json=payload
        )
        assert response.status_code == 400

    async def test_delete_bulk_metadata(self, event_loop):
        """Test delete_metadata method"""
        self.napp.controller.loop = event_loop
        evc_mock = create_autospec(EVC)
        evc_mock.id = 1234
        self.napp.circuits = {"1234": evc_mock}
        payload = {
            "circuit_ids": ["1234"]
        }
        response = await self.api_client.request(
            "DELETE",
            f"{self.base_endpoint}/v2/evc/metadata/metadata1",
            json=payload
        )
        assert response.status_code == 200
        args = self.napp.mongo_controller.update_evcs.call_args[0]
        assert args[0] == payload["circuit_ids"]
        assert args[1] == {"metadata1": ""}
        assert args[2] == "del"
        calls = self.napp.mongo_controller.update_evcs.call_count
        assert calls == 1
        assert evc_mock.remove_metadata.call_count == 1
