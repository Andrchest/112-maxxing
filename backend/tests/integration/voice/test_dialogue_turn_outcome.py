"""`DialogueTurnRepository.set_dialogue_outcome` against real PostgreSQL (§20.6, R8 step 6).

`dialogue_turns` is filled by three epics in three passes — E12 the speech boundaries and the
operator transcript, E13 the interpretation and the gate output, E14 the caller side — and §20.6's
rule is that none of them may blank another's columns. A unit test against the in-memory fake can
only say that the fake behaves; these run the statement the adapter actually issues.

The jsonb round trip matters as much as the write: `DialogueContextLoader` rebuilds the
`ALREADY_REVEALED` block from exactly this `gate_output` column on later turns, so a lossy
round trip would silently change what the caller is told it has already said.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable

import pytest
from app.application.dialogue.dialogue_context import (
    allowed_facts_from_gate_output,
    gate_output_document,
)
from app.application.ports.dialogue_turn_repository import DialogueTurnUpsert
from app.domain.common.ids import RoleStageId, SessionId
from app.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tests.unit.application.dialogue._support import gate_package

pytestmark = pytest.mark.integration

INTERPRETATION = {
    "turn_index": 0,
    "speech_act": "QUESTION",
    "requested_facts": [{"fact_id": "address.street", "explicit": True}],
    "operator_assertions": [],
    "confirmation_targets": [],
    "semantic_confidence": 0.95,
    "repair_retry_used": False,
}


@pytest.fixture
async def role_stage_id(
    migrated_engine: AsyncEngine, seeded: dict[str, uuid.UUID], session_id: SessionId
) -> AsyncIterator[RoleStageId]:
    """One committed incident + `role_stages` row — `dialogue_turns.role_stage_id` is NOT NULL."""
    async with migrated_engine.begin() as connection:
        incident_id = (
            await connection.execute(
                text(
                    "INSERT INTO incidents (session_id, scenario_version_id)"
                    " VALUES (:sid, :svid) RETURNING id"
                ),
                {"sid": str(session_id), "svid": str(seeded["scenario_version"])},
            )
        ).scalar_one()
        stage_id = (
            await connection.execute(
                text(
                    "INSERT INTO role_stages (session_id, incident_id, role_type, order_index,"
                    " state) VALUES (:sid, :iid, 'OPERATOR_112', 0, 'CONNECTED') RETURNING id"
                ),
                {"sid": str(session_id), "iid": incident_id},
            )
        ).scalar_one()
    yield RoleStageId(uuid.UUID(str(stage_id)))


async def seed_e12_row(
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    session_id: SessionId,
    role_stage_id: RoleStageId,
    *,
    turn_index: int = 0,
) -> uuid.UUID:
    """The row `AsrTurnResponder` writes before the dialogue chain runs (E12's pass)."""
    transcript_id = uuid.uuid4()
    async with unit_of_work() as uow:
        await uow.dialogue_turns.upsert(
            DialogueTurnUpsert(
                id=uuid.uuid4(),
                session_id=session_id,
                role_stage_id=role_stage_id,
                turn_index=turn_index,
                user_speech_started_offset_ms=1000,
                user_speech_ended_offset_ms=1600,
                operator_transcript_segment_id=None,
                correlation_id=transcript_id,
            )
        )
        await uow.commit()
    return transcript_id


async def test_the_dialogue_outcome_is_written_to_the_four_columns_e13_owns(
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    session_id: SessionId,
    role_stage_id: RoleStageId,
) -> None:
    await seed_e12_row(unit_of_work, session_id, role_stage_id)
    package, decisions = gate_package(("address.street", "address.house"))

    async with unit_of_work() as uow:
        await uow.dialogue_turns.set_dialogue_outcome(
            session_id,
            0,
            interpretation=INTERPRETATION,
            gate_output=gate_output_document(package, decisions),
            planned_text="Улица Николаева, дом 27.",
            fallback_used=False,
        )
        await uow.commit()

    async with unit_of_work() as uow:
        row = await uow.dialogue_turns.get(session_id, 0)

    assert row is not None
    assert row.interpretation["speech_act"] == "QUESTION"
    assert row.planned_text == "Улица Николаева, дом 27."
    assert row.fallback_used is False
    assert [fact["fact_id"] for fact in row.gate_output["allowed"]] == [
        "address.street",
        "address.house",
    ]


async def test_the_gate_output_round_trips_through_jsonb(
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    session_id: SessionId,
    role_stage_id: RoleStageId,
) -> None:
    """`DialogueContextLoader` rebuilds `ALREADY_REVEALED` from this column (R4)."""
    await seed_e12_row(unit_of_work, session_id, role_stage_id)
    package, decisions = gate_package(("address.floor", "address.landmark"))

    async with unit_of_work() as uow:
        await uow.dialogue_turns.set_dialogue_outcome(
            session_id,
            0,
            interpretation=INTERPRETATION,
            gate_output=gate_output_document(package, decisions),
            planned_text="Пятый этаж, напротив магазина.",
            fallback_used=False,
        )
        await uow.commit()

    async with unit_of_work() as uow:
        row = await uow.dialogue_turns.get(session_id, 0)

    assert row is not None
    assert allowed_facts_from_gate_output(row.gate_output) == list(package.allowed)


async def test_e12s_columns_are_not_blanked_by_e13s_pass(
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    session_id: SessionId,
    role_stage_id: RoleStageId,
) -> None:
    """§20.6: "a later epic's pass must not be able to blank an earlier one's"."""
    correlation_id = await seed_e12_row(unit_of_work, session_id, role_stage_id)
    package, decisions = gate_package(("address.street",))

    async with unit_of_work() as uow:
        await uow.dialogue_turns.set_dialogue_outcome(
            session_id,
            0,
            interpretation=INTERPRETATION,
            gate_output=gate_output_document(package, decisions),
            planned_text="Улица Николаева.",
            fallback_used=True,
        )
        await uow.commit()

    async with unit_of_work() as uow:
        row = await uow.dialogue_turns.get(session_id, 0)

    assert row is not None
    assert row.user_speech_started_offset_ms == 1000
    assert row.user_speech_ended_offset_ms == 1600
    assert row.correlation_id == correlation_id
    assert row.fallback_used is True


async def test_e13s_columns_survive_a_later_e12_style_upsert(
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    session_id: SessionId,
    role_stage_id: RoleStageId,
) -> None:
    """The other direction: an `upsert` that says nothing about E13's columns keeps them."""
    await seed_e12_row(unit_of_work, session_id, role_stage_id)
    package, decisions = gate_package(("address.street",))
    async with unit_of_work() as uow:
        await uow.dialogue_turns.set_dialogue_outcome(
            session_id,
            0,
            interpretation=INTERPRETATION,
            gate_output=gate_output_document(package, decisions),
            planned_text="Улица Николаева.",
            fallback_used=True,
        )
        await uow.commit()

    async with unit_of_work() as uow:
        await uow.dialogue_turns.upsert(
            DialogueTurnUpsert(
                id=uuid.uuid4(),
                session_id=session_id,
                role_stage_id=role_stage_id,
                turn_index=0,
                user_speech_started_offset_ms=1000,
                user_speech_ended_offset_ms=1800,
            )
        )
        await uow.commit()

    async with unit_of_work() as uow:
        row = await uow.dialogue_turns.get(session_id, 0)

    assert row is not None
    assert row.user_speech_ended_offset_ms == 1800
    assert row.planned_text == "Улица Николаева."
    assert row.fallback_used is True
    assert row.gate_output["allowed"], "E13's gate output was blanked by E12's pass"


async def test_a_turn_row_that_does_not_exist_is_not_created(
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    session_id: SessionId,
    role_stage_id: RoleStageId,
) -> None:
    """Like `set_speech_end_to_first_audio_ms`: this port has no `role_stage_id` to invent."""
    package, decisions = gate_package(("address.street",))

    async with unit_of_work() as uow:
        await uow.dialogue_turns.set_dialogue_outcome(
            session_id,
            99,
            interpretation=INTERPRETATION,
            gate_output=gate_output_document(package, decisions),
            planned_text="Улица Николаева.",
            fallback_used=False,
        )
        await uow.commit()

    async with unit_of_work() as uow:
        assert await uow.dialogue_turns.get(session_id, 99) is None


async def test_a_fresh_row_reads_back_empty_json_documents(
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    session_id: SessionId,
    role_stage_id: RoleStageId,
) -> None:
    """§20.6's `DEFAULT '{}'::jsonb`, surfaced on the read projection rather than as `None`."""
    await seed_e12_row(unit_of_work, session_id, role_stage_id, turn_index=4)

    async with unit_of_work() as uow:
        row = await uow.dialogue_turns.get(session_id, 4)

    assert row is not None
    assert row.interpretation == {}
    assert row.gate_output == {}
    assert allowed_facts_from_gate_output(row.gate_output) == []


# ---------------------------------------------------------------------------------------------
# E14's pass: the caller side (`set_caller_outcome`, §20.6, §6.4)
# ---------------------------------------------------------------------------------------------


async def seed_caller_transcript(
    migrated_engine: AsyncEngine, session_id: SessionId, text_ru: str
) -> uuid.UUID:
    """One committed `CALLER` transcript row — the FK `caller_transcript_segment_id` points at.

    The sink writes it in the same transaction as `CALLER_UTTERANCE_INTERRUPTED` and updates the
    turn row afterwards, so in the real write path the referent is already committed; here it is
    seeded so the FK has something to resolve.
    """
    async with migrated_engine.begin() as connection:
        return uuid.UUID(
            str(
                (
                    await connection.execute(
                        text(
                            "INSERT INTO transcript_segments"
                            " (session_id, speaker, start_ms, end_ms, text, is_final, turn_index)"
                            " VALUES (:sid, 'CALLER', 0, 100, :t, true, 0) RETURNING id"
                        ),
                        {"sid": str(session_id), "t": text_ru},
                    )
                ).scalar_one()
            )
        )


async def test_the_caller_outcome_is_written_to_the_three_columns_e14_owns(
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    migrated_engine: AsyncEngine,
    session_id: SessionId,
    role_stage_id: RoleStageId,
) -> None:
    """§6.4's "caller turn record": `caller_transcript_segment_id`, `delivered_text`, flag."""
    await seed_e12_row(unit_of_work, session_id, role_stage_id)
    transcript_id = await seed_caller_transcript(migrated_engine, session_id, "Улица Николаева")

    async with unit_of_work() as uow:
        await uow.dialogue_turns.set_caller_outcome(
            session_id,
            0,
            caller_transcript_segment_id=transcript_id,
            delivered_text="Улица Николаева",
            interrupted=True,
        )
        await uow.commit()

    async with unit_of_work() as uow:
        row = await uow.dialogue_turns.get(session_id, 0)

    assert row is not None
    assert row.caller_transcript_segment_id == transcript_id
    assert row.delivered_text == "Улица Николаева"
    assert row.interrupted is True


async def test_e13s_and_e12s_columns_are_not_blanked_by_e14s_pass(
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    session_id: SessionId,
    role_stage_id: RoleStageId,
) -> None:
    """The §20.6 rule the three-pass upsert exists for, now with all three passes in the row."""
    await seed_e12_row(unit_of_work, session_id, role_stage_id)
    package, decisions = gate_package(("address.street",))

    async with unit_of_work() as uow:
        await uow.dialogue_turns.set_dialogue_outcome(
            session_id,
            0,
            interpretation=INTERPRETATION,
            gate_output=gate_output_document(package, decisions),
            planned_text="Улица Николаева, дом 27.",
            fallback_used=False,
        )
        await uow.commit()
    async with unit_of_work() as uow:
        await uow.dialogue_turns.set_caller_outcome(
            session_id,
            0,
            caller_transcript_segment_id=None,
            delivered_text="Улица Николаева",
            interrupted=True,
        )
        await uow.commit()

    async with unit_of_work() as uow:
        row = await uow.dialogue_turns.get(session_id, 0)

    assert row is not None
    # E12's.
    assert row.user_speech_started_offset_ms == 1000
    assert row.user_speech_ended_offset_ms == 1600
    # E13's — in particular `planned_text`, which reads against E14's `delivered_text`.
    assert row.planned_text == "Улица Николаева, дом 27."
    assert row.interpretation["speech_act"] == "QUESTION"
    # E14's.
    assert row.delivered_text == "Улица Николаева"
    assert row.interrupted is True


async def test_a_caller_outcome_for_a_missing_row_creates_nothing(
    unit_of_work: Callable[[], SqlAlchemyUnitOfWork],
    session_id: SessionId,
    role_stage_id: RoleStageId,
) -> None:
    """Like E13's pass: the row was recorded by `AsrTurnResponder`, or there is no honest row."""
    async with unit_of_work() as uow:
        await uow.dialogue_turns.set_caller_outcome(
            session_id,
            7,
            caller_transcript_segment_id=None,
            delivered_text="",
            interrupted=False,
        )
        await uow.commit()

    async with unit_of_work() as uow:
        assert await uow.dialogue_turns.get(session_id, 7) is None
