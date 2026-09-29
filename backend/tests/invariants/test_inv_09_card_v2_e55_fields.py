"""INV 9/10 — the card v2 fields of I7 E55 never move a score (ТЗ gap G16).

I7 E55 added «Канал связи» (`applicant.channel`), five caller statuses, «Количество» of the injured
(`flags.casualties_count`), the 103 «Отказ от реагирования» (`flags.response_refused`) and the
1999-character cap of «Описание со слов заявителя», and the ДДС's «ЧС» / «ЧП» marks
(`DDS_CARD_MARKS_SET`). None of them is scored (owner decisions 2026-09-29). This pins it over
every one of the 108 ticket scenarios: a log
whose trainee also filled every new field — and whose handoff carries them, and whose ДДС set
both marks — gives the same
`ScoreReport` (results, evidence and notes; only `computed_from_event_count` counts the extra
entries) and the same checksum as the log without them, and a rescore of it reproduces it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import pytest
from app.domain.common.ids import EventId
from app.domain.enums import ActorType
from app.domain.events.session_event import SessionEvent
from app.domain.events.types import EventType
from app.domain.scenario.version import ScenarioVersion
from app.domain.scoring.engine import report_checksum, score

from tests.unit.domain.scoring._event_log_builders import (
    CARD_ID,
    INCIDENT_ID,
    SNAPSHOT_ID,
    TRAINEE_ID,
    det_uuid,
    with_previous_scoring_events,
)
from tests.unit.domain.scoring.test_deadline_timer import TICKETS, memo_log

#: A trainee's entries in every field I7 E55 added (the description at its 1999-character cap).
E55_VALUES: Mapping[str, Any] = {
    "caller.status": "RELATIVE",
    "applicant.channel": "MTS",
    "flags.casualties": True,
    "flags.casualties_count": 2,
    "flags.response_refused": True,
    "description.text": "ы" * 1999,
}


def _append(
    events: Sequence[SessionEvent], event_type: EventType, payload: Mapping[str, Any], name: str
) -> tuple[SessionEvent, ...]:
    """`events` plus one trainee event after the last one (same clock, next `seq_no`)."""
    last = events[-1]
    event = SessionEvent(
        id=EventId(det_uuid(f"e55:{name}")),
        session_id=last.session_id,
        seq_no=last.seq_no + 1,
        event_type=event_type,
        timestamp_utc=last.timestamp_utc,
        monotonic_offset_ms=last.monotonic_offset_ms,
        actor_type=ActorType.TRAINEE,
        actor_id=TRAINEE_ID,
        payload=dict(payload),
    )
    return (*events, event)


def _card_field(
    events: Sequence[SessionEvent], path: str, value: Any, revision_no: int
) -> tuple[SessionEvent, ...]:
    return _append(
        events,
        EventType.CARD_FIELD_CHANGED,
        {
            "card_id": str(CARD_ID),
            "revision_id": str(det_uuid(f"e55-revision:{path}")),
            "revision_no": revision_no,
            "field_path": path,
            "previous_value": None,
            "new_value": value,
            "actor_user_id": str(TRAINEE_ID),
            "at_offset_ms": events[-1].monotonic_offset_ms,
        },
        f"card:{path}",
    )


def _log(version: ScenarioVersion, *, with_e55: bool) -> tuple[SessionEvent, ...]:
    """The timer tests' memo card of `version`, with the whole 112 chain recorded, the trainee's
    entries of the prefab card, the handoff — and, `with_e55`, the E55 fields on top of it."""
    prefab = version.expected_response.prefab_handoff
    assert prefab is not None
    events = tuple(
        event.model_copy(
            update={"payload": {**event.payload, "role_chain": ["OPERATOR_112", "DDS"]}}
        )
        if event.event_type is EventType.SESSION_CREATED
        else event
        for event in memo_log(version, decision_after_ms=40_000)
    )
    card = dict(prefab.card_values)
    for revision_no, (path, value) in enumerate(sorted(card.items()), start=1):
        events = _card_field(events, path, value, revision_no)
    handoff_values = {**card, **E55_VALUES} if with_e55 else card
    events = _append(
        events,
        EventType.HANDOFF_CREATED,
        {
            "snapshot_id": str(SNAPSHOT_ID),
            "incident_id": str(INCIDENT_ID),
            "card_id": str(CARD_ID),
            "card_revision_id": str(det_uuid("e55-revision:handoff")),
            "recipient_services": list(prefab.recipient_services),
            "card_values": handoff_values,
            "content_sha256": "0" * 64,
            "at_offset_ms": events[-1].monotonic_offset_ms,
        },
        "handoff",
    )
    if with_e55:
        for revision_no, (path, value) in enumerate(E55_VALUES.items(), start=len(card) + 1):
            events = _card_field(events, path, value, revision_no)
        events = _append(
            events,
            EventType.DDS_CARD_MARKS_SET,
            {
                "previous_chs": False,
                "previous_chp": False,
                "chs": True,
                "chp": True,
                "actor_user_id": str(TRAINEE_ID),
                "at_offset_ms": events[-1].monotonic_offset_ms,
            },
            "marks",
        )
    return events


@pytest.mark.parametrize("slug", sorted(TICKETS))
def test_the_e55_fields_never_change_a_ticket_score_or_its_checksum(slug: str) -> None:
    version = TICKETS[slug]
    baseline = score(version, _log(version, with_e55=False))
    varied_log = _log(version, with_e55=True)
    varied = score(version, varied_log)
    assert baseline.results, slug  # not vacuous: the ticket's rules ran over this log
    # Only the count of events read differs — by the trainee's E55 entries and the ДДС's marks.
    added = len(E55_VALUES) + 1
    assert varied.computed_from_event_count == baseline.computed_from_event_count + added
    same_count = {"computed_from_event_count": baseline.computed_from_event_count}
    assert varied.model_copy(update=same_count) == baseline, slug
    assert report_checksum(varied) == report_checksum(baseline)
    stored = with_previous_scoring_events(varied_log, version)
    assert report_checksum(score(version, stored)) == report_checksum(baseline)
