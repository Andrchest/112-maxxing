"""Shared API model base and the paged-list envelope (`openapi.yaml`, D8, D12).

Three endpoints of this epic answer with the same inline object — `{items, total}` — rather than a
named schema. `PageSchema` renders it once, generically, so `listScenarios`, `listScenarioVersions`
and `listSessions` cannot drift from one another.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

__all__ = ["ApiModel", "PageSchema", "ProblemSchema"]


class ApiModel(BaseModel):
    """Base for every API model: frozen, and `extra="forbid"` on the way in.

    `additionalProperties: false` is what almost every schema in `openapi.yaml` says, and
    forbidding extras on a *request* model is how a client that posts a misspelled field learns
    about it (as `422 VALIDATION_ERROR`) instead of having it silently ignored.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


class PageSchema[ItemT](ApiModel):
    """`{items, total}` — the inline list envelope of `openapi.yaml`.

    `total` is the unpaged count, not `len(items)`: a client paginating needs to know how far the
    list goes.
    """

    items: list[ItemT]
    total: int = Field(ge=0)


class ProblemSchema(ApiModel):
    """`openapi.yaml`'s `Problem`, property names literal.

    It is declared for the contract test and for documentation; the responses themselves are
    rendered by `app.api.errors.problem_response`, which also attaches the
    `additionalProperties: true` members a `ScenarioProblem` carries.
    """

    model_config = ConfigDict(extra="allow", frozen=True)

    type: str = "about:blank"
    title: str
    status: int = Field(ge=100, le=599)
    detail: str | None = None
    instance: str | None = None
    code: str
