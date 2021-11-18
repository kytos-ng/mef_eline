"""Utility functions."""
from kytos.core.events import KytosEvent


def emit_event(controller, name, **kwargs):
    """Send an event when something happens with an EVC."""
    event_name = f"kytos/mef_eline.{name}"
    event = KytosEvent(name=event_name, content=kwargs)
    controller.buffers.app.put(event)


def compare_endpoint_trace(endpoint, vlan, trace):
    """Compare and endpoint with a trace step."""
    return (
        endpoint.switch.dpid == trace["dpid"]
        and endpoint.port_number == trace["port"]
        and vlan == trace["vlan"]
    )
