"""ELineController."""
# pylint: disable=unnecessary-lambda,invalid-name
import os
from datetime import datetime
from typing import Dict, Optional

import pymongo
from pymongo.collection import ReturnDocument
from pymongo.errors import AutoReconnect
from tenacity import retry_if_exception_type, stop_after_attempt, wait_random

from kytos.core import log
from kytos.core.db import Mongo
from kytos.core.retry import before_sleep, for_all_methods, retries
from napps.kytos.mef_eline.db.models import EVCBaseDoc


@for_all_methods(
    retries,
    stop=stop_after_attempt(
        int(os.environ.get("MONGO_AUTO_RETRY_STOP_AFTER_ATTEMPT", "3"))
    ),
    wait=wait_random(
        min=int(os.environ.get("MONGO_AUTO_RETRY_WAIT_RANDOM_MIN", "1")),
        max=int(os.environ.get("MONGO_AUTO_RETRY_WAIT_RANDOM_MAX", "1")),
    ),
    before_sleep=before_sleep,
    retry=retry_if_exception_type((AutoReconnect,)),
)
class ELineController:
    """E-Line Controller"""

    def __init__(self, get_mongo=lambda: Mongo()) -> None:
        self.mongo = get_mongo()
        self.db_client = self.mongo.client
        self.db = self.db_client[self.mongo.db_name]

    def bootstrap_indexes(self) -> None:
        """Bootstrap mef_eline relaeted indexes."""
        index_tuples = [
            ("evcs", [("circuit_scheduler.id", pymongo.ASCENDING)]),
            ("evcs", [("archived", pymongo.ASCENDING)]),
        ]
        for collection, keys in index_tuples:
            if self.mongo.bootstrap_index(collection, keys):
                log.info(
                    f"Created DB index {keys}, collection: {collection}"
                )

    def get_circuits(self, archived: Optional[bool] = False) -> Dict:
        """Get all circuits from database."""
        aggregation = []
        match_filters = {"$match": {}}
        if archived is not None:
            match_filters["$match"]["archived"] = archived
            aggregation.append(match_filters)

        aggregation.extend([
                {"$sort": {"_id": 1}},
                {"$project": EVCBaseDoc.projection()},
            ]
        )
        circuits = self.db.evcs.aggregate(aggregation)
        return {"circuits": {value["id"]: value for value in circuits}}

    def get_circuit(self, circuit_id: str) -> Optional[Dict]:
        """Get a circuit."""
        return self.db.evcs.find_one({"_id": circuit_id},
                                     EVCBaseDoc.projection())

    def upsert_evc(self, evc: Dict) -> Optional[Dict]:
        """Update or insert an EVC"""
        utc_now = datetime.utcnow()
        model = EVCBaseDoc(
            **{
                **evc,
                **{"_id": evc["id"], "updated_at": utc_now}
            }
        )
        updated = self.db.evcs.find_one_and_update(
            {"_id": evc["id"]},
            {
                "$set": model.dict(exclude={"inserted_at"}, exclude_none=True),
                "$setOnInsert": {"inserted_at": utc_now},
            },
            return_document=ReturnDocument.AFTER,
            upsert=True,
        )
        if updated is not None:
            return utc_now
        return updated

    def get_circuits_by_update_date(self, dt: datetime) -> Optional[Dict]:
        """Filter for EVCs where updated_at is lte to a given datetime"""
        return self.db.evcs.find(
            {
                "updated_at": {"$lte": dt}
            }
        )
