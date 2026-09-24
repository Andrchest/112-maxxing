"""The service head's side of a ДДС call (I3 E6c, HLD `80-telephony.md` §80.4, D24).

What the E6c row owes here, on fakes (no model, no database):

* the first call asks the snapshot's checklist, and the trainee's statements are matched **by code**
  into `DDS_CALL_ASSERTION`s;
* a later call reports exactly the due steps — one `DDS_CALL_STATUS_PROPOSED` each, after the line
  was heard — and a not-yet-due step is never spoken (INV 2), in `template` **and** `llm` mode;
* no scenario value outside the head's knowledge is ever spoken (INV 1): the `llm` paraphrase is
  checked by code and a leak, an unlisted number or a model failure is the template line with
  `MODEL_FALLBACK_USED` (INV 14);
* a barge-in (the line cancelled) proposes nothing;
* INV 3's constructor pattern for `ResponderContextLoader` and the `test_r3` signature pattern for
  `ResponderPromptBuilder`.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
from app.application.dialogue.interpreter import (
    RESPONDER_SLOTS,
    DialogueInterpreter,
    InterpretedUtterance,
    InterpreterConfig,
)
from app.application.dialogue.responder_context import (
    ChecklistItem,
    DueStep,
    ResponderContextLoader,
    ResponderKnowledge,
)
from app.application.dialogue.responder_prompt_builder import (
    ResponderPromptBuilder,
    responder_line_violations,
)
from app.application.dialogue.responder_templates import (
    LINE_IN_TRANSIT_RU,
    LINE_REPEAT_RU,
    ResponderTemplates,
)
from app.application.dialogue.service_head import ServiceHeadResponder
from app.application.dialogue.speech_sink import NullCallerSpeechSink, PlannedCallerUtterance
from app.application.ports.metrics_recorder import NullMetricsRecorder
from app.application.testing.fakes import FakeClock
from app.application.voice.turn_pipeline import TurnContext
from app.domain.dds.call import DdsCallDirection
from app.domain.dds.personas import Persona
from app.domain.dds.responders import ScriptedStep
from app.domain.dds.response import ServiceResponseStatus
from app.domain.enums import SpeechAct
from app.domain.facts.definitions import FactDefinition
from app.inference.llm.fake_llm import FakeLLM
from app.infrastructure.reference.file_catalog import FileReferenceCatalog

from tests.unit.application.dialogue._support import demo_definitions
from tests.unit.application.dialogue.conftest import (
    CALL_ID,
    DialogueStore,
    make_store,
    make_turn_context,
    make_uow_factory,
    transcribed_turn,
)

BACKEND = Path(__file__).resolve().parents[4]
DIALOGUE = BACKEND / "app" / "application" / "dialogue"
RECEIVED_AT = 5_000

_S = ServiceResponseStatus

SCRIPT: tuple[ScriptedStep, ...] = (
    ScriptedStep(after_ms=0, status=_S.RECEIVED),
    ScriptedStep(after_ms=15_000, status=_S.ACCEPTED),
    ScriptedStep(after_ms=60_000, status=_S.RESPONSE_STARTED, order_number="2415"),
    ScriptedStep(after_ms=180_000, status=_S.ARRIVED, comment_ru="Прибыли к подъезду 7"),
    ScriptedStep(after_ms=200_000, status=_S.WORKING),
    ScriptedStep(after_ms=600_000, status=_S.COMPLETED, order_number="9931"),
)
"""A FIRE_RESCUE script whose pending steps carry words and numbers no due step has."""

PENDING_WORDS = ("Прибыли на место", "подъезду 7", "9931", "Работаем на месте", "Работы завершили")


def brigade_101() -> Persona:
    personas = FileReferenceCatalog().catalog().personas("v046_24-r1")
    assert personas is not None
    persona = personas.get("BRIGADE_101")
    assert persona is not None
    return persona


def knowledge(
    store: DialogueStore, *, first_call: bool, now_ms: int = 70_000
) -> ResponderKnowledge:
    due = tuple(
        DueStep(index=index, step=step, due_offset_ms=RECEIVED_AT + step.after_ms)
        for index, step in enumerate(SCRIPT)
        if step.status is not _S.RECEIVED and RECEIVED_AT + step.after_ms <= now_ms
    )
    values = {
        "address.street": "Академика Королёва",
        "address.house": "12",
        "description.text": "Горит мусор у подъезда",
    }
    return ResponderKnowledge(
        session_id=store.session.id,
        call_id=CALL_ID,
        direction=DdsCallDirection.OUTBOUND,
        assignment_id=uuid.uuid5(uuid.NAMESPACE_URL, "leg:fire"),
        service_type="FIRE_RESCUE",
        service=None,
        persona=brigade_101(),
        snapshot_values=values,
        checklist=(
            ChecklistItem("address.street", "Улица", values["address.street"]),
            ChecklistItem("address.house", "Дом/Вл", values["address.house"]),
            ChecklistItem(
                "description.text", "Описание со слов заявителя", values["description.text"]
            ),
        ),
        steps_due=due,
        steps_pending_count=len(SCRIPT) - 1 - len(due),
        leg_status_now=_S.ADDED,
        leg_order_number=None,
        received_at_offset_ms=RECEIVED_AT,
        first_call=first_call,
        call_history=(),
        proposed_on_this_call=frozenset(),
        now_ms=now_ms,
    )


def _dataclass_replace(item: ResponderKnowledge, **changes: Any) -> ResponderKnowledge:
    from dataclasses import replace

    return replace(item, **changes)


class FixedLoader:
    """A `ResponderContextLoader` stand-in: the same knowledge on every turn."""

    def __init__(self, value: ResponderKnowledge) -> None:
        self.value = value

    async def load(self, session_id: Any, call_id: Any) -> ResponderKnowledge:
        return self.value


def interpretation(
    speech_act: str = "QUESTION",
    requested: tuple[str, ...] = (),
    assertions: tuple[tuple[str, str], ...] = (),
) -> str:
    return json.dumps(
        {
            "speech_act": speech_act,
            "requested_facts": [{"fact_id": slot, "explicit": True} for slot in requested],
            "operator_assertions": [
                {"fact_id": slot, "asserted_value": value} for slot, value in assertions
            ],
            "confirmation_targets": [],
            "semantic_confidence": 0.9,
        }
    )


def leak_values(_session_id: Any) -> Any:
    async def read() -> list[str]:
        return scenario_values(demo_definitions())

    return read()


def scenario_values(definitions: dict[str, FactDefinition]) -> list[str]:
    values: list[str] = []
    for definition in definitions.values():
        for value in (definition.world_value, definition.caller_value):
            if isinstance(value, str) and value.strip():
                values.append(value)
            elif isinstance(value, int) and not isinstance(value, bool):
                values.append(str(value))
    return values


def responder(
    store: DialogueStore,
    clock: FakeClock,
    known: ResponderKnowledge,
    script: list[Any],
    *,
    mode: str = "template",
    sink: Any = None,
) -> tuple[ServiceHeadResponder, Any, TurnContext]:
    uow_factory = make_uow_factory(store, clock)
    llm = FakeLLM(script)
    head = ServiceHeadResponder(
        loader=FixedLoader(known),  # type: ignore[arg-type]
        interpreter=DialogueInterpreter(llm, NullMetricsRecorder(), config=InterpreterConfig()),
        sink=sink if sink is not None else NullCallerSpeechSink(),
        uow_factory=uow_factory,  # type: ignore[arg-type]
        mode=mode,  # type: ignore[arg-type]
        llm=llm,
        leak_values=leak_values,
    )
    return head, sink, make_turn_context(store, clock, uow_factory)


@pytest.fixture
def clock() -> FakeClock:
    from datetime import UTC, datetime

    return FakeClock(start=datetime(2026, 1, 1, 0, 1, 10, tzinfo=UTC))


# ---------------------------------------------------------------------------------------------
# The first call: the checklist, and assertions matched by code
# ---------------------------------------------------------------------------------------------


async def test_the_first_call_greets_and_asks_the_checklist(clock: FakeClock) -> None:
    store = make_store()
    head, _sink, context = responder(
        store, clock, knowledge(store, first_call=True), [interpretation("GREETING")]
    )
    outcome = await head.run_turn(transcribed_turn("Алло, пожарная?"), context)
    assert outcome.text == "Начальник караула, слушаю. Диктуйте: адрес, что случилось."
    assert outcome.plan.template_row == "CHECKLIST"
    assert store.payloads("DDS_CALL_STATUS_PROPOSED") == []


async def test_stated_card_facts_become_assertions_matched_by_code(clock: FakeClock) -> None:
    store = make_store()
    head, _sink, context = responder(
        store,
        clock,
        knowledge(store, first_call=True),
        [
            interpretation("GREETING"),
            interpretation("STATEMENT", assertions=(("address", "Королёва 14"),)),
        ],
    )
    await head.run_turn(transcribed_turn("Алло?"), context)
    # «двенадцать» folds to 12 (§7.2): the house matches though it was spoken as a numeral.
    outcome = await head.run_turn(
        transcribed_turn("Горит мусор у подъезда, Академика Королёва дом двенадцать", turn_index=1),
        context,
    )
    assertions = {
        payload["field_path"]: payload for payload in store.payloads("DDS_CALL_ASSERTION")
    }
    assert assertions["address.street"]["matches_snapshot"] is True
    assert assertions["address.house"]["matches_snapshot"] is True
    assert assertions["description.text"]["matches_snapshot"] is True
    assert all(payload["call_id"] == CALL_ID for payload in assertions.values())
    assert outcome.text == "Принял."


async def test_a_statement_that_contradicts_the_snapshot_is_a_false_assertion(
    clock: FakeClock,
) -> None:
    store = make_store()
    known = knowledge(store, first_call=True)
    plan = ResponderTemplates().plan(
        known,
        InterpretedUtterance.model_validate_json(
            interpretation("STATEMENT", assertions=(("address", "Ленина 5"),))
        ),
        "Адрес Ленина 5",
        greeted=True,
    )
    assert [
        (item.field_path, item.value_ru, item.matches_snapshot) for item in plan.assertions
    ] == [("address.street", "Ленина 5", False)]


# ---------------------------------------------------------------------------------------------
# A later call: the due steps, and only those (INV 2)
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["template", "llm"])
async def test_a_later_call_reports_exactly_the_due_steps(clock: FakeClock, mode: str) -> None:
    store = make_store()
    script = [interpretation(requested=("status",))]
    if mode == "llm":
        script.append(json.dumps({"utterance": "Приняли вызов, выехали, наряд 2415."}))
    head, _sink, context = responder(
        store, clock, knowledge(store, first_call=False), script, mode=mode
    )
    outcome = await head.run_turn(transcribed_turn("Вы уже выехали?"), context)
    proposals = store.payloads("DDS_CALL_STATUS_PROPOSED")
    assert [
        (item["status"], item["due_offset_ms"], item["script_after_ms"]) for item in proposals
    ] == [
        ("ACCEPTED", 20_000, 15_000),
        ("RESPONSE_STARTED", 65_000, 60_000),
    ]
    assert proposals[1]["order_number"] == "2415"
    assert all(item["call_id"] == CALL_ID for item in proposals)
    for word in PENDING_WORDS:  # INV 2: a pending step's words are never spoken
        assert word not in outcome.text
    if mode == "llm":
        assert outcome.source == "LLM"
    else:
        assert outcome.text == (
            "Начальник караула, слушаю. Докладываю. Вызов приняли. Выехали, наряд 2415."
        )


@pytest.mark.parametrize("mode", ["template", "llm"])
async def test_nothing_due_is_never_filled_with_a_pending_step(clock: FakeClock, mode: str) -> None:
    """INV 2 by construction: with nothing due the head says «Пока …», whatever the model says."""
    store = make_store()
    known = _dataclass_replace(
        knowledge(store, first_call=False, now_ms=60_000),
        steps_due=(),
        leg_status_now=_S.RESPONSE_STARTED,
    )
    script = [interpretation(requested=("status",))]
    if mode == "llm":  # the model tries to announce the pending arrival — the check refuses it
        script.append(json.dumps({"utterance": "Прибыли на место, у подъезда 7."}))
    head, _sink, context = responder(store, clock, known, script, mode=mode)
    outcome = await head.run_turn(transcribed_turn("Вы на месте?"), context)
    assert outcome.text.endswith(LINE_IN_TRANSIT_RU)
    assert store.payloads("DDS_CALL_STATUS_PROPOSED") == []
    for word in PENDING_WORDS:
        assert word not in outcome.text
    if mode == "llm":
        assert "MODEL_FALLBACK_USED" in store.event_types


async def test_a_step_already_proposed_on_this_call_is_not_proposed_again(
    clock: FakeClock,
) -> None:
    store = make_store()
    known = _dataclass_replace(
        knowledge(store, first_call=False),
        proposed_on_this_call=frozenset({("ACCEPTED", 20_000)}),
    )
    head, _sink, context = responder(store, clock, known, [interpretation(requested=("status",))])
    await head.run_turn(transcribed_turn("Что у вас?"), context)
    assert [item["status"] for item in store.payloads("DDS_CALL_STATUS_PROPOSED")] == [
        "RESPONSE_STARTED"
    ]


async def test_an_unintelligible_turn_asks_to_repeat(clock: FakeClock) -> None:
    store = make_store()
    head, _sink, context = responder(
        store, clock, knowledge(store, first_call=False), [interpretation("UNINTELLIGIBLE")]
    )
    outcome = await head.run_turn(transcribed_turn("ммм"), context)
    assert outcome.text.endswith(LINE_REPEAT_RU)
    assert store.payloads("DDS_CALL_STATUS_PROPOSED") == []


async def test_an_eta_is_never_invented(clock: FakeClock) -> None:
    store = make_store()
    head, _sink, context = responder(
        store, clock, knowledge(store, first_call=False), [interpretation(requested=("eta",))]
    )
    outcome = await head.run_turn(transcribed_turn("Когда будете на месте?"), context)
    assert outcome.text.endswith("Время прибытия уточню, доложу.")


async def test_an_inbound_call_reports_on_the_first_reply(clock: FakeClock) -> None:
    """A brigade's `CALL_IN` call: the head called to report, so it reports at once."""
    store = make_store()
    known = _dataclass_replace(
        knowledge(store, first_call=True), direction=DdsCallDirection.INBOUND
    )
    head, _sink, context = responder(store, clock, known, [interpretation("GREETING")])
    outcome = await head.run_turn(transcribed_turn("ДДС, слушаю"), context)
    assert "Докладываю." in outcome.text
    assert len(store.payloads("DDS_CALL_STATUS_PROPOSED")) == 2


