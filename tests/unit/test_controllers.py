"""Tests for the DB controller."""
from unittest.mock import MagicMock

from controllers import ELineController


class TestControllers():
    """Test DB Controllers"""

    def setup_method(self) -> None:
        """Setup method"""
        self.eline = ELineController(MagicMock())
        self.evc_dict = {
            "id": "1234",
            "uni_a": {
                "interface_id": "00:00:00:00:00:00:00:01:1",
                "tag": {
                    "tag_type": 'vlan',
                    "value": 200,
                }
            },
            "uni_z": {
                "interface_id": "00:00:00:00:00:00:00:02:2",
                "tag": {
                    "tag_type": 'vlan',
                    "value": 200,
                }
            },
            "name": "EVC 1",
            "dynamic_backup_path": True,
            "creation_time": "2022-05-06T21:34:10",
            "priority": 100,
            "active": False,
            "enabled": True,
            "circuit_scheduler": []
        }

    def test_bootstrap_indexes(self):
        """Test bootstrap_indexes"""
        self.eline.bootstrap_indexes()
        expected_indexes = [
            ("evcs", [("circuit_scheduler", 1)]),
            ("evcs", [("archived", 1)]),
        ]
        mock = self.eline.mongo.bootstrap_index
        assert mock.call_count == len(expected_indexes)

    def test_get_circuits(self):
        """Test get_circuits"""

        assert "circuits" in self.eline.get_circuits()
        assert self.eline.db.evcs.aggregate.call_count == 1

    def test_get_circuits_archived_false(self):
        """Test get_circuits with archive being false"""
        self.eline.get_circuits(archived=None)
        args = self.eline.db.evcs.aggregate.call_args[0][0][0]
        assert args["$match"] == {}

    def test_get_circuits_archived_true(self):
        """Test get_circuits with archive being true"""
        self.eline.get_circuits(archived="true")
        args = self.eline.db.evcs.aggregate.call_args[0][0][0]
        assert args["$match"] == {'archived': True}

    def test_get_circuits_metadata(self):
        """Test get_circuits with metadata"""
        metadata = {"metadata.test": "123"}
        self.eline.get_circuits(archived=True, metadata=metadata)
        args = self.eline.db.evcs.aggregate.call_args[0][0][0]
        assert args["$match"]["metadata.test"] == 123

    def test_upsert_evc(self):
        """Test upsert_evc"""

        self.eline.upsert_evc(self.evc_dict)
        assert self.eline.db.evcs.find_one_and_update.call_count == 1

    def test_update_evcs_metadata(self):
        """Test update_evcs_metadata"""
        circuit_ids = ["123", "456", "789"]
        metadata = {"info": "testing"}
        self.eline.update_evcs_metadata(circuit_ids, metadata, "add")
        arg = self.eline.db.evcs.bulk_write.call_args[0][0]
        assert len(arg) == 3
        assert self.eline.db.evcs.bulk_write.call_count == 1

    def test_update_evcs(self):
        """Test update_evcs"""
        evc2 = dict(self.evc_dict | {"id": "456"})
        self.eline.update_evcs([self.evc_dict, evc2])
        arg = self.eline.db.evcs.bulk_write.call_args[0][0]
        assert len(arg) == 2
        assert self.eline.db.evcs.bulk_write.call_count == 1
