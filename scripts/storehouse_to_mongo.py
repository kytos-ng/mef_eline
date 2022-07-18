#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import glob
import pickle
import os
import sys
from typing import Any, List, Tuple
from napps.kytos.mef_eline.controllers import ELineController
from concurrent.futures import ThreadPoolExecutor, as_completed

eline_controller = ELineController()


def get_storehouse_dir() -> str:
    return os.environ["STOREHOUSE_NAMESPACES_DIR"]


def _list_boxes_files(namespace: str, storehouse_dir=get_storehouse_dir()) -> dict:
    """List boxes files given the storehouse dir."""
    if storehouse_dir.endswith(os.path.sep):
        storehouse_dir = storehouse_dir[:-1]
    return {
        file_name.split(os.path.sep)[-2]: file_name
        for file_name in glob.glob(f"{storehouse_dir}/{namespace}**/*", recursive=True)
    }


def _load_from_file(file_name) -> Any:
    with open(file_name, "rb") as load_file:
        return pickle.load(load_file)


def load_boxes_data(namespace: str) -> dict:
    """Load boxes data."""
    return {k: _load_from_file(v).data for k, v in _list_boxes_files(namespace).items()}


def load_mef_eline_evcs() -> List[dict]:
    """Load mef_eline evcs."""
    namespace = "kytos.mef_eline.circuits"
    content = load_boxes_data(namespace)
    if namespace not in content:
        return ([], [])

    content = content[namespace]

    evcs = []
    for evc in content.values():
        evcs.append(evc)

    return evcs


def insert_from_mef_eline_evcs(
    eline_controller=eline_controller,
) -> List[dict]:
    """Insert from mef_eline evcs."""
    loaded_evcs = load_mef_eline_evcs()

    insert_evcs = []
    with ThreadPoolExecutor(max_workers=len(loaded_evcs)) as executor:
        futures = [
            executor.submit(eline_controller.upsert_evc, evc)
            for evc in loaded_evcs
        ]
        for future in as_completed(futures):
            response = future.result()
            insert_evcs.append(response)

    return insert_evcs


if __name__ == "__main__":
    cmds = {
        "insert_evcs": insert_from_mef_eline_evcs,
        "load_evcs": lambda: json.dumps(load_mef_eline_evcs()),
    }
    try:
        cmd = os.environ["CMD"]
    except KeyError:
        print("Please set the 'CMD' env var.")
        sys.exit(1)
    try:
        for command in cmd.split(","):
            print(cmds[command]())
    except KeyError as e:
        print(
            f"Unknown cmd: {str(e)}. 'CMD' env var has to be one of these {list(cmds.keys())}."
        )
        sys.exit(1)
