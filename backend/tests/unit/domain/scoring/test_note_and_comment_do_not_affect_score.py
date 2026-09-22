"""E17 R2: `note_ru` (`RESOURCE_DISPATCHED`) and `comment_ru` (`DDS_INCIDENT_CLOSED`) are trainee
free text, recorded in the event log for the instructor/DDS to read — and nothing else. No
evaluator's evidence path may key off either, so the same log scores identically with and without
them: this is what "score() never reads them" (E17-A brief, R2) means as a test rather than a
promise.

`good_log()` (`_event_log_builders.py`) does not itself set `note_ru`/`comment_ru` — this test
adds them to a copy of the log, which is standing in for "the trainee happened to type a note",
and checks the resulting `ScoreReport` — checksum included — is byte-identical to the bare run's.
"""

from __future__ import annotations

from app.domain.events.session_event import SessionEvent
from app.domain.events.types import EventType
from app.domain.scoring.engine import report_checksum, score

from tests.unit.domain.scoring._event_log_builders import demo_scenario, good_log

SCENARIO = demo_scenario()


def test_note_ru_and_comment_ru_do_not_affect_the_score() -> None:
    bare = good_log()
    annotated = tuple(_with_text(event) for event in bare)

    bare_report = score(SCENARIO, bare)
    annotated_report = score(SCENARIO, annotated)

    assert report_checksum(annotated_report) == report_checksum(bare_report)
    assert annotated_report.total_points == bare_report.total_points
    assert annotated_report.total_max_points == bare_report.total_max_points
    assert annotated_report.critical_errors == bare_report.critical_errors
    assert annotated_report.by_category == bare_report.by_category


def _with_text(event: SessionEvent) -> SessionEvent:
    if event.event_type is EventType.RESOURCE_DISPATCHED:
        return event.model_copy(
            update={"payload": {**event.payload, "note_ru": "Пожар на пятом этаже"}}
        )
    if event.event_type is EventType.DDS_INCIDENT_CLOSED:
        return event.model_copy(
            update={
                "payload": {
                    **event.payload,
                    "comment_ru": "Пожар потушен, разведка подтвердила отсутствие пострадавших",
                }
            }
        )
    return event
