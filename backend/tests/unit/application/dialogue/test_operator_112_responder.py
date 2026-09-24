"""The AI 112 operator's side of a ДДС call to 112 (I3 E6d, HLD `80-telephony.md` §80.3.4, §80.10;
REQ-5332's checklist, D23).

What the E6d row owes here, on fakes (no model, no database):

* every REQ-5332 checklist item the ДДС covers — self-identification, the address, the card it is
  working, the change — is one `DDS_CALL_ASSERTION` with its checklist `field_path`, recognised by
  code (the scoring side is `tests/unit/domain/scoring/test_operator_112_call_scoring.py`);
* the operator asks for what the ДДС omitted, in the memo's order, and says so once all is said;
* a ДДС that never introduces itself asserts no `call.self_identification` — the operator keeps
  asking for it (the penalty is the scoring rule's);
* the operator speaks only its own fixed lines: no card value is ever read out (INV 1), nothing is
  proposed (it reports no status).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import replace
from typing import Any

import pytest
from app.application.dialogue.interpreter import DialogueInterpreter, InterpreterConfig
from app.application.dialogue.responder_context import ChecklistItem, ResponderKnowledge
from app.application.dialogue.responder_templates import (
    CARD_REFERENCE_PATH,
    INCIDENT_CHANGE_PATH,
    LINE_112_ADDRESS_UNCLEAR_RU,
    LINE_112_ALL_STATED_RU,
    OPERATOR_112_CHECKLIST,
    SELF_IDENTIFICATION_PATH,
    ResponderTemplates,
    missing_112_items,
)
from app.application.dialogue.service_head import ServiceHeadResponder
from app.application.dialogue.speech_sink import NullCallerSpeechSink
from app.application.ports.metrics_recorder import NullMetricsRecorder
from app.application.testing.fakes import FakeClock
from app.application.voice.turn_pipeline import TurnContext
from app.domain.dds.call import DdsCallDirection, DdsCallKind
from app.domain.dds.personas import Persona
from app.domain.routing.catalog import ServiceCatalogEntry
from app.inference.llm.fake_llm import FakeLLM
from app.infrastructure.reference.file_catalog import FileReferenceCatalog

from tests.unit.application.dialogue.conftest import (
    CALL_ID,
    DialogueStore,
    make_store,
    make_turn_context,
    make_uow_factory,
    transcribed_turn,
)

PACK = "v046_24-r1"
PROMPTS = dict(OPERATOR_112_CHECKLIST)
VALUES = {
    "address.street": "Академика Королёва",
    "address.house": "12",
    "description.text": "Горит мусор у подъезда",
}


def operator_112() -> Persona:
    personas = FileReferenceCatalog().catalog().personas(PACK)
    assert personas is not None
    persona = personas.get("OPERATOR_112")
    assert persona is not None
    return persona


def service(service_id: str) -> ServiceCatalogEntry:
    services = FileReferenceCatalog().catalog().services(PACK)
    assert services is not None
    entry = services.get(service_id)
    assert entry is not None
    return entry


def knowledge(store: DialogueStore) -> ResponderKnowledge:
    """What the loader builds for a call to 112: the snapshot, its recipients, its address."""
    return ResponderKnowledge(
        session_id=store.session.id,
        call_id=CALL_ID,
        direction=DdsCallDirection.OUTBOUND,
        assignment_id=None,
        service_type=None,
        service=None,
        persona=operator_112(),
        snapshot_values=VALUES,
        checklist=(
            ChecklistItem("address.street", "Улица", VALUES["address.street"]),
            ChecklistItem("address.house", "Дом/Вл", VALUES["address.house"]),
        ),
        steps_due=(),
        steps_pending_count=0,
        leg_status_now=None,
        leg_order_number=None,
        received_at_offset_ms=5_000,
        first_call=True,
        call_history=(),
        proposed_on_this_call=frozenset(),
        now_ms=70_000,
        kind=DdsCallKind.OPERATOR_112,
        recipients=(service("FIRE_RESCUE"), service("POLICE")),
    )


class StoreLoader:
    """The loader's reading of this call's own assertions, over the in-memory store: what the
    real loader folds from the log (`stated_on_this_call`)."""

    def __init__(self, store: DialogueStore, base: ResponderKnowledge) -> None:
        self.store = store
        self.base = base

    async def load(self, session_id: Any, call_id: Any) -> ResponderKnowledge:
        stated: dict[str, bool] = {}
        for payload in self.store.payloads("DDS_CALL_ASSERTION"):
            path = str(payload["field_path"])
            stated[path] = stated.get(path, False) or bool(payload["matches_snapshot"])
        return replace(self.base, stated_on_this_call=stated)


def interpretation(speech_act: str = "STATEMENT") -> str:
    return json.dumps(
        {
            "speech_act": speech_act,
            "requested_facts": [],
            "operator_assertions": [],
            "confirmation_targets": [],
            "semantic_confidence": 0.9,
        }
    )


def operator(
    store: DialogueStore, clock: FakeClock, turns: int
) -> tuple[ServiceHeadResponder, TurnContext]:
    uow_factory = make_uow_factory(store, clock)
    llm = FakeLLM([interpretation() for _ in range(turns)])
    head = ServiceHeadResponder(
        loader=StoreLoader(store, knowledge(store)),  # type: ignore[arg-type]
        interpreter=DialogueInterpreter(llm, NullMetricsRecorder(), config=InterpreterConfig()),
        sink=NullCallerSpeechSink(),
        uow_factory=uow_factory,  # type: ignore[arg-type]
        llm=llm,
    )
    return head, make_turn_context(store, clock, uow_factory)


async def say(head: ServiceHeadResponder, context: TurnContext, lines: list[str]) -> list[str]:
    replies: list[str] = []
    for index, line in enumerate(lines):
        outcome = await head.run_turn(transcribed_turn(line, turn_index=index), context)
        replies.append(outcome.text)
    return replies


@pytest.fixture
def clock() -> FakeClock:
    from datetime import UTC, datetime

    return FakeClock(start=datetime(2026, 1, 1, 0, 1, 10, tzinfo=UTC))


FULL_CALL = [
    "Алло, 112?",
    "Дежурный пожарно-спасательной службы Иванов",
    "Адрес: улица Академика Королёва, дом двенадцать",
    "Работаем по вашей карточке номер 36814851",
    "Ситуация изменилась: огонь перекинулся на гараж, нужна полиция",
]


# ---------------------------------------------------------------------------------------------
# The checklist, item by item
# ---------------------------------------------------------------------------------------------


async def test_every_covered_item_is_an_assertion_and_the_operator_asks_for_the_next(
    clock: FakeClock,
) -> None:
    store = make_store()
    head, context = operator(store, clock, len(FULL_CALL))
    replies = await say(head, context, FULL_CALL)
    assert replies == [
        f"Служба 112, оператор слушает. {PROMPTS[SELF_IDENTIFICATION_PATH]}",
        PROMPTS["address.*"],
        PROMPTS[CARD_REFERENCE_PATH],
        PROMPTS[INCIDENT_CHANGE_PATH],
        LINE_112_ALL_STATED_RU,
    ]
    asserted = {payload["field_path"]: payload for payload in store.payloads("DDS_CALL_ASSERTION")}
    assert set(asserted) == {
        SELF_IDENTIFICATION_PATH,
        "address.street",
        "address.house",
        CARD_REFERENCE_PATH,
        INCIDENT_CHANGE_PATH,
    }
    # The named service («пожарно-спасательной») is one the card was routed to.
    assert asserted[SELF_IDENTIFICATION_PATH]["matches_snapshot"] is True
    assert asserted[SELF_IDENTIFICATION_PATH]["value_ru"] == FULL_CALL[1]
    assert asserted["address.street"]["matches_snapshot"] is True
    assert asserted["address.house"]["matches_snapshot"] is True  # «двенадцать» folds to 12
    assert (
        asserted[CARD_REFERENCE_PATH] | {"value_ru": "36814851", "matches_snapshot": True}
        == (asserted[CARD_REFERENCE_PATH])
    )
    assert asserted[INCIDENT_CHANGE_PATH]["matches_snapshot"] is False
    assert all(payload["call_id"] == CALL_ID for payload in asserted.values())
    # The operator reports no status.
    assert store.payloads("DDS_CALL_STATUS_PROPOSED") == []


async def test_one_utterance_can_cover_the_whole_checklist(clock: FakeClock) -> None:
    store = make_store()
    head, context = operator(store, clock, 1)
    [reply] = await say(
        head,
        context,
        [
            "Дежурный полиции Петров. Работаем по карточке с улицы Академика Королёва дом 12, "
            "обстановка изменилась, требуется скорая."
        ],
    )
    assert reply == f"Служба 112, оператор слушает. {LINE_112_ALL_STATED_RU}"
    assert (
        missing_112_items(
            {p["field_path"]: p["matches_snapshot"] for p in store.payloads("DDS_CALL_ASSERTION")},
            knowledge(store).checklist,
        )
        == ()
    )


async def test_a_dds_that_never_introduces_itself_asserts_no_self_identification(
    clock: FakeClock,
) -> None:
    """The penalty's evidence: no `call.self_identification` assertion on the call, and the
    operator asks for it again after every other item."""
    store = make_store()
    lines = [
        "Улица Академика Королёва, дом 12",
        "Работаем по карточке",
        "Обстановка изменилась, нужна полиция",
    ]
    head, context = operator(store, clock, len(lines))
    replies = await say(head, context, lines)
    ask = PROMPTS[SELF_IDENTIFICATION_PATH]
    assert replies == [f"Служба 112, оператор слушает. {ask}", ask, ask]
    paths = {payload["field_path"] for payload in store.payloads("DDS_CALL_ASSERTION")}
    assert SELF_IDENTIFICATION_PATH not in paths
    assert {CARD_REFERENCE_PATH, INCIDENT_CHANGE_PATH, "address.street"} <= paths


async def test_a_service_the_card_was_not_routed_to_does_not_match(clock: FakeClock) -> None:
    store = make_store()
    head, context = operator(store, clock, 1)
    await say(head, context, ["Дежурный Мосводоканала Сидоров"])
    [identified] = store.payloads("DDS_CALL_ASSERTION")
    assert identified["field_path"] == SELF_IDENTIFICATION_PATH
    assert identified["matches_snapshot"] is False


async def test_a_wrong_address_is_asked_again(clock: FakeClock) -> None:
    store = make_store()
    lines = ["Дежурный пожарной охраны Иванов", "Адрес улица Ленина"]
    uow_factory = make_uow_factory(store, clock)
    llm = FakeLLM(
        [
            interpretation(),
            json.dumps(
                {
                    "speech_act": "STATEMENT",
                    "requested_facts": [],
                    "operator_assertions": [
                        {"fact_id": "address", "asserted_value": "улица Ленина"}
                    ],
                    "confirmation_targets": [],
                    "semantic_confidence": 0.9,
                }
            ),
        ]
    )
    head = ServiceHeadResponder(
        loader=StoreLoader(store, knowledge(store)),  # type: ignore[arg-type]
        interpreter=DialogueInterpreter(llm, NullMetricsRecorder(), config=InterpreterConfig()),
        sink=NullCallerSpeechSink(),
        uow_factory=uow_factory,  # type: ignore[arg-type]
        llm=llm,
    )
    replies = await say(head, make_turn_context(store, clock, uow_factory), lines)
    assert replies[-1] == LINE_112_ADDRESS_UNCLEAR_RU
    wrong = [p for p in store.payloads("DDS_CALL_ASSERTION") if p["field_path"] == "address.street"]
    assert [p["matches_snapshot"] for p in wrong] == [False]


async def test_an_item_is_asserted_once_per_call(clock: FakeClock) -> None:
    store = make_store()
    lines = ["Дежурный пожарной охраны Иванов", "Ещё раз: дежурный пожарной охраны Иванов"]
    head, context = operator(store, clock, len(lines))
    await say(head, context, lines)
    paths = [payload["field_path"] for payload in store.payloads("DDS_CALL_ASSERTION")]
    assert paths.count(SELF_IDENTIFICATION_PATH) == 1


async def test_the_operator_never_reads_a_card_value_out(clock: FakeClock) -> None:
    """INV 1: every line is the persona's greeting and one of its fixed lines — which are a
    function of the persona alone (`static_lines`), so no card value can be among them."""
    store = make_store()
    head, context = operator(store, clock, len(FULL_CALL))
    replies = await say(head, context, FULL_CALL)
    fixed = set(ResponderTemplates().static_lines(operator_112()))
    for reply in replies:
        remainder = reply.removeprefix(operator_112().greeting_ru).strip()
        assert remainder in fixed, reply


def test_the_service_head_plan_is_unchanged_by_the_kind_default() -> None:
    """A `ResponderKnowledge` built without the E6d keys is a service head's (E6c unchanged)."""
    store = make_store()
    head_knowledge = replace(
        knowledge(store),
        kind=DdsCallKind.SERVICE_HEAD,
        assignment_id=uuid.uuid4(),
        recipients=(),
    )
    assert head_knowledge.kind is DdsCallKind.SERVICE_HEAD
    assert ResponderKnowledge.__dataclass_fields__["kind"].default is DdsCallKind.SERVICE_HEAD
