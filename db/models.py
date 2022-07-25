"""Models for Mongo DB"""
# pylint: disable=no-self-use,unused-argument,invalid-name,unused-argument
# pylint: disable=no-self-argument,no-name-in-module

from datetime import datetime
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
    date: Optional[str]
    frequency: Optional[str]
    interval: Optional[int]
    action: str


class TAGDoc(BaseModel):
    """TAG model"""
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
    request_time: Optional[datetime]
    start_date: Optional[datetime]
    end_date: Optional[datetime]
    queue_id: Optional[int]
    bandwidth: int = 0
    primary_path: Optional[List]
    backup_path: Optional[List]
    current_path: Optional[List]
    primary_links: Optional[List]
    backup_links: Optional[List]
    backup_links: Optional[List]
    dynamic_backup_path: bool
    creation_time: datetime
    owner: Optional[str]
    priority: int
    circuit_scheduler: List[CircuitScheduleDoc]
    archived: bool = False
    metadata: Optional[Dict] = None
    active: bool
    enabled: bool

    @staticmethod
    def projection() -> Dict:
        """Base projection of EVCBaseDoc model."""
        time_fmt = "%Y-%m-%dT%H:%M:%S"
        return {
            "_id": 0,
            "id": 1,
            "uni_a": 1,
            "uni_z": 1,
            "name": 1,
            "bandwidth": 1,
            "primary_path": 1,
            "backup_path": 1,
            "current_path": 1,
            "dynamic_backup_path": 1,
            "priority": 1,
            "circuit_scheduler": 1,
            "archived": 1,
            "metadata": 1,
            "active": 1,
            "enabled": 1,
            "owner": {"$ifNull": ["$owner", None]},
            "queue_id": {"$ifNull": ["$queue_id", None]},
            "primary_links": {"$ifNull": ["$primary_links", []]},
            "backup_links": {"$ifNull": ["$backup_links", []]},
            "start_date": {"$dateToString": {
                "format": time_fmt, "date": "$start_date"
            }},
            "creation_time": {"$dateToString": {
                "format": time_fmt, "date": "$creation_time"
            }},
            "request_time": {"$dateToString": {
                "format": time_fmt, "date": {
                    "$ifNull": ["$request_time", "$inserted_at"]
                }
            }},
            "end_date": {"$dateToString": {
                "format": time_fmt, "date": {
                    "$ifNull": ["$end_date", None]
                }
            }},
        }
