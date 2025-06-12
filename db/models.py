"""Models for Mongo DB"""
# pylint: disable=unused-argument,invalid-name,unused-argument
# pylint: disable=no-self-argument,no-name-in-module

from datetime import datetime
from typing import Dict, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator


class DocumentBaseModel(BaseModel):
    """Base model for Mongo documents"""

    id: str = Field(None, alias="_id")
    inserted_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def model_dump(self, **kwargs) -> Dict:
        """Return a dictionary representation of the model"""
        values = super().model_dump(**kwargs)
        if "id" in values and values["id"]:
            values["_id"] = values["id"]
        if "exclude" in kwargs and "_id" in kwargs["exclude"]:
            del values["_id"]
        return values


class CircuitScheduleDoc(BaseModel):
    """EVC circuit schedule model"""

    id: str
    date: Optional[str] = None
    frequency: Optional[str] = None
    interval: Optional[int] = None
    action: str


class TAGDoc(BaseModel):
    """TAG model"""
    tag_type: str
    value: Union[int, str, list[list[int]]]
    mask_list: Optional[list[Union[str, int]]] = None

    @field_validator('value')
    def validate_value(cls, value):
        """Validate value when is a string"""
        if isinstance(value, list):
            return value
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value in ("any", "untagged"):
            return value
        raise ValueError(f"{value} is not allowed as {type(value)}. " +
                         "Allowed strings are 'any' and 'untagged'.")


class UNIDoc(BaseModel):
    """UNI model"""
    tag: Optional[TAGDoc] = None
    interface_id: str


class LinkConstraints(BaseModel):
    """LinkConstraints."""
    bandwidth: Optional[float] = None
    ownership: Optional[str] = None
    reliability: Optional[float] = None
    utilization: Optional[float] = None
    delay: Optional[float] = None
    priority: Optional[int] = None
    not_ownership: Optional[list[str]] = None


class PathConstraints(BaseModel):
    """Pathfinder Constraints."""
    spf_attribute: Optional[Literal["hop", "delay", "priority"]] = None
    spf_max_path_cost: Optional[float] = None
    mandatory_metrics: Optional[LinkConstraints] = None
    flexible_metrics: Optional[LinkConstraints] = None
    minimum_flexible_hits: Optional[int] = None
    undesired_links: Optional[list[str]] = None


class EVCUpdateDoc(DocumentBaseModel):
    """Base model when updating an EVC document"""
    uni_a: Optional[UNIDoc] = None
    uni_z: Optional[UNIDoc] = None
    name: Optional[str] = None
    request_time: Optional[datetime] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    queue_id: Optional[int] = None
    flow_removed_at: Optional[datetime] = None
    execution_rounds: Optional[int] = None
    bandwidth: Optional[int] = None
    primary_path: Optional[list] = None
    backup_path: Optional[list] = None
    primary_links: Optional[list] = None
    backup_links: Optional[list] = None
    dynamic_backup_path: Optional[bool] = None
    primary_constraints: Optional[PathConstraints] = None
    secondary_constraints: Optional[PathConstraints] = None
    owner: Optional[str] = None
    sb_priority: Optional[int] = None
    service_level: Optional[int] = None
    circuit_scheduler: Optional[list[CircuitScheduleDoc]] = None
    metadata: Optional[dict] = None
    enabled: Optional[bool] = None


class EVCBaseDoc(DocumentBaseModel):
    """Base model for EVC documents"""

    uni_a: UNIDoc
    uni_z: UNIDoc
    name: str
    request_time: Optional[datetime] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    queue_id: Optional[int] = None
    flow_removed_at: Optional[datetime] = None
    execution_rounds: int = 0
    bandwidth: int = 0
    primary_path: Optional[list] = None
    backup_path: Optional[list] = None
    current_path: Optional[list] = None
    failover_path: Optional[list] = None
    primary_links: Optional[list] = None
    backup_links: Optional[list] = None
    dynamic_backup_path: bool
    primary_constraints: Optional[PathConstraints] = None
    secondary_constraints: Optional[PathConstraints] = None
    creation_time: datetime
    owner: Optional[str] = None
    sb_priority: Optional[int] = None
    service_level: int = 0
    circuit_scheduler: list[CircuitScheduleDoc]
    archived: bool = False
    metadata: Dict = {}
    active: bool
    enabled: bool
    max_paths: Optional[int] = 2

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
            "failover_path": 1,
            "dynamic_backup_path": 1,
            "sb_priority": {"$ifNull": ["$sb_priority", "$priority", None]},
            "service_level": 1,
            "circuit_scheduler": 1,
            "archived": 1,
            "metadata": 1,
            "active": 1,
            "enabled": 1,
            "max_paths": 1,
            "execution_rounds": {"$ifNull": ["$execution_rounds", 0]},
            "owner": {"$ifNull": ["$owner", None]},
            "queue_id": {"$ifNull": ["$queue_id", None]},
            "primary_constraints": {"$ifNull": ["$primary_constraints", {}]},
            "secondary_constraints": {"$ifNull": ["$secondary_constraints",
                                      {}]},
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
            "flow_removed_at": {"$dateToString": {
                "format": time_fmt, "date": {
                    "$ifNull": ["$flow_removed_at", None]
                }
            }},
            "updated_at": {"$dateToString": {
                "format": time_fmt, "date": "$updated_at"
            }}
        }
