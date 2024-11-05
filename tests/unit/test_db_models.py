"""Tests for DB models."""
import pytest
from pydantic import ValidationError

from db.models import (DocumentBaseModel, EVCBaseDoc, EVCUpdateDoc,
                       LinkConstraints, TAGDoc)


class TestDBModels():
    """Test the DB models"""

    def setup_method(self):
        """Setup method."""
        self.evc_dict = {
            "uni_a": {
                "interface_id": "00:00:00:00:00:00:00:04:1",
                "tag": {
                    "tag_type": 'vlan',
                    "value": 100,
                },
            },
            "uni_z": {
                "interface_id": "00:00:00:00:00:00:00:02:3",
                "tag": {
                    "tag_type": 'vlan',
                    "value": 100,
                }
            },
            "name": "EVC 2",
            "dynamic_backup_path": True,
            "creation_time": "2022-04-06T21:34:10",
            "sb_priority": 81,
            "active": False,
            "enabled": False,
            "circuit_scheduler": [],
            "queue_id": None,
            "take_last": False,
        }
        self.evc_update = {
            "uni_a": {
                "interface_id": "00:00:00:00:00:00:00:04:1",
                "tag": {
                    "tag_type": 'vlan',
                    "value": 100,
                },
            },
            "uni_z": {
                "interface_id": "00:00:00:00:00:00:00:02:3",
                "tag": {
                    "tag_type": 'vlan',
                    "value": 100,
                }
            },
            "name": "EVC 2",
            "dynamic_backup_path": True,
            "sb_priority": 81,
            "enabled": False,
            "circuit_scheduler": [],
            "queue_id": None,
        }

    def test_evcbasedoc(self):
        """Test EVCBaseDoc model"""

        evc = EVCBaseDoc(**self.evc_dict)
        assert evc.name == "EVC 2"
        assert evc.uni_a.interface_id == "00:00:00:00:00:00:00:04:1"
        assert evc.uni_z.interface_id == "00:00:00:00:00:00:00:02:3"
        assert evc.dynamic_backup_path
        assert evc.sb_priority == 81
        assert evc.service_level == 0
        assert not evc.active
        assert not evc.enabled
        assert not evc.circuit_scheduler
        assert not evc.take_last

    def test_evcupdatedoc(self):
        """Test EVCUpdateDoc model"""
        evc = EVCUpdateDoc(**self.evc_update)
        assert evc.name == "EVC 2"
        assert evc.uni_a.interface_id == "00:00:00:00:00:00:00:04:1"
        assert evc.uni_z.interface_id == "00:00:00:00:00:00:00:02:3"
        assert evc.dynamic_backup_path
        assert evc.sb_priority == 81
        assert not evc.enabled
        assert not evc.circuit_scheduler

    def test_evcbasedoc_error(self):
        """Test failure EVCBaseDoc model creation"""

        self.evc_dict["queue_id"] = "error"

        with pytest.raises(ValidationError):
            EVCBaseDoc(**self.evc_dict)

    def test_document_base_model_dict(self):
        """test_document_base_model_dict."""
        self.evc_dict["_id"] = "some_id"
        model = DocumentBaseModel(**self.evc_dict)
        assert "_id" not in model.model_dump(exclude={"_id"})

    def test_tagdoc_value(self):
        """Test TAGDoc value restrictions"""
        tag_mask = {"tag_type": 'vlan', "value": "untagged"}
        tag = TAGDoc(**tag_mask)
        assert tag.tag_type == 'vlan'
        assert tag.value == "untagged"

        tag_mask = {"tag_type": 'vlan', "value": "any"}
        tag = TAGDoc(**tag_mask)
        assert tag.tag_type == 'vlan'
        assert tag.value == "any"

        tag_list = {"tag_type": 'vlan', "value": [[1, 10]]}
        tag = TAGDoc(**tag_list)
        assert tag.tag_type == 'vlan'
        assert tag.value == [[1, 10]]

    def test_tagdoc_fail(self):
        """Test TAGDoc value fail case"""
        tag_fail = {"tag_type": 'vlan', "value": "test_fail"}
        with pytest.raises(ValueError):
            TAGDoc(**tag_fail)

    @pytest.mark.parametrize(
        'attribute,acceptable_value',
        [
            ('bandwidth', 1.0),
            ('bandwidth', 1),
            ('ownership', 'Test A'),
            ('reliability', 0.9),
            ('reliability', 1),
            ('utilization', 30.0),
            ('utilization', 30),
            ('delay', 10.0),
            ('delay', 10),
            ('priority', 1),
            ('not_ownership', []),
            ('not_ownership', ['Test B']),
            ('not_ownership', ['Test B', 'Test C']),
        ]
    )
    def test_link_metrics(
        self,
        attribute,
        acceptable_value,
    ):
        """
        Test attributes of link constraints across
        various acceptable values
        """
        constraints = {
            attribute: acceptable_value
        }
        LinkConstraints(**constraints)

    @pytest.mark.parametrize(
        'attribute,unacceptable_value',
        [
            ('bandwidth', 'E'),
            ('reliability', 'D'),
            ('utilization', 'C'),
            ('delay', 'B'),
            ('priority', 'A'),
            ('not_ownership', 'Yo'),
        ]
    )
    def test_link_unacceptable_metrics(
        self,
        attribute,
        unacceptable_value,
    ):
        """
        Test attributes of link constraints across
        various unacceptable values
        """
        constraints = {
            attribute: unacceptable_value
        }
        with pytest.raises(ValidationError):
            LinkConstraints(**constraints)