# ---------------------------------------------------------------------------------------------
# INV 1 / INV 14 in `llm` mode: the checked paraphrase
# ---------------------------------------------------------------------------------------------


async def test_llm_a_scenario_value_outside_the_knowledge_is_never_spoken(
    clock: FakeClock,
) -> None:
    """INV 1: the model names a world value the head does not know — the template is spoken."""
    store = make_store()
    leak = next(value for value in scenario_values(demo_definitions()) if len(value) > 4)
    head, _sink, context = responder(
        store,
        clock,
        knowledge(store, first_call=False),
        [interpretation(requested=("status",)), json.dumps({"utterance": f"Выехали, там {leak}."})],
        mode="llm",
    )
    outcome = await head.run_turn(transcribed_turn("Что у вас?"), context)
    assert leak not in outcome.text
    assert outcome.source == "FALLBACK"
    fallback = store.payloads("MODEL_FALLBACK_USED")[-1]
    assert fallback["component"] == "GENERATOR" and "LEAK" in fallback["reason"]


async def test_llm_an_unlisted_number_is_refused(clock: FakeClock) -> None:
    store = make_store()
    head, _sink, context = responder(
        store,
        clock,
        knowledge(store, first_call=False),
        [
            interpretation(requested=("status",)),
            json.dumps({"utterance": "Выехали, будем через 7 минут, наряд 2415."}),
        ],
        mode="llm",
    )
    outcome = await head.run_turn(transcribed_turn("Что у вас?"), context)
    assert "7 минут" not in outcome.text
    assert "NUMBER_NOT_ALLOWED" in store.payloads("MODEL_FALLBACK_USED")[-1]["reason"]


