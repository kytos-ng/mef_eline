"""Utility functions."""
from kytos.core.common import EntityStatus
from kytos.core.events import KytosEvent
from kytos.core.interface import UNI
from napps.kytos.mef_eline.exceptions import DisabledSwitch


def map_evc_event_content(evc, **kwargs):
    """Returns a set of values from evc to be used for content"""
    return kwargs | {"evc_id": evc.id,
                     "name": evc.name,
                     "metadata": evc.metadata,
                     "active": evc._active,
                     "enabled": evc._enabled,
                     "uni_a": evc.uni_a.as_dict(),
                     "uni_z": evc.uni_z.as_dict()}


def emit_event(controller, name, context="kytos/mef_eline", content=None):
    """Send an event when something happens with an EVC."""
    event_name = f"{context}.{name}"
    event = KytosEvent(name=event_name, content=content)
    controller.buffers.app.put(event)


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


def map_dl_vlan(value):
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


def compare_uni_out_trace(uni, trace):
    """Check if the trace last step (output) matches the UNI attributes."""
    # keep compatibility for old versions of sdntrace-cp
    if "out" not in trace:
        return True
    if not isinstance(trace["out"], dict):
        return False
    uni_vlan = map_dl_vlan(uni.user_tag.value) if uni.user_tag else None
    return (
        uni.interface.port_number == trace["out"].get("port")
        and uni_vlan == trace["out"].get("vlan")
    )


def max_power2_divisor(number: int, limit: int = 4096) -> int:
    """Get the max power of 2 that is divisor of number"""
    while number % limit > 0:
        limit //= 2
    return limit


def get_vlan_tags_and_masks(tag_ranges: list[list[int]]) -> list[str]:
    """Get the minimum number of vlan/mask pairs for a given range."""
    masks_list = []
    for start, end in tag_ranges:
        limit = end + 1
        while start < limit:
            divisor = max_power2_divisor(start)
            while divisor > limit - start:
                divisor //= 2
            masks_list.append(f"{start}/{4096-divisor}")
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
