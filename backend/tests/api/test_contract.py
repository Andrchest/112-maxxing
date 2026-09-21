"""Every registered route matches `docs/hld/openapi.yaml` (D8, D12).

Three assertions, all derived from the YAML rather than from a list retyped here:

1. every `(path, method)` the application registers exists in the contract, with the same
   `operationId`;
2. every route's success status is the one the contract gives that operation;
3. every route's pydantic response model has **exactly** the property names of the contract's
   response schema, with `$ref` and `allOf` resolved.

(3) is the one that bites: rename a field in `app.api.schemas` and this test fails, which is the
"prove the contract test bites" step of the E7-A task. It is also what makes E7-B and E7-C cheap
to verify — they add routes to the already-included stub routers and this test covers them the
moment they exist.

The FastAPI-generated `/openapi.json`, `/docs` and `/redoc` routes are not part of the contract
and are skipped by path.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest
from app.api.container import Container
from app.api.main import create_app
from fastapi.routing import APIRoute
from pydantic import BaseModel

from tests.api._openapi import iter_api_routes, load_openapi, operation_of, property_names

pytestmark = pytest.mark.integration

_GENERATED_PATHS = frozenset({"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"})


def _contract_routes(container: Container) -> list[APIRoute]:
    app = create_app(container)
    return [route for route in iter_api_routes(app) if route.path not in _GENERATED_PATHS]


def test_every_route_is_in_the_contract(container: Container) -> None:
    """No endpoint exists that `openapi.yaml` does not describe."""
    document = load_openapi()
    missing: list[str] = []
    for route in _contract_routes(container):
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            if operation_of(document, route.path, method) is None:
                missing.append(f"{method} {route.path}")
    assert not missing, f"routes absent from openapi.yaml: {missing}"


def test_every_route_carries_the_contract_operation_id(container: Container) -> None:
    """`operation_id` is the contract's `operationId`, literally."""
    document = load_openapi()
    wrong: list[str] = []
    for route in _contract_routes(container):
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            operation = operation_of(document, route.path, method)
            assert operation is not None
            expected = operation.get("operationId")
            if route.operation_id != expected:
                wrong.append(
                    f"{method} {route.path}: operation_id={route.operation_id!r}, "
                    f"openapi.yaml says {expected!r}"
                )
    assert not wrong, wrong


def test_every_route_uses_the_contract_success_status(container: Container) -> None:
    """A route's `status_code` is the success status the contract documents."""
    document = load_openapi()
    wrong: list[str] = []
    for route in _contract_routes(container):
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            operation = operation_of(document, route.path, method)
            assert operation is not None
            successes = sorted(
                int(status)
                for status in operation.get("responses", {})
                if str(status).isdigit() and 200 <= int(status) < 300
            )
            if successes and route.status_code not in successes:
                wrong.append(
                    f"{method} {route.path}: status_code={route.status_code}, "
                    f"openapi.yaml documents {successes}"
                )
    assert not wrong, wrong


def test_response_models_have_the_contract_property_names(container: Container) -> None:
    """Each response model's field names equal the contract schema's `properties` keys.

    This is the assertion that catches a rename on either side. A route whose response schema is
    an inline `{items, total}` object is compared against that inline schema, not skipped.
    """
    document = load_openapi()
    mismatches: list[str] = []
    for route in _contract_routes(container):
        model = route.response_model
        if model is None or not _is_model(model):
            continue
        for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
            operation = operation_of(document, route.path, method)
            assert operation is not None
            schema = _success_schema(operation, route.status_code)
            if schema is None:
                continue
            expected = property_names(document, schema)
            actual = set(_fields_of(model))
            if expected != actual:
                mismatches.append(
                    f"{method} {route.path}: model has {sorted(actual)}, "
                    f"openapi.yaml has {sorted(expected)}"
                )
    assert not mismatches, mismatches


def _is_model(model: Any) -> bool:
    return isinstance(model, type) and issubclass(model, BaseModel)


def _fields_of(model: Any) -> set[str]:
    fields: dict[str, Any] = model.model_fields
    return set(fields)


def _success_schema(
    operation: Mapping[str, Any], status_code: int | None
) -> Mapping[str, Any] | None:
    responses = operation.get("responses", {})
    key = str(status_code) if status_code is not None else None
    response = responses.get(key) if key else None
    if not isinstance(response, Mapping):
        return None
    content = response.get("content", {})
    for media_type in ("application/json", "application/problem+json"):
        media = content.get(media_type)
        if isinstance(media, Mapping) and isinstance(media.get("schema"), Mapping):
            schema: Mapping[str, Any] = media["schema"]
            return schema
    return None