async def test_llm_a_model_failure_is_the_template_line_and_the_call_goes_on(
    clock: FakeClock,
) -> None:
    """INV 14: the model raises; the head still answers, the proposals still stand."""
    from app.application.ports.llm import LlmUnavailableError

    store = make_store()
    head, _sink, context = responder(
        store,
        clock,
        knowledge(store, first_call=False),
        [interpretation(requested=("status",)), LlmUnavailableError("down")],
        mode="llm",
    )
    outcome = await head.run_turn(transcribed_turn("Что у вас?"), context)
    assert outcome.source == "FALLBACK"
    assert outcome.text.startswith("Начальник караула, слушаю. Докладываю.")
    assert len(store.payloads("DDS_CALL_STATUS_PROPOSED")) == 2
    assert store.payloads("MODEL_FALLBACK_USED")[-1]["reason"] == "LlmUnavailableError"


async def test_template_mode_never_calls_the_model_for_words(clock: FakeClock) -> None:
    store = make_store()
    head, _sink, context = responder(
        store, clock, knowledge(store, first_call=False), [interpretation(requested=("status",))]
    )
    outcome = await head.run_turn(transcribed_turn("Что у вас?"), context)
    assert outcome.source == "FALLBACK"
    assert "MODEL_FALLBACK_USED" not in store.event_types


