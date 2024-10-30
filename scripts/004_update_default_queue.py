#!/usr/bin/env python
# -*- coding: utf-8 -*-
from napps.kytos.mef_eline.controllers import ELineController


def update_default_queue_id():
    controller = ELineController()
    db = controller.db
    return db.evcs.update_many(
        {"queue_id": None, "archived": False},
        { "$set": { "queue_id": -1 }}
    ).modified_count


def main() -> None:
    """Main function."""
    count = update_default_queue_id()
    print(f"Change default queue_id from None to -1 updated: {count}")


if __name__ == "__main__":
    main()
