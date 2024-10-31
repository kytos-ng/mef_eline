#!/usr/bin/env python
# -*- coding: utf-8 -*-
from kytos.core.db import Mongo


def update_default_queue_id(mongo: Mongo):
    db = mongo.client[mongo.db_name]
    return db.evcs.update_many(
        {"queue_id": None, "archived": False},
        { "$set": { "queue_id": -1 }}
    ).modified_count


def main() -> None:
    """Main function."""
    mongo = Mongo()
    count = update_default_queue_id(mongo)
    print(f"Change default queue_id from None to -1 updated: {count}")


if __name__ == "__main__":
    main()
