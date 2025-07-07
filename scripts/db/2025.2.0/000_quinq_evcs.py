#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
import httpx

from kytos.core.db import Mongo


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

    evc_count = 0
    evc_ids: list[str] = []
    for evc in documents:
        evc_count += 1
        evc_ids.append(evc["id"])
    print(f"{evc_count} EVCs to be redeploy.")
    print("Redeploying...")

    evc_deleted_count = 0
    evc_not_deleted: list[str] = []
    MEF_URL = "http://localhost:8181/api/kytos/mef_eline/v2/evc/"
    for evc in evc_ids:
        response = httpx.patch(MEF_URL+evc+"/redeploy", timeout=60)
        if response.status_code//100 == 2:
            evc_deleted_count += 1

    if evc_count != evc_deleted_count:
        print("Not redeployed EVCs: ", evc_not_deleted)

    else:
        print("All EVCs were redeployed successfully.")

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
    
