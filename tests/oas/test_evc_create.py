import os
import json
import requests


def test_required():
    """ test should_fail_due_to_missing_name_attribute_on_payload """
    actual_dir = os.getcwd()
    json_file = actual_dir+"/tests/oas/evc_params.json"
    with open(json_file) as f:
        json_data = json.load(f)
        f.close()
    url = json_data["url"]
    headers = json_data["headers"]
    payload = {
        "enabled": True,
        "uni_a": json_data["uni_a"],
        "uni_z": json_data["uni_z"],
        "bandwidth": json_data["bandwidth"],
        "dynamic_backup_path": True
    }
    request_data = json.dumps(payload)
    response = requests.post(url=url, data=request_data, headers=headers)
    json_response = response.json()
    assert response.status_code == 400
    assert 'required' in json_response['description']['error_validator']


def test_additionalProperties():
    """ test should_fail_due_to_additional_properties_on_payload """
    actual_dir = os.getcwd()
    json_file = actual_dir+"/tests/oas/evc_params.json"
    with open(json_file) as f:
        json_data = json.load(f)
        f.close()
    url = json_data["url"]
    headers = json_data["headers"]
    payload = {
        "name": "EVC_1",
        "enabled": True,
        "uni_a": json_data["uni_a"],
        "uni_z": json_data["uni_z"],
        "bandwidth": json_data["bandwidth"],
        "dynamic_backup_path": True,
        "active": True
    }
    request_data = json.dumps(payload)
    response = requests.post(url=url, data=request_data, headers=headers)
    json_response = response.json()
    assert response.status_code == 400
    assert 'additionalProperties' in \
        json_response['description']['error_validator']


def test_pattern():
    """ test should_fail_due_to_invalid_mac_address_on_payload """
    actual_dir = os.getcwd()
    json_file = actual_dir+"/tests/oas/evc_params.json"
    with open(json_file) as f:
        json_data = json.load(f)
        f.close()
    url = json_data["url"]
    headers = json_data["headers"]
    json_data["uni_z"]["interface_id"] = "zz:00:00:00:00:00:00:01:1"
    payload = {
        "name": "EVC_1",
        "enabled": True,
        "uni_a": json_data["uni_a"],
        "uni_z": json_data["uni_z"],
        "bandwidth": json_data["bandwidth"],
        "dynamic_backup_path": True
    }
    request_data = json.dumps(payload)
    response = requests.post(url=url, data=request_data, headers=headers)
    json_response = response.json()
    assert response.status_code == 400
    assert 'pattern' in json_response['description']['error_validator']


def test_type():
    """ test should_fail_due_to_invalid_mac_address_on_payload """
    actual_dir = os.getcwd()
    json_file = actual_dir+"/tests/oas/evc_params.json"
    with open(json_file) as f:
        json_data = json.load(f)
        f.close()
    url = json_data["url"]
    headers = json_data["headers"]
    payload = {
        "name": "EVC_1",
        "enabled": True,
        "uni_a": {
            "interface_id": "00:00:00:00:00:00:00:01:1",
            "tag": {
                "tag_type": 1,
                "value": "1"
            }
        },
        "uni_z": json_data["uni_z"],
        "bandwidth": json_data["bandwidth"],
        "dynamic_backup_path": True
    }
    request_data = json.dumps(payload)
    response = requests.post(url=url, data=request_data, headers=headers)
    json_response = response.json()
    assert response.status_code == 400
    assert 'type' in json_response['description']['error_validator']
