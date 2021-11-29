"""Utility functions."""
import functools
from pathlib import Path

from flask import request
from openapi_core import create_spec
from openapi_core.contrib.flask import FlaskOpenAPIRequest
from openapi_core.validation.request.validators import RequestValidator
from openapi_spec_validator import validate_spec
from openapi_spec_validator.readers import read_from_filename
from werkzeug.exceptions import BadRequest, UnsupportedMediaType

from kytos.core import log
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


def load_spec():
    """Validate openapi spec."""
    napp_dir = Path(__file__).parent
    yml_file = napp_dir / "openapi.yml"
    spec_dict, _ = read_from_filename(yml_file)

    validate_spec(spec_dict)

    return create_spec(spec_dict)


def validate(spec):
    """Decorator to validate a REST endpoint input.

    Uses the schema defined in the openapi.yml file
    to validate.
    """

    def validate_decorator(func):
        @functools.wraps(func)
        def wrapper_validate(*args, **kwargs):
            print(f"Spec {spec}")
            try:
                data = request.get_json()
            except BadRequest:
                result = "The request body is not a well-formed JSON."
                log.debug("create_circuit result %s %s", result, 400)
                raise BadRequest(result) from BadRequest
            if data is None:
                result = "The request body mimetype is not application/json."
                log.debug("update result %s %s", result, 415)
                raise UnsupportedMediaType(result)

            validator = RequestValidator(spec)
            openapi_request = FlaskOpenAPIRequest(request)
            result = validator.validate(openapi_request)
            if result.errors:
                errors = result.errors[0]
                if hasattr(errors, "schema_errors"):
                    schema_errors = errors.schema_errors[0]
                    error_response = {
                        "error_message": schema_errors.message,
                        "error_validator": schema_errors.validator,
                        "error_validator_value": schema_errors.validator_value,
                        "error_path": list(schema_errors.path),
                        "error_schema": schema_errors.schema,
                        "error_schema_path": list(schema_errors.schema_path),
                    }
                    log.debug("error response: %s", error_response)
                else:
                    error_response = (
                        "The request body mimetype is not application/json."
                    )
                raise BadRequest(error_response) from BadRequest
            return func(*args, data=data, **kwargs)

        return wrapper_validate

    return validate_decorator
