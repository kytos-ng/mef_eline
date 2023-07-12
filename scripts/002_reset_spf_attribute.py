#!/usr/bin/env python
# -*- coding: utf-8 -*-
from napps.kytos.mef_eline.controllers import ELineController
import os
import sys


def reset_primary_constraints_spf_attr(controller: ELineController, value: str) -> int:
    """Reset primary_constraints.spf_attribute."""
    db = controller.db
    return db.evcs.update_many(
        {"primary_constraints.spf_attribute": "hop"},
        {"$set": {"primary_constraints.spf_attribute": value}},
    ).modified_count


def reset_secondary_constraints_spf_attr(
    controller: ELineController, value: str
) -> int:
    """Reset secondary_constraints.spf_attribute."""
    db = controller.db
    return db.evcs.update_many(
        {"secondary_constraints.spf_attribute": "hop"},
        {"$set": {"secondary_constraints.spf_attribute": value}},
    ).modified_count


def main() -> None:
    """Main function."""
    controller = ELineController()
    value = os.getenv("SPF_ATTRIBUTE")
    expected_values = {"hop", "priority", "delay"}
    if not value or value not in expected_values:
        print(
            f"'SPF_ATTRIBUTE' env: '{value}', "
            f"expected one of these values: {expected_values}.\n"
            "Please, set the SPF_ATTRIBUTE env var."
        )
        sys.exit(1)

    count = reset_primary_constraints_spf_attr(controller, value)
    print(f"Updated {count} primary_constraints spf_attribute as {value}")
    count = reset_secondary_constraints_spf_attr(controller, value)
    print(f"Updated {count} secondary_constraints spf_attribute as {value}")


if __name__ == "__main__":
    main()
