#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import httpx
import concurrent.futures
from kytos.core.db import Mongo

BATCH_SIZE = 10
MEF_URL = "http://localhost:8181/api/kytos/mef_eline/v2/evc/"

def number_evcs_affected():
    mongo = Mongo()
    evcs_collection = mongo.client[mongo.db_name]["evcs"]
    n_documents = evcs_collection.count_documents({
        "$and": [
            {"$expr": {
                "$ne": ["$uni_a.tag.value", "$uni_z.tag.value"]
            }},
            {"$or":[
                {"$and":[
                    {"uni_a.tag.value": {"$type": "number"}},
                    {"uni_z.tag.value": {"$type": "number"}}
                ]},
                {"$and":[
                    {"uni_a.tag.value": {"$type": "number"}},
                    {"uni_z.tag.value": {"$eq": "untagged"}}
                ]},
                {"$and":[
                    {"uni_a.tag.value": {"$eq": "untagged"}},
                    {"uni_z.tag.value": {"$type": "number"}}
                ]}]
            },
            {"archived": {"$eq": False}}
        ]
    })
    print(f"There are {n_documents} that need to be redeploy")
    return

def _redeploy_evc(evc_id):
    response = httpx.patch(MEF_URL+evc_id+"/redeploy", timeout=60)
    if not response.status_code//100 == 2:
        print(f"EVC {evc_id} was not redeployed, error: {response.text}")
        return
    print(f"EVC {evc_id} was redeployed successfully.")

def redeploy_affected_evcs():
    mongo = Mongo()
    evcs_collection = mongo.client[mongo.db_name]["evcs"]
    documents = evcs_collection.find({
        "$and": [
            {"$expr": {
                "$ne": ["$uni_a.tag.value", "$uni_z.tag.value"]
            }},
            {"$or":[
                {"$and":[
                    {"uni_a.tag.value": {"$type": "number"}},
                    {"uni_z.tag.value": {"$type": "number"}}
                ]},
                {"$and":[
                    {"uni_a.tag.value": {"$type": "number"}},
                    {"uni_z.tag.value": {"$eq": "untagged"}}
                ]},
                {"$and":[
                    {"uni_a.tag.value": {"$eq": "untagged"}},
                    {"uni_z.tag.value": {"$type": "number"}}
                ]}]
            },
            {"archived": {"$eq": False}}
        ]
    })

    evc_ids: list[str] = []
    for evc in documents:
        evc_ids.append(evc["id"])
    print(f"{len(evc_ids)} EVCs to be redeploy.")
    print("Redeploying...")

    executor = concurrent.futures.ThreadPoolExecutor(BATCH_SIZE, "script:redeploy")
    executor.map(_redeploy_evc, evc_ids)
    executor.shutdown()

    print("Finnished redeploying EVCs")

    return 0

if __name__ == "__main__":
    cmds = {
        "number_evcs_affected": number_evcs_affected,
        "redeploy_affected_evcs": redeploy_affected_evcs,
    }
    try:
        cmd = os.environ["CMD"]
        command = cmds[cmd]
    except KeyError:
        print(
            f"Please set the 'CMD' env var. \nIt has to be one of these: {list(cmds.keys())}"
        )
        sys.exit(1)
        
    command()
    
