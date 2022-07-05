"""Models for Mongo DB"""

from datetime import date, datetime
from pathlib import Path
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


class DocumentBaseModel(BaseModel):
    """Base model for Mongo documents"""

    id: str = Field(None, alias="_id")
    inserted_at: Optional[datetime]
    updated_at: Optional[datetime]

    def dict(self, **kwargs) -> Dict:
        """Return a dictionary representation of the model"""
        values = super().dict(**kwargs)
        if "id" in values and values["id"]:
            values["_id"] = values["id"]
        if "exclude" in kwargs and "_id" in kwargs["exclude"]:
            del values["_id"]
        return values


class CircuitScheduleDoc(BaseModel):
    """EVC circuit schedule model"""

    id: str
    date: Optional[date]
    frequency: Optional[str]
    interval: Optional[int]
    action: str


class TAGDoc(BaseModel):
    tag_type: int
    value: int


class UNIDoc(BaseModel):
    """UNI model"""

    tag: Optional[TAGDoc]
    interface_id: str

        
class EVCBaseDoc(DocumentBaseModel):
    """Base model for EVC documents"""

    uni_a: UNIDoc
    uni_z: UNIDoc
    name: str
    start_date: Optional[datetime]
    end_date: Optional[datetime]
    queue_id: Optional[int]
    bandwidth: int = 0
    primary_path: Optional[List]
    backup_path: Optional[List]
    current_path: Optional[List]
    dynamic_backup_path: bool
    creation_time: datetime
    owner: Optional[str]
    priority: int
    circuit_scheduler: List[CircuitScheduleDoc]
    archived: bool = False
    metadata: Optional[Dict] = None
    active: bool
    enabled: bool
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @staticmethod
    def projection() -> Dict:
        """Base projection of EVCBaseDoc model."""
        return {
            "_id": 0,
            "id": 1,
            "uni_a": 1,
            "uni_z": 1,
            "name": 1,
            "start_date": 1,
            "end_date": 1,
            "queue_id": 1,
            "bandwidth": 1,
            "primary_path": 1,
            "backup_path": 1,
            "current_path": 1,
            "dynamic_backup_path": 1,
            "creation_time": 1,
            "owner": 1,
            "priority": 1,
            "circuit_scheduler": 1,
            "archived": 1,
            "metadata": 1,
            "active": 1,
            "enabled": 1,
        }