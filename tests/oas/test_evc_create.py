"""
EVC creation test
"""
import os
import json
import requests


def test_required():
    """ test should_fail_due_to_missing_name_attribute_on_payload """
    actual_dir = os.getcwd()
    evc_params = actual_dir + "/tests/oas/evc_params.json"
    with open(evc_params, encoding="utf8") as json_file:
        json_data = json.load(json_file)
        json_file.close()
    url = json_data["url"]
    headers = json_data["headers"]
    payload = {
        "enabled": True,
        "uni_a": json_data["uni_a"],
        "uni_z": json_data["uni_z"],
        "bandwidth": json_data["bandwidth"],
        "dynamic_backup_path": True,
    }
    request_data = json.dumps(payload)
    response = requests.post(url=url, data=request_data, headers=headers)
    json_response = response.json()
    assert response.status_code == 400
    message = json.loads(json_response["description"]).get("message")
    assert "required" in message["error_validator"]


def test_additional_properties():
    """ test should_fail_due_to_additional_properties_on_payload """
    actual_dir = os.getcwd()
    evc_params = actual_dir + "/tests/oas/evc_params.json"
    with open(evc_params, encoding="utf8") as json_file:
        json_data = json.load(json_file)
        json_file.close()
    url = json_data["url"]
    headers = json_data["headers"]
    payload = {
        "name": "EVC_1",
        "enabled": True,
        "uni_a": json_data["uni_a"],
        "uni_z": json_data["uni_z"],
        "bandwidth": json_data["bandwidth"],
        "dynamic_backup_path": True,
        "active": True,
    }
    request_data = json.dumps(payload)
    response = requests.post(url=url, data=request_data, headers=headers)
    json_response = response.json()
    message = json.loads(json_response["description"]).get("message")
    assert response.status_code == 400
    assert "additionalProperties" in message["error_validator"]


def test_pattern():
    """ test should_fail_due_to_invalid_mac_address_on_payload """
    actual_dir = os.getcwd()
    evc_params = actual_dir + "/tests/oas/evc_params.json"
    with open(evc_params, encoding="utf8") as json_file:
        json_data = json.load(json_file)
        json_file.close()
    url = json_data["url"]
    headers = json_data["headers"]
    json_data["uni_z"]["interface_id"] = "zz:00:00:00:00:00:00:01:1"
    payload = {
        "name": "EVC_1",
        "enabled": True,
        "uni_a": json_data["uni_a"],
        "uni_z": json_data["uni_z"],
        "bandwidth": json_data["bandwidth"],
        "dynamic_backup_path": True,
    }
    request_data = json.dumps(payload)
    response = requests.post(url=url, data=request_data, headers=headers)
    json_response = response.json()
    message = json.loads(json_response["description"]).get("message")
    assert response.status_code == 400
    assert "pattern" in message["error_validator"]


def test_type():
    """ test should_fail_due_to_invalid_mac_address_on_payload """
    actual_dir = os.getcwd()
    evc_params = actual_dir + "/tests/oas/evc_params.json"
    with open(evc_params, encoding="utf8") as json_file:
        json_data = json.load(json_file)
        json_file.close()
    url = json_data["url"]
    headers = json_data["headers"]
    payload = {
        "name": "EVC_1",
        "enabled": True,
        "uni_a": {
            "interface_id": "00:00:00:00:00:00:00:01:1",
            "tag": {"tag_type": 1, "value": "1"},
        },
        "uni_z": json_data["uni_z"],
        "bandwidth": json_data["bandwidth"],
        "dynamic_backup_path": True,
    }
    request_data = json.dumps(payload)
    response = requests.post(url=url, data=request_data, headers=headers)
    json_response = response.json()
    message = json.loads(json_response["description"]).get("message")
    assert response.status_code == 400
    assert "type" in message["error_validator"]
