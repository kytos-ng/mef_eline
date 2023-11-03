#!/usr/bin/env python
# -*- coding: utf-8 -*-
import json
import sys
import logging

import argparse
import asyncio
import httpx

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


def is_symmetric_evpl(evc: dict) -> bool:
    """Check whether it's a symmetric (same UNIs vlans) evpl."""
    uni_a, uni_z = evc["uni_a"], evc["uni_z"]
    return (
        "tag" in uni_a
        and "tag" in uni_z
        and uni_a["tag"]["tag_type"] == "vlan"
        and uni_z["tag"]["tag_type"] == "vlan"
        and isinstance(uni_a["tag"]["value"], int)
        and isinstance(uni_z["tag"]["value"], int)
        and uni_a["tag"]["value"] == uni_z["tag"]["value"]
    )


async def redeploy(evc_id: str, base_url: str):
    """Redeploy."""
    endpoint = "/mef_eline/v2/evc"
    async with httpx.AsyncClient(base_url=base_url) as client:
        res = await client.patch(f"{endpoint}/{evc_id}/redeploy")
        logger.info(f"Redeployed evc_id {evc_id}")
        assert (
            res.status_code == 202
        ), f"failed to redeploy evc_id: {evc_id} {res.status_code} {res.text}"


async def list_symmetric_evpls(base_url: str, included_evcs_filter: str = "") -> dict:
    """List symmetric (same UNI vlan) evpls."""
    endpoint = "/mef_eline/v2/evc"
    async with httpx.AsyncClient(base_url=base_url) as client:
        resp = await client.get(endpoint, timeout=20)
        evcs = {
            evc_id: evc for evc_id, evc in resp.json().items() if is_symmetric_evpl(evc)
        }
        if included_evcs_filter:
            included = set(included_evcs_filter.split(","))
            evcs = {evc_id: evc for evc_id, evc in evcs.items() if evc_id in included}
        return evcs


async def update_command(args: argparse.Namespace) -> None:
    """update command.

    It'll list all symmetric EVPLs (same UNIs vlans) and redeploy them
    concurrently. The concurrency slot and wait time can be controlled with
    batch_size and batch_sleep_secs

    If any coroutine fails its exception will be bubbled up.
    """
    evcs = await list_symmetric_evpls(args.base_url, args.included_evcs_filter)
    coros = [redeploy(evc_id, args.base_url) for evc_id, evc in evcs.items()]
    batch_size = args.batch_size if args.batch_size > 0 else len(coros)
    batch_sleep = args.batch_sleep_secs if args.batch_sleep_secs >= 0 else 0

    logger.info(
        f"It'll redeploy {len(coros)} EVPL(s) using batch_size {batch_size} "
        f"and batch_sleep {batch_sleep}"
    )

    for i in range(0, len(coros), batch_size):
        sliced = coros[i : i + batch_size]
        if i > 0 and batch_sleep:
            logger.info(f"Sleeping for {batch_sleep}...")
            await asyncio.sleep(batch_sleep)
        await asyncio.gather(*sliced)


async def list_command(args: argparse.Namespace) -> None:
    """list command."""
    evcs = await list_symmetric_evpls(args.base_url, args.included_evcs_filter)
    evcs = {
        evc_id: {
            "name": evc["name"],
            "uni_a": evc["uni_a"],
            "uni_z": evc["uni_z"],
        }
        for evc_id, evc in evcs.items()
    }
    print(json.dumps(evcs))


async def main() -> None:
    """Main function."""
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(title="commands", dest="command")

    update_parser = subparsers.add_parser("update", help="Update command")
    update_parser.add_argument(
        "--batch_sleep_secs", type=int, help="Batch sleep in seconds", default=5
    )
    update_parser.add_argument("--batch_size", type=int, help="Batch size", default=10)
    update_parser.add_argument(
        "--included_evcs_filter",
        type=str,
        help="Included filtered EVC ids separated by comma",
        default="",
    )
    update_parser.add_argument(
        "--base_url",
        type=str,
        default="http://localhost:8181/api/kytos",
        help="Kytos-ng API base url",
    )

    list_parser = subparsers.add_parser("list", help="List command")
    list_parser.add_argument(
        "--base_url",
        type=str,
        default="http://localhost:8181/api/kytos",
        help="Kytos-ng API base url",
    )
    list_parser.add_argument(
        "--included_evcs_filter",
        type=str,
        help="Included filtered EVC ids separated by comma",
        default="",
    )
    args = parser.parse_args()

    try:
        if args.command == "update":
            await update_command(args)
        elif args.command == "list":
            await list_command(args)
    except (httpx.HTTPError, AssertionError) as exc:
        logger.exception(f"Error when running '{args.command}': {exc}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
