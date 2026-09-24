"""The ДДС phone's dial plan (I3 E6b, HLD `80-telephony.md` §80.3.5) — pure, row by row.

The browser path never dials (its button carries the kind); E6e's SIP endpoint resolves every
number a softphone dials through `resolve_dial`, so each row of §80.3.5 is pinned here.
"""

from __future__ import annotations

import pytest
from app.domain.dds.call import DdsCallKind
from app.domain.enums import ServiceId
from app.domain.routing.catalog import ServiceCatalog, ServiceCatalogEntry
from app.domain.routing.dial_plan import DialTarget, normalise_phone, phone_extension, resolve_dial


def _entry(
    service_id: str, *, code: str | None = None, display: bool = True
) -> ServiceCatalogEntry:
    return ServiceCatalogEntry(
        id=ServiceId(service_id),
        name_ru=service_id,
        full_name_ru=service_id,
        kind="CITY",  # type: ignore[arg-type]
        code=code,
        okrug=None,
        district=None,
        classifier_org_id=None,
        status_policy="DEFAULT",  # type: ignore[arg-type]
        display=display,
        deprecated=False,
        phone=None,
    )


CATALOG = ServiceCatalog(
    catalog_id="test",
    services=(
        _entry("FIRE_RESCUE", code="101"),
        _entry("POLICE", code="102"),
        _entry("HIDDEN_ORG", display=False),
        _entry("TSODD"),
        _entry("OATI"),
    ),
)
CLAIMANT = "+7 (916) 123-45-67"


@pytest.mark.parametrize(
    ("dialed", "expected"),
    [
        ("112", DialTarget(kind=DdsCallKind.OPERATOR_112)),
        ("101", DialTarget(kind=DdsCallKind.SERVICE_HEAD, service_id=ServiceId("FIRE_RESCUE"))),
        ("102", DialTarget(kind=DdsCallKind.SERVICE_HEAD, service_id=ServiceId("POLICE"))),
        # `7` + the 1-based position among the displayed entries, in pack order.
        ("7001", DialTarget(kind=DdsCallKind.SERVICE_HEAD, service_id=ServiceId("FIRE_RESCUE"))),
        ("7003", DialTarget(kind=DdsCallKind.SERVICE_HEAD, service_id=ServiceId("TSODD"))),
        ("7004", DialTarget(kind=DdsCallKind.SERVICE_HEAD, service_id=ServiceId("OATI"))),
        ("89161234567", DialTarget(kind=DdsCallKind.CLAIMANT)),
        ("79161234567", DialTarget(kind=DdsCallKind.CLAIMANT)),
        ("9161234567", DialTarget(kind=DdsCallKind.CLAIMANT)),
        ("999", None),
        ("7005", None),
        ("103", None),
        ("", None),
        ("4951234567", None),
    ],
)
def test_each_row_of_the_dial_plan(dialed: str, expected: DialTarget | None) -> None:
    assert resolve_dial(dialed, catalog=CATALOG, claimant_phone=CLAIMANT) == expected


def test_without_a_claimant_number_nobody_is_the_claimant() -> None:
    assert resolve_dial("89161234567", catalog=CATALOG, claimant_phone=None) is None


def test_the_national_ten_digits_are_compared() -> None:
    assert normalise_phone("+7 (916) 123-45-67") == "9161234567"
    assert normalise_phone("8-916-123-45-67") == "9161234567"
    assert normalise_phone("123") == "123"


def test_phone_extensions_are_the_code_or_the_displayed_position() -> None:
    assert phone_extension(CATALOG, ServiceId("FIRE_RESCUE")) == "101"
    assert phone_extension(CATALOG, ServiceId("OATI")) == "7004"
    assert phone_extension(CATALOG, ServiceId("HIDDEN_ORG")) is None
    assert phone_extension(CATALOG, ServiceId("NOPE")) is None
