"""RFC 7807 `application/problem+json` rendering (D8, `openapi.yaml`'s `Problem`).

D8: "Errors: RFC 7807 problem JSON; invalid transition ⇒ 409 with `code = INVALID_TRANSITION`."
This module is the single place a raised exception becomes an HTTP response, so no endpoint ever
writes a status code for an error and no endpoint can invent a `code` the contract does not have.

Three handlers, one shape:

* `DomainError` — every application and domain error. Its `code` class attribute is looked up in
  `STATUS_BY_CODE` below; a `DomainError` without one (they exist: `InvalidTransitionError`,
  `CardFieldError`, `GateError`) falls back to `_DEFAULT_CODE_BY_TYPE` and, failing that, to
  `INVALID_TRANSITION`/`VALIDATION_ERROR` as its type dictates;
* `RequestValidationError` — FastAPI's own body/query rejection, rendered as `422
  VALIDATION_ERROR` so that a malformed body and a semantically invalid one look the same to a
  client;
* `Exception` — anything unforeseen: `500` with `code = VALIDATION_ERROR`'s sibling… no. With a
  generic title and **no stack trace in the body** (SPEC §41). The traceback goes to the log,
  where an operator can see it, and never to the network.

`STATUS_BY_CODE` is asserted complete against `openapi.yaml`'s `ProblemCode` enum by
`backend/tests/api/test_problem_codes.py`, which parses the YAML rather than restating the list —
so a code added to the contract fails the suite until it is mapped here.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse

from app.application.scenarios.import_scenario_version import ScenarioDocumentInvalidError
from app.domain.common.errors import (
    CardFieldError,
    DomainError,
    InvalidTransitionError,
    ScenarioValidationError,
)

__all__ = [
    "PROBLEM_CONTENT_TYPE",
    "STATUS_BY_CODE",
    "install_exception_handlers",
    "problem_response",
    "status_for",
]

logger = logging.getLogger(__name__)

PROBLEM_CONTENT_TYPE = "application/problem+json"

#: `ProblemCode` → HTTP status. Copied from `openapi.yaml`'s `components/responses`: the response
#: a code appears under *is* its status, so `Unauthorized` gives 401, `Forbidden` 403, `NotFound`
#: 404, `Conflict` 409, `UnprocessableEntity` 422 and `ServiceUnavailable` 503. The four codes
#: `openapi.yaml` states a status for inline rather than through a shared response —
#: `SCENARIO_INVALID` (422 on `importScenarioVersion`), `AUDIO_PURGED` (410 on `getAudioSegment`),
#: `RANGE_NOT_SATISFIABLE` (416) and `EXPLANATION_ALREADY_EXISTS` (409 on
#: `generateReportExplanation`) — take that inline status, because openapi wins.
STATUS_BY_CODE: Mapping[str, int] = {
    # 401 — components/responses/Unauthorized
    "UNAUTHENTICATED": 401,
    # 403 — components/responses/Forbidden
    "FORBIDDEN_FOR_ROLE": 403,
    "PARTICIPANT_NOT_ASSIGNED": 403,
    "REPORT_NOT_RELEASED": 403,
    # 403 — I3 addition to Forbidden (`i3-openapi-delta.yaml` `ForbiddenI3`, E5a)
    "FORBIDDEN_FOR_SERVICE": 403,
    # 404 — components/responses/NotFound
    "NOT_FOUND": 404,
    # 404 — I3 E6e addition to NotFound (`i3-telephony-openapi-delta.yaml` `NotFoundE6`)
    "DIAL_NUMBER_UNKNOWN": 404,
    # 409 — components/responses/Conflict
    "INVALID_TRANSITION": 409,
    "ACTION_NOT_AVAILABLE": 409,
    "SESSION_NOT_ACTIVE": 409,
    "SCENARIO_VERSION_LOCKED": 409,
    "SCENARIO_VERSION_EXISTS": 409,
    "PREFAB_HANDOFF_REQUIRED": 409,
    "RECIPIENT_SERVICES_EMPTY": 409,
    "HANDOFF_ALREADY_CREATED": 409,
    "RESOURCE_UNAVAILABLE": 409,
    "REPORT_NOT_READY": 409,
    "EXPLANATION_ALREADY_EXISTS": 409,
    # 409 — I3 additions to Conflict (`docs/hld/contracts/i3-openapi-delta.yaml` `ConflictI3`)
    "VARIANT_NOT_SUPPORTED": 409,
    "VARIANT_NOT_AVAILABLE": 409,
    "REFERENCE_PACK_UNKNOWN": 409,
    "LESSON_NOT_ACTIVE": 409,
    "SERVICE_REMOVAL_FORBIDDEN": 409,
    # 409 — I3 E6b addition to Conflict (`i3-telephony-openapi-delta.yaml` `ConflictE6`)
    "DDS_LINE_BUSY": 409,
    # 409 — I3 E6e addition to Conflict (`ConflictE6`): a softphone dialled, no eligible session
    "NO_ACTIVE_DDS_SESSION": 409,
    # 409 — I4 E28 addition to Conflict (`docs/hld/contracts/i4-openapi-delta.yaml` `ConflictI4`)
    "USERNAME_TAKEN": 409,
    "SELF_MODIFICATION_FORBIDDEN": 409,
    "LAST_ADMIN_REQUIRED": 409,
    # 409 — I4 E29 addition to Conflict (`docs/hld/contracts/i4-openapi-delta.yaml` `ConflictI4`)
    "BACKUP_REQUIRED": 409,
    # 410 / 416 — stated inline on `getAudioSegment`, which E16 implements
    # (`app.application.reports.serve_audio_segment`).
    "AUDIO_PURGED": 410,
    "RANGE_NOT_SATISFIABLE": 416,
    # 422 — components/responses/UnprocessableEntity
    "VALIDATION_ERROR": 422,
    "CARD_FIELD_UNKNOWN": 422,
    "CARD_VALUE_TYPE_MISMATCH": 422,
    "SCENARIO_INVALID": 422,
    # 422 — I3 additions to UnprocessableEntity (`i3-openapi-delta.yaml` `UnprocessableEntityI3`)
    "SERVICE_UNKNOWN": 422,
    "CARD_OPTION_UNKNOWN": 422,
    "COMMENT_REQUIRED": 422,
    "PROPOSAL_UNKNOWN": 422,  # I3 E6c (HLD 80 §80.3.3)
    # 422 — I4 E34 additions to UnprocessableEntity (`i4-openapi-delta.yaml`
    # `UnprocessableEntityI4`)
    "MATERIAL_TYPE_NOT_ALLOWED": 422,
    "MATERIAL_TOO_LARGE": 422,
    # 503 — components/responses/ServiceUnavailable
    "INFERENCE_NOT_READY": 503,
    "LLM_UNAVAILABLE": 503,
}

#: Domain errors that predate the API layer and carry no `code`. Mapping them here rather than
#: adding a `code` to `app.domain` keeps the HTTP vocabulary out of the domain (D2).
_DEFAULT_CODE_BY_TYPE: tuple[tuple[type[DomainError], str], ...] = (
    (InvalidTransitionError, "INVALID_TRANSITION"),
    (CardFieldError, "CARD_FIELD_UNKNOWN"),
    (ScenarioValidationError, "SCENARIO_INVALID"),
)

_TITLE_BY_STATUS: Mapping[int, str] = {
    401: "Unauthorized",
    403: "Forbidden",
    404: "Not Found",
    409: "Conflict",
    410: "Gone",
    416: "Range Not Satisfiable",
    422: "Unprocessable Entity",
    500: "Internal Server Error",
    503: "Service Unavailable",
}


def code_of(error: DomainError) -> str:
    """The `ProblemCode` of a domain error: its own `code`, else its type's default."""
    code = getattr(error, "code", None)
    if isinstance(code, str) and code in STATUS_BY_CODE:
        return code
    for error_type, default in _DEFAULT_CODE_BY_TYPE:
        if isinstance(error, error_type):
            return default
    # A `DomainError` nobody classified is a rejected *input*, not a server fault: the domain
    # raises it instead of accepting something it was asked to accept.
    return "VALIDATION_ERROR"


