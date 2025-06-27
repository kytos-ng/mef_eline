import concurrent.futures
# Change to False so this script makes changes
DRY_RUN = True
# Batch size to redeploy EVCs with set_queue
BATCH_SIZE = 10

mef_eline = controller.napps[("kytos", "mef_eline")]
flow_manager = controller.napps[("kytos", "flow_manager")]


def list_cookies_with_set_queue(flow_manager) -> set[int]:
    """List unique mef_eline cookies from the flows collection
    where the set_queue action is set (incorrectly) as the last action
    with output action."""
    return set(
        map(
            lambda doc: int(doc["flow"]["cookie"].to_decimal()),
            filter(
                lambda doc: len(doc["flow"]["actions"]) > 1
                and doc["flow"]["actions"][-1]["action_type"] == "set_queue"
                and doc["flow"]["actions"][-2]["action_type"] == "output",
                flow_manager.flow_controller.db.flows.find(
                    {
                        "flow.owner": "mef_eline",
                        "flow.actions": {"$elemMatch": {"action_type": "set_queue"}},
                    }
                ),
            ),
        )
    )


def get_id_from_cookie(cookie) -> str:
    """Return the evc id given a cookie value."""
    evc_id = cookie & 0xFFFFFFFFFFFFFF
    return f"{evc_id:x}".zfill(14)


def redeploy_evc(evc_id):
    """Redeploy an EVC."""
    import httpx

    MEF_ELINE_URL = "http://localhost:8181/api/kytos/mef_eline/v2"
    url = f"{MEF_ELINE_URL}/evc/{evc_id}/redeploy"
    try:
        res = httpx.request("PATCH", url, timeout=30)
    except httpx.TimeoutException:
        print(f"Timeout while enabling EVC {evc_id}")
    if res.is_server_error or res.status_code in {424, 404, 409, 400}:
        print(f"Error disabling EVC {evc_id}: {res.text}")


dry_run_key = "WILL" if not DRY_RUN else "WOULD"

print("Checking EVCs with action_type set_queue...")
evc_ids = []
for cookie in list_cookies_with_set_queue(flow_manager):
    evc_ids.append(get_id_from_cookie(cookie))
print(f"It {dry_run_key} redeploy {len(evc_ids)} EVCs")

if not DRY_RUN:
    executor = concurrent.futures.ThreadPoolExecutor(BATCH_SIZE, "script:redeploy_evc")
    executor.map(redeploy_evc, evc_ids)
    executor.shutdown()

print("Finished!")
