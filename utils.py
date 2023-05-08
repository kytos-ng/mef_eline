"""Utility functions."""
from kytos.core.events import KytosEvent


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


def notify_link_available_tags(controller, link, src_func=None):
    """Notify link available tags."""
    emit_event(controller, "link_available_tags", content={
        "link": link,
        "src_func": src_func
    })


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


def get_vlan_tags_and_masks(start: int, end: int) -> list[tuple[int, int]]:
    """Get the minimum number of vlan/mask pairs for a given range."""
    limit = end + 1
    tags_and_masks = []
    while start < limit:
        divisor = max_power2_divisor(start)
        while divisor > limit - start:
            divisor //= 2
        tags_and_masks.append((start, 4096-divisor))
        start += divisor
    return tags_and_masks