def test_the_line_check_reads_numbers_and_leaks() -> None:
    allowed = ["Выехали, наряд 2415."]
    assert (
        responder_line_violations("Выехали, наряд две тысячи четыреста пятнадцать.", allowed, [])
        == []
    )
    assert "NUMBER_NOT_ALLOWED" in responder_line_violations("Выехали, наряд 7.", allowed, [])
    assert "LEAK" in responder_line_violations("Горит квартира 27", allowed, ["квартира 27"])
    assert responder_line_violations("   ", allowed, []) == ["EMPTY"]


# ---------------------------------------------------------------------------------------------
# A barge-in proposes nothing
# ---------------------------------------------------------------------------------------------


class CancelledSink:
    """A sink whose playback is cut by a barge-in (the pipeline cancels `speak`)."""

    def __init__(self) -> None:
        self.spoken: list[PlannedCallerUtterance] = []

    async def speak(self, planned: PlannedCallerUtterance, context: TurnContext) -> None:
        self.spoken.append(planned)
        raise asyncio.CancelledError


async def test_a_barge_in_before_the_end_proposes_nothing(clock: FakeClock) -> None:
    store = make_store()
    head, sink, context = responder(
        store,
        clock,
        knowledge(store, first_call=False),
        [interpretation(requested=("status",))],
        sink=CancelledSink(),
    )
    with pytest.raises(asyncio.CancelledError):
        await head.run_turn(transcribed_turn("Что у вас?"), context)
    assert sink.spoken  # the line was being said…
    assert store.payloads("DDS_CALL_STATUS_PROPOSED") == []  # …but never heard to its end


