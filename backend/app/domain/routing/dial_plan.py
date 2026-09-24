"""The ДДС phone's dial plan — pure (HLD `80-telephony.md` §80.3.5, D23; I3 E6b, used by E6e).

A softphone dials digits; the backend has to turn them into *whom* the ДДС is calling. This module
is that function and nothing else — no session, no repository, no I/O:

* `112` → `OPERATOR_112`;
* a catalog `code` (`101` … `104`) → `SERVICE_HEAD` of that service;
* `7` + 3 digits → `SERVICE_HEAD` of the catalog entry at that 1-based position among the
  `display: true` entries in pack order (`7001` …);
* the snapshot's `caller.phone` (digits; a leading `8`/`7` of an 11-digit number dropped, so the
  national 10 digits are compared) → `CLAIMANT`;
* `999` → the gateway-local echo: it never reaches the backend, so it resolves to nothing here;
* anything else → nothing (`404 DIAL_NUMBER_UNKNOWN`, E6e).

The `7xxx` extension is stable because the pack is sha-pinned: a reorder is a new pack. Which leg
of which card a `SERVICE_HEAD` number means, and whether the dialling user plays it, is the
session selection's question (E6e); the browser path never needs this module at all — its button
carries the kind (and, E6c, the `assignment_id`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.domain.dds.call import DdsCallKind
from app.domain.enums import ServiceId
from app.domain.routing.catalog import ServiceCatalog

__all__ = [
    "ECHO_NUMBER",
    "EXTENSION_PREFIX",
    "OPERATOR_112_NUMBER",
    "DialTarget",
    "normalise_phone",
    "phone_extension",
    "resolve_dial",
]

OPERATOR_112_NUMBER = "112"
ECHO_NUMBER = "999"
"""The SIP gateway's own echo (E6a). The gateway answers it; the backend never sees it."""
EXTENSION_PREFIX = "7"
_EXTENSION = re.compile(r"^7(\d{3})$")
_NON_DIGIT = re.compile(r"\D")
_NATIONAL_DIGITS = 10


@dataclass(frozen=True, slots=True)
class DialTarget:
    """Whom a dialled number reaches: the call kind, and for `SERVICE_HEAD` the service."""

    kind: DdsCallKind
    service_id: ServiceId | None = None


def normalise_phone(raw: str) -> str:
    """Digits only; an 11-digit number's leading `8` or `7` dropped (the national 10 digits).

    `+7 (916) 123-45-67`, `89161234567` and `9161234567` all normalise to `9161234567`, which is
    what makes the claimant's card number and whatever a softphone dials comparable.
    """
    digits = _NON_DIGIT.sub("", raw)
    if len(digits) == _NATIONAL_DIGITS + 1 and digits[0] in "78":
        return digits[1:]
    return digits


def phone_extension(catalog: ServiceCatalog, service_id: ServiceId) -> str | None:
    """`DdsLegView.phone_extension` (E6e): the catalog `code` if it has one, else `7` + its 1-based
    position among the `display: true` entries in pack order; `None` for an undisplayed service."""
    entry = catalog.get(service_id)
    if entry is None:
        return None
    if entry.code:
        return entry.code
    displayed = [item.id for item in catalog.services if item.display]
    if service_id not in displayed:
        return None
    return f"{EXTENSION_PREFIX}{displayed.index(service_id) + 1:03d}"


def resolve_dial(
    dialed: str, *, catalog: ServiceCatalog, claimant_phone: str | None = None
) -> DialTarget | None:
    """The §80.3.5 table, in its row order; `None` for `999` and for anything unknown."""
    digits = _NON_DIGIT.sub("", dialed)
    if not digits or digits == ECHO_NUMBER:
        return None
    if digits == OPERATOR_112_NUMBER:
        return DialTarget(kind=DdsCallKind.OPERATOR_112)
    for entry in catalog.services:
        if entry.code and entry.code == digits:
            return DialTarget(kind=DdsCallKind.SERVICE_HEAD, service_id=entry.id)
    extension = _EXTENSION.match(digits)
    if extension is not None:
        position = int(extension.group(1))
        displayed = [item for item in catalog.services if item.display]
        if 1 <= position <= len(displayed):
            return DialTarget(kind=DdsCallKind.SERVICE_HEAD, service_id=displayed[position - 1].id)
        return None
    if claimant_phone:
        wanted = normalise_phone(claimant_phone)
        if wanted and normalise_phone(digits) == wanted:
            return DialTarget(kind=DdsCallKind.CLAIMANT)
    return None
