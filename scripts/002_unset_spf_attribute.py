#!/usr/bin/env python
# -*- coding: utf-8 -*-
from napps.kytos.mef_eline.controllers import ELineController
import os
import sys
from typing import Iterable


def unset_primary_constraints_spf_attr(
    controller: ELineController, evc_ids: Iterable[str] = None
) -> int:
    """Unset primary_constraints.spf_attribute."""
    db = controller.db
    filter_expr = {"primary_constraints.spf_attribute": "hop"}
    if evc_ids:
        {"_id": {"$in": [evc_ids]}}
    return db.evcs.update_many(
        filter_expr,
        {"$unset": {"primary_constraints.spf_attribute": 1}},
    ).modified_count


def unset_secondary_constraints_spf_attr(
    controller: ELineController, evc_ids: Iterable[str] = None
) -> int:
    """Unset secondary_constraints.spf_attribute."""
    db = controller.db
    if evc_ids:
        {"_id": {"$in": [evc_ids]}}
    filter_expr = {"secondary_constraints.spf_attribute": "hop"}
    return db.evcs.update_many(
        filter_expr,
        {"$unset": {"secondary_constraints.spf_attribute": 1}},
    ).modified_count


def main() -> None:
    """Main function."""
    controller = ELineController()
    evc_ids = [e for e in os.getenv("EVC_IDS", "").split(",") if e]

    not_found = []
    circuits = controller.get_circuits()["circuits"]
    not_found = [e for e in evc_ids if e not in circuits]
    if not_found:
        print(
            f"The following evc_ids weren't found: {not_found}\n"
            f"Make sure that evc string in EVC_IDS is a valid evc_id "
            "and it's separated by a comma"
        )
        sys.exit(1)

    count = unset_primary_constraints_spf_attr(controller, evc_ids)
    print(f"Unset {count} primary_constraints spf_attribute, evc_ids: {evc_ids}")
    count = unset_secondary_constraints_spf_attr(controller, evc_ids)
    print(f"Unset {count} secondary_constraints spf_attribute, evc_ids: {evc_ids}")


if __name__ == "__main__":
    main()