# ---------------------------------------------------------------------------------------------
# The persona's fixed lines, the slot catalog
# ---------------------------------------------------------------------------------------------


def test_the_fixed_lines_of_a_persona_are_what_the_voice_agent_pre_synthesises() -> None:
    lines = ResponderTemplates().static_lines(brigade_101())
    assert lines[0] == "Начальник караула, слушаю."
    assert LINE_REPEAT_RU in lines and LINE_IN_TRANSIT_RU in lines
    assert "Прибыли на место." in lines
    assert len(lines) == len(set(lines))


def test_the_responder_slot_catalog_is_value_free() -> None:
    assert RESPONDER_SLOTS == ("status", "order_number", "address", "victims", "eta")
    assert SpeechAct.UNINTELLIGIBLE.value == "UNINTELLIGIBLE"


# ---------------------------------------------------------------------------------------------
# INV 3 (constructor) and `test_r3` (signature) patterns
# ---------------------------------------------------------------------------------------------

FORBIDDEN_NAMES = (
    "WorldTruth",
    "CallerBelief",
    "ScenarioVersion",
    "FactDefinition",
    "OperatorCard",
)
FORBIDDEN_MODULES = (
    "app.domain.layers.world_truth",
    "app.domain.layers.caller_belief",
    "app.domain.facts.definitions",
    "app.domain.scenario",
    "app.application.dialogue.forbidden_values",
    "app.application.dialogue.dialogue_context",
)


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
        elif isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
    return found


