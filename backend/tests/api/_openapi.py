"""Reading `docs/hld/openapi.yaml` and walking the app's routes — shared by the contract tests.

Two helpers, both deliberately *derivative*: neither restates anything the contract already says.
`load_openapi()` parses the YAML, and `iter_api_routes(app)` walks every `APIRoute` the
application registered, recursing through FastAPI's included-router wrappers so that a route added
to one of the stub routers of E7-B / E7-C is picked up with no change here.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI
from fastapi.routing import APIRoute, APIRouter

REPO_ROOT = Path(__file__).resolve().parents[3]
OPENAPI_PATH = REPO_ROOT / "docs" / "hld" / "openapi.yaml"

__all__ = [
    "OPENAPI_PATH",
    "iter_api_routes",
    "load_openapi",
    "operation_of",
    "property_names",
    "resolve",
]


@lru_cache(maxsize=1)
def load_openapi() -> Mapping[str, Any]:
    """`docs/hld/openapi.yaml`, parsed. The contract, never a copy of it."""
    document: Mapping[str, Any] = yaml.safe_load(OPENAPI_PATH.read_text(encoding="utf-8"))
    return document


def iter_api_routes(app: FastAPI) -> Iterator[APIRoute]:
    """Every `APIRoute` on `app`, including those inside included routers.

    FastAPI wraps an included router rather than flattening its routes into `app.routes`, so a
    naive `isinstance` scan of `app.routes` finds nothing. Walking `original_router` is what makes
    this grow automatically as E7-B and E7-C fill the stub routers.
    """
    yield from _walk(app.routes)


def _walk(routes: Any) -> Iterator[APIRoute]:
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
            continue
        nested = getattr(route, "original_router", None)
        if isinstance(nested, APIRouter):
            yield from _walk(nested.routes)
            continue
        inner = getattr(route, "routes", None)
        if inner:
            yield from _walk(inner)


def operation_of(document: Mapping[str, Any], path: str, method: str) -> Mapping[str, Any] | None:
    """The operation object at `(path, method)`, or `None` when the contract has no such pair."""
    item = document.get("paths", {}).get(path)
    if not isinstance(item, Mapping):
        return None
    operation = item.get(method.lower())
    return operation if isinstance(operation, Mapping) else None


def resolve(document: Mapping[str, Any], schema: Mapping[str, Any]) -> Mapping[str, Any]:
    """Follow one `$ref` into `components`; a schema without one is returned unchanged."""
    ref = schema.get("$ref")
    if not isinstance(ref, str):
        return schema
    node: Any = document
    for part in ref.lstrip("#/").split("/"):
        node = node[part]
    assert isinstance(node, Mapping)
    return node


def property_names(document: Mapping[str, Any], schema: Mapping[str, Any]) -> set[str]:
    """The `properties` key set of a schema, resolving `$ref` and flattening `allOf`.

    `allOf` is flattened because `ScenarioProblem` is "a `Problem` plus `validation_report`" and
    the union of the two `properties` maps is what a response actually carries.
    """
    resolved = resolve(document, schema)
    names: set[str] = set(resolved.get("properties", {}))
    for branch in resolved.get("allOf", ()):
        names |= property_names(document, branch)
    return names
