"""Tests for DB models."""
from unittest import TestCase
from pydantic import ValidationError

from db.models import EVCBaseDoc, DocumentBaseModel


class TestDBModels(TestCase):
    """Test the DB models"""

    def setUp(self):
        self.evc_dict = {
            "uni_a": {
                "interface_id": "00:00:00:00:00:00:00:04:1",
                "tag": {
                    "tag_type": 1,
                    "value": 100,
                }
            },
            "uni_z": {
                "interface_id": "00:00:00:00:00:00:00:02:3",
                "tag": {
                    "tag_type": 1,
                    "value": 100,
                }
            },
            "name": "EVC 2",
            "dynamic_backup_path": True,
            "creation_time": "2022-04-06T21:34:10",
            "priority": 81,
            "active": False,
            "enabled": False,
            "circuit_scheduler": []
        }

    def test_evcbasedoc(self):
        """Test EVCBaseDoc model"""

        evc = EVCBaseDoc(**self.evc_dict)
        assert evc.name == "EVC 2"

    def test_evcbasedoc_error(self):
        """Test failure EVCBaseDoc model creation"""

        self.evc_dict["queue_id"] = "error"

        with self.assertRaises(ValidationError):
            EVCBaseDoc(**self.evc_dict)

    def test_document_base_model_dict(self):
        """test_document_base_model_dict."""
        self.evc_dict["_id"] = "some_id"
        model = DocumentBaseModel(**self.evc_dict)
        assert "_id" not in model.dict(exclude={"_id"})
