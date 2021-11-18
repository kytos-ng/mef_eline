"""Module to help to create tests."""
from unittest.mock import Mock

from kytos.core import Controller
from kytos.core.common import EntityStatus
from kytos.core.config import KytosConfig
from kytos.core.interface import TAG, UNI, Interface
from kytos.core.link import Link
from kytos.core.switch import Switch


def get_controller_mock():
    """Return a controller mock."""
    options = KytosConfig().options["daemon"]
    controller = Controller(options)
    controller.log = Mock()
    return controller


def get_link_mocked(**kwargs):
    """Return a link mocked.

    Args:
        link_dict: Python dict returned after call link.as_dict()
    """
    switch_a = kwargs.get("switch_a", Switch("00:00:00:00:00:01"))
    switch_b = kwargs.get("switch_b", Switch("00:00:00:00:00:02"))

    endpoint_a = Interface(
        kwargs.get("endpoint_a_name", "eth0"),
        kwargs.get("endpoint_a_port", 1),
        switch_a,
    )
    endpoint_b = Interface(
        kwargs.get("endpoint_b_name", "eth1"),
        kwargs.get("endpoint_b_port", 2),
        switch_b,
    )
    link = Mock(spec=Link, endpoint_a=endpoint_a, endpoint_b=endpoint_b)
    link.endpoint_a.link = link
    link.endpoint_b.link = link
    link.as_dict.return_value = kwargs.get(
        "link_dict", {"id": kwargs.get("link_id", 1)}
    )

    link.status = kwargs.get("status", EntityStatus.DOWN)

    metadata = kwargs.get("metadata", {})

    def side_effect(key):
        """Mock Link get metadata."""
        return Mock(value=metadata.get(key))

    link.get_metadata = Mock(side_effect=side_effect)

    return link


def get_mocked_requests(_):
    """Mock requests.get."""
    return MockResponse(
        {
            "links": {
                "abc": {"active": False, "enabled": True},
                "def": {"active": True, "enabled": True},
            }
        },
        200,
    )


def get_uni_mocked(**kwargs):
    """Create an uni mocked.

    Args:
        interface_name(str): Interface name. Defaults to "eth1".
        interface_port(int): Interface pror. Defaults to 1.
        tag_type(int): Type of a tag. Defaults to 1.
        tag_value(int): Value of a tag. Defaults to 81
        is_valid(bool): Value returned by is_valid method.
                        Defaults to False.
    """
    interface_name = kwargs.get("interface_name", "eth1")
    interface_port = kwargs.get("interface_port", 1)
    tag_type = kwargs.get("tag_type", 1)
    tag_value = kwargs.get("tag_value", 81)
    is_valid = kwargs.get("is_valid", False)
    switch = Mock(spec=Switch)
    switch.id = kwargs.get("switch_id", "custom_switch_id")
    switch.dpid = kwargs.get("switch_dpid", "custom_switch_dpid")
    interface = Interface(interface_name, interface_port, switch)
    tag = TAG(tag_type, tag_value)
    uni = Mock(spec=UNI, interface=interface, user_tag=tag)
    uni.is_valid.return_value = is_valid
    uni.as_dict.return_value = {
        "interface_id": f"switch_mock:{interface_port}",
        "tag": tag.as_dict(),
    }
    return uni


class MockResponse:
    """
    Mock a requests response object.

    Just define a function and add the patch decorator to the test.
    Example:
    def mocked_requests_get(*args, **kwargs):
        return MockResponse({}, 200)
    @patch('requests.get', side_effect=mocked_requests_get)

    """

    def __init__(self, json_data, status_code):
        """Create mock response object with parameters.

        Args:
            json_data: JSON response content
            status_code: HTTP status code.
        """
        self.json_data = json_data
        self.status_code = status_code

    def json(self):
        """Return the response json data."""
        return self.json_data

    def __str__(self):
        return self.__class__.__name__