def status_for(code: str) -> int:
    """The HTTP status of a `ProblemCode`; an unmapped code is a `500` — a bug the suite catches."""
    return STATUS_BY_CODE.get(code, 500)


def problem_response(
    *,
    code: str,
    detail: str | None,
    instance: str | None,
    status: int | None = None,
    extra: Mapping[str, Any] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    """Render one `Problem` (`openapi.yaml`), with `additionalProperties` from `extra`.

    `type` stays `about:blank`: RFC 7807 makes that the correct value when the status code is the
    whole semantics of the problem type, and `code` — not a URI nobody will dereference — is the
    machine-readable contract here (D8).

    `headers`, when given, are passed straight to the `JSONResponse` on top of the usual
    `Content-Type`; today's one user is the `416`'s `Content-Range: bytes */<total>` (RFC 9110
    §14.4, E16 ruling R7). Every existing caller omits it, so behaviour is unchanged for them.
    """
    resolved = status if status is not None else status_for(code)
    body: dict[str, Any] = {
        "type": "about:blank",
        "title": _TITLE_BY_STATUS.get(resolved, "Error"),
        "status": resolved,
        "detail": detail,
        "instance": instance,
        "code": code,
    }
    if extra:
        body.update(extra)
    return JSONResponse(
        status_code=resolved,
        content=body,
        media_type=PROBLEM_CONTENT_TYPE,
        headers=dict(headers) if headers else None,
    )


def install_exception_handlers(app: FastAPI) -> None:
    """Register the three handlers on `app`. Called by `create_app` and nothing else."""

    @app.exception_handler(DomainError)
    async def _domain_error(request: Request, exc: Exception) -> JSONResponse:
        error = exc if isinstance(exc, DomainError) else DomainError(str(exc))
        code = code_of(error)
        extra = _extra_of(error)
        headers = _headers_of(error)
        return problem_response(
            code=code, detail=str(error), instance=request.url.path, extra=extra, headers=headers
        )

    @app.exception_handler(RequestValidationError)
    async def _request_validation(request: Request, exc: Exception) -> JSONResponse:
        # FastAPI's own rejection of a body, query or path parameter. Rendered as problem+json so
        # a client parses exactly one error shape, never two.
        errors = exc.errors() if isinstance(exc, RequestValidationError) else []
        return problem_response(
            code="VALIDATION_ERROR",
            detail=_validation_detail(errors),
            instance=request.url.path,
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # The traceback goes to the log, where an operator can read it, and never into the body:
        # a stack trace on the wire is an information leak (SPEC §41).
        logger.exception("unhandled error serving %s %s", request.method, request.url.path)
        return problem_response(
            code="VALIDATION_ERROR",
            status=500,
            detail="The request could not be completed. See the backend log.",
            instance=request.url.path,
        )


def _headers_of(error: DomainError) -> Mapping[str, str] | None:
    """The response headers a particular problem carries.

    `RangeNotSatisfiableError` (`app.application.reports.serve_audio_segment`) parks the
    `Content-Range: bytes */<total>` value RFC 9110 §14.4 requires on a `416` on its own
    `content_range` attribute; this is the one place that value reaches the response (E16 R7).
    """
    content_range = getattr(error, "content_range", None)
    if isinstance(content_range, str):
        return {"Content-Range": content_range}
    return None


def _extra_of(error: DomainError) -> Mapping[str, Any] | None:
    """The `additionalProperties` a particular problem carries.

    `SCENARIO_INVALID` is `ScenarioProblem`: "the problem carries the complete
    `validation_report`" (`openapi.yaml`). Rendering it here rather than in the router is what
    makes an import failure and a validation failure produce the same document.
    """
    if isinstance(error, ScenarioDocumentInvalidError):
        from app.api.schemas.scenarios import validation_report_schema

        schema = validation_report_schema(error.report)
        return {"validation_report": schema.model_dump(mode="json")}
    return None


def _validation_detail(errors: list[Any]) -> str:
    """A one-line summary of FastAPI's validation errors — locations and messages, no values.

    The offending *values* are deliberately left out: a rejected login body would otherwise echo
    the password back in the error document (SPEC §41).
    """
    if not errors:
        return "the request is not valid"
    parts = []
    for error in errors[:10]:
        location = ".".join(str(part) for part in error.get("loc", ()))
        parts.append(f"{location}: {error.get('msg', 'invalid')}")
    return "; ".join(parts)
