"""`STATUS_BY_CODE` covers every `ProblemCode` of the contract (D8).

The enum is **parsed out of `docs/hld/openapi.yaml`**, never retyped here: a code added to the
contract must fail this test until `app.api.errors` maps it, which is the only way the mapping
stays complete without anyone remembering to update two places.

The second test is the converse — no invented codes — and the third checks that each mapped
status is the one the contract's `components/responses` puts that code under, so a code cannot be
mapped to a *wrong* status either.
"""

from __future__ import annotations

import re

from app.api.errors import STATUS_BY_CODE

from tests.api._openapi import load_openapi

#: `components/responses/<name>` → the status that response is used as, from `openapi.yaml`'s own
#: `$ref`s. `Unauthorized` only ever appears under `'401'`, and so on.
_RESPONSE_STATUS: dict[str, int] = {
    "Unauthorized": 401,
    "Forbidden": 403,
    "NotFound": 404,
    "Conflict": 409,
    "UnprocessableEntity": 422,
    "ServiceUnavailable": 503,
    "TooManyRequests": 429,  # additive, I7 E51 (G5)
}


def _contract_codes() -> list[str]:
    document = load_openapi()
    schema = document["components"]["schemas"]["ProblemCode"]
    codes: list[str] = list(schema["enum"])
    return codes


def test_every_contract_problem_code_has_a_status() -> None:
    """No `ProblemCode` can reach a client without a mapped HTTP status."""
    unmapped = [code for code in _contract_codes() if code not in STATUS_BY_CODE]
    assert not unmapped, f"ProblemCode members with no status mapping: {unmapped}"


def test_no_invented_problem_codes() -> None:
    """The mapping holds no code the contract does not define."""
    contract = set(_contract_codes())
    invented = sorted(set(STATUS_BY_CODE) - contract)
    assert not invented, f"codes mapped that openapi.yaml does not define: {invented}"


def test_shared_response_statuses_agree_with_the_contract() -> None:
    """A code named in a shared response's description gets that response's status.

    `openapi.yaml` documents the codes of `Unauthorized`, `Forbidden`, `NotFound`, `Conflict`,
    `UnprocessableEntity` and `ServiceUnavailable` in prose inside each description. Every code
    named there must map to that response's status — this is what would catch, say,
    `SESSION_NOT_ACTIVE` being mapped to 422 when the contract lists it under `Conflict`.
    """
    document = load_openapi()
    contract = set(_contract_codes())
    wrong: list[str] = []
    for name, status in _RESPONSE_STATUS.items():
        description = document["components"]["responses"][name].get("description", "")
        for code in re.findall(r"`([A-Z][A-Z_]+)`", description):
            if code not in contract:
                continue
            mapped = STATUS_BY_CODE.get(code)
            if mapped != status:
                wrong.append(f"{code}: mapped to {mapped}, openapi.yaml lists it under {status}")
    assert not wrong, wrong