def test_the_context_loader_is_constructed_without_world_truth_or_caller_belief() -> None:
    """INV 3's pattern: what the loader is *handed* decides what it can read."""
    signature = inspect.signature(ResponderContextLoader.__init__)
    assert list(signature.parameters) == ["self", "unit_of_work", "clock", "scripts", "reference"]
    rendered = " | ".join(str(parameter.annotation) for parameter in signature.parameters.values())
    assert not [name for name in FORBIDDEN_NAMES if name in rendered]
    for module in _imports(DIALOGUE / "responder_context.py"):
        assert not module.startswith(FORBIDDEN_MODULES), module
    source = (DIALOGUE / "responder_context.py").read_text(encoding="utf-8")
    assert "world_truth" not in source.replace("WorldTruth", "")
    assert "caller_belief" not in source


def test_the_knowledge_holds_no_layer_but_the_snapshot() -> None:
    fields = {
        name: str(annotation) for name, annotation in ResponderKnowledge.__annotations__.items()
    }
    assert not [
        name for name in FORBIDDEN_NAMES for annotation in fields.values() if name in annotation
    ]
    assert "snapshot_values" in fields and "steps_due" in fields


def test_the_prompt_builder_takes_the_persona_and_the_knowledge_and_nothing_else() -> None:
    """The `test_r3` pattern: the parameter list is the boundary, read off one line."""
    signature = inspect.signature(ResponderPromptBuilder.build)
    assert list(signature.parameters) == [
        "self",
        "persona",
        "known_facts",
        "window",
        "utterance",
        "template_line",
    ]
    rendered = " | ".join(str(parameter.annotation) for parameter in signature.parameters.values())
    assert not [name for name in FORBIDDEN_NAMES if name in rendered]
    for path in (DIALOGUE / "responder_prompt_builder.py", DIALOGUE / "responder_templates.py"):
        for module in _imports(path):
            assert not module.startswith(FORBIDDEN_MODULES), (path.name, module)


def test_the_prompt_carries_only_the_knowledge() -> None:
    """INV 1 on the rendered text: no demo world/caller value reaches the paraphrase prompt."""
    messages = ResponderPromptBuilder().build(
        brigade_101(),
        ["Улица: Академика Королёва", "Выехали, наряд 2415."],
        (),
        "Что у вас?",
        "Выехали.",
    )
    text = "\n".join(message.content for message in messages)
    assert "Академика Королёва" in text and "2415" in text
    for value in scenario_values(demo_definitions()):
        if len(value) > 3:
            assert value not in text
