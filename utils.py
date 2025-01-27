"""Utility functions."""
from typing import Union

import httpx

from kytos.core.common import EntityStatus
from kytos.core.events import KytosEvent
from kytos.core.interface import UNI, Interface, TAGRange
from napps.kytos.mef_eline import settings
from napps.kytos.mef_eline.exceptions import DisabledSwitch, FlowModException


def map_evc_event_content(evc, **kwargs) -> dict:
    """Returns a set of values from evc to be used for content"""
    return kwargs | {"evc_id": evc.id,
                     "id": evc.id,
                     "name": evc.name,
                     "metadata": evc.metadata,
                     "active": evc._active,
                     "enabled": evc._enabled,
                     "uni_a": evc.uni_a.as_dict(),
                     "uni_z": evc.uni_z.as_dict()}


def emit_event(controller, name, context="kytos/mef_eline", content=None,
               timeout=None):
    """Send an event when something happens with an EVC."""
    event_name = f"{context}.{name}"
    event = KytosEvent(name=event_name, content=content)
    controller.buffers.app.put(event, timeout=timeout)


def merge_flow_dicts(
    dst: dict[str, list], *srcs: dict[str, list]
) -> dict[str, list]:
    """Merge srcs dict flows into dst."""
    for src in srcs:
        for k, v in src.items():
            if k not in dst:
                dst[k] = v
            else:
                dst[k].extend(v)
    return dst


async def aemit_event(controller, name, content):
    """Send an asynchronous event"""
    event = KytosEvent(name=name, content=content)
    await controller.buffers.app.aput(event)


def compare_endpoint_trace(endpoint, vlan, trace):
    """Compare and endpoint with a trace step."""
    if vlan and "vlan" in trace:
        return (
            endpoint.switch.dpid == trace["dpid"]
            and endpoint.port_number == trace["port"]
            and vlan == trace["vlan"]
        )
    return (
        endpoint.switch.dpid == trace["dpid"]
        and endpoint.port_number == trace["port"]
    )


def map_dl_vlan(value: Union[str, int]) -> bool:
    """Map dl_vlan value with the following criteria:
    dl_vlan = untagged or 0 -> None
    dl_vlan = any or "4096/4096" -> 1
    dl_vlan = "num1/num2" -> int in [1, 4095]"""
    special_untagged = {"untagged", 0}
    if value in special_untagged:
        return None
    special_any = {"any": 1, "4096/4096": 1}
    value = special_any.get(value, value)
    if isinstance(value, int):
        return value
    value, mask = map(int, value.split('/'))
    return value & (mask & 4095)


def compare_uni_out_trace(
    tag_value: Union[None, int, str],
    interface: Interface,
    trace: dict
) -> bool:
    """Check if the trace last step (output) matches the UNI attributes."""
    # keep compatibility for old versions of sdntrace-cp
    if "out" not in trace:
        return True
    if not isinstance(trace["out"], dict):
        return False
    uni_vlan = map_dl_vlan(tag_value) if tag_value else None
    return (
        interface.port_number == trace["out"].get("port")
        and uni_vlan == trace["out"].get("vlan")
    )


def max_power2_divisor(number: int, limit: int = 4096) -> int:
    """Get the max power of 2 that is divisor of number"""
    while number % limit > 0:
        limit //= 2
    return limit


def get_vlan_tags_and_masks(tag_ranges: list[list[int]]) -> list[int, str]:
    """Get a list of vlan/mask pairs for a given list of ranges."""
    masks_list = []
    for start, end in tag_ranges:
        limit = end + 1
        while start < limit:
            divisor = max_power2_divisor(start)
            while divisor > limit - start:
                divisor //= 2
            mask = 4096 - divisor
            if mask == 4095:
                masks_list.append(start)
            else:
                masks_list.append(f"{start}/{mask}")
            start += divisor
    return masks_list


def check_disabled_component(uni_a: UNI, uni_z: UNI):
    """Check if a switch or an interface is disabled"""
    if uni_a.interface.switch != uni_z.interface.switch:
        return
    if uni_a.interface.switch.status == EntityStatus.DISABLED:
        dpid = uni_a.interface.switch.dpid
        raise DisabledSwitch(f"Switch {dpid} is disabled")
    if uni_a.interface.status == EntityStatus.DISABLED:
        id_ = uni_a.interface.id
        raise DisabledSwitch(f"Interface {id_} is disabled")
    if uni_z.interface.status == EntityStatus.DISABLED:
        id_ = uni_z.interface.id
        raise DisabledSwitch(f"Interface {id_} is disabled")


def make_uni_list(list_circuits: list) -> list:
    """Make uni list to be sent to sdntrace"""
    uni_list = []
    for circuit in list_circuits:
        if isinstance(circuit.uni_a.user_tag, TAGRange):
            # TAGRange value from uni_a and uni_z are currently mirrored
            mask_list = (circuit.uni_a.user_tag.mask_list or
                         circuit.uni_z.user_tag.mask_list)
            for mask in mask_list:
                uni_list.append((circuit.uni_a.interface, mask))
                uni_list.append((circuit.uni_z.interface, mask))
        else:
            tag_a = None
            if circuit.uni_a.user_tag:
                tag_a = circuit.uni_a.user_tag.value
            uni_list.append(
                (circuit.uni_a.interface, tag_a)
            )
            tag_z = None
            if circuit.uni_z.user_tag:
                tag_z = circuit.uni_z.user_tag.value
            uni_list.append(
                (circuit.uni_z.interface, tag_z)
            )
    return uni_list


def send_flow_mods_event(
    controller, flow_dict: dict[str, list], action: str, force=True
):
    """Send flow mods to be deleted or install to flow_manager
     through an event"""
    for dpid, flows in flow_dict.items():
        emit_event(
            controller,
            context="kytos.flow_manager",
            name=f"flows.{action}",
            content={
                "dpid": dpid,
                "flow_dict": {"flows": flows},
                "force": force,
            },
        )


def send_flow_mods_http(
    flow_dict: dict[str, list],
    action: str, force=True
):
    """
    Send a flow_mod list to a specific switch.

    Args:
        dpid(str): The target of flows (i.e. Switch.id).
        flow_mods(dict): Python dictionary with flow_mods.
        command(str): By default is 'flows'. To remove a flow is 'remove'.
        force(bool): True to send via consistency check in case of errors.
        by_switch(bool): True to send to 'flows_by_switch' request instead.
    """
    endpoint = f"{settings.MANAGER_URL}/flows_by_switch/?force={force}"

    formatted_dict = {
        dpid: {"flows": flows}
        for (dpid, flows) in flow_dict.items()
    }

    try:
        if action == "install":
            res = httpx.post(endpoint, json=formatted_dict, timeout=30)
        elif action == "delete":
            res = httpx.request(
                "DELETE", endpoint, json=formatted_dict, timeout=30
            )
    except httpx.RequestError as err:
        raise FlowModException(str(err)) from err
    if res.is_server_error or res.status_code >= 400:
        raise FlowModException(res.text)


def prepare_delete_flow(evc_flows: dict[str, list[dict]]):
    """Create flow mods suited for flow deletion."""
    dpid_flows: dict[str, list[dict]] = {}

    if not evc_flows:
        return dpid_flows

    for dpid, flows in evc_flows.items():
        dpid_flows.setdefault(dpid, [])
        for flow in flows:
            dpid_flows[dpid].append({
                "cookie": flow["cookie"],
                "match": flow["match"],
                "owner": "mef_eline",
                "cookie_mask": int(0xffffffffffffffff)
            })
    return dpid_flows
