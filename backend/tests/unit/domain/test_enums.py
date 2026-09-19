"""SPEC-driven tests for `app.domain.enums` and `app.domain.events.types.EventType`.

These tests parse `docs/SPEC.md` at test time (never a copy-pasted snapshot of it) and assert:

1. every ALL_CAPS token SPEC lists in §1 (session modes), §5 (knowledge states, disclosure
   policies), §7 (session / Operator 112 / DDS states), §8 (event types) and §28 (evaluator
   types) is a member of the matching enum;
2. §12's four event kinds (spelled as class names in SPEC) map onto `WorldEventKind` the way HLD
   `10-domain-model.md` §10.2 spells them;
3. every member of every enum in `app.domain.enums`, plus `EventType`, has `member.name ==
   member.value`.

If SPEC.md itself changes shape, these tests should fail loudly rather than silently pass.
"""

from __future__ import annotations

import inspect
import re
from enum import Enum
from pathlib import Path

import pytest
from app.domain import enums
from app.domain.events.types import EventType

SPEC_PATH = Path(__file__).resolve().parents[4] / "docs" / "SPEC.md"

# A heading line looks like "# 7. SIMULATION STATE MACHINE".
_HEADING_RE = re.compile(r"^# (\d+)\. .+$", re.MULTILINE)

# A bare or "- "-prefixed ALL_CAPS token line, e.g. "CREATED" or "- SINGLE_ROLE".
_ALL_CAPS_TOKEN_RE = re.compile(r"^-?\s*([A-Z][A-Z0-9_]*)\s*$")

# A bare or "- "-prefixed PascalCase token line, e.g. "- TimedEvent" (SPEC §12).
_PASCAL_TOKEN_RE = re.compile(r"^-?\s*([A-Z][A-Za-z0-9]*)\s*$")


def _sections(spec_text: str) -> dict[int, str]:
    """Split `spec_text` into `{section_number: body_text_until_next_heading}`."""
    headings = list(_HEADING_RE.finditer(spec_text))
    assert headings, "docs/SPEC.md has no '# N. TITLE' headings — parsing is broken"
    sections: dict[int, str] = {}
    for index, match in enumerate(headings):
        number = int(match.group(1))
        start = match.end()
        end = headings[index + 1].start() if index + 1 < len(headings) else len(spec_text)
        sections[number] = spec_text[start:end]
    return sections


def _tokens_after(text: str, marker: str, token_re: re.Pattern[str]) -> list[str]:
    """The run of `token_re` matches on the lines right after `marker`, up to the next blank line.

    Blank lines before the first match are skipped (the marker line and the list are usually
    separated by one blank line in SPEC.md's prose style).
    """
    assert marker in text, f"marker {marker!r} not found in the expected SPEC section"
    tail = text[text.index(marker) + len(marker) :]
    tokens: list[str] = []
    for line in tail.splitlines():
        stripped = line.strip()
        if not stripped:
            if tokens:
                break
            continue
        match = token_re.match(stripped)
        if match is None:
            if tokens:
                break
            continue
        tokens.append(match.group(1))
    assert tokens, f"no tokens found after marker {marker!r}"
    return tokens


SPEC_TEXT = SPEC_PATH.read_text(encoding="utf-8")
SPEC_SECTIONS = _sections(SPEC_TEXT)

SESSION_MODES = _tokens_after(
    SPEC_SECTIONS[1],
    "Supported session modes must be represented architecturally:",
    _ALL_CAPS_TOKEN_RE,
)
KNOWLEDGE_STATES = _tokens_after(SPEC_SECTIONS[5], "Knowledge states:", _ALL_CAPS_TOKEN_RE)
DISCLOSURE_POLICIES = _tokens_after(SPEC_SECTIONS[5], "Disclosure policies:", _ALL_CAPS_TOKEN_RE)
SESSION_STATES = _tokens_after(SPEC_SECTIONS[7], "Top-level session states:", _ALL_CAPS_TOKEN_RE)
OPERATOR_112_STATES = _tokens_after(
    SPEC_SECTIONS[7], "Operator 112 stage should support at least:", _ALL_CAPS_TOKEN_RE
)
DDS_STATES = _tokens_after(
    SPEC_SECTIONS[7], "DDS stage should support at least:", _ALL_CAPS_TOKEN_RE
)
SPEC_EVENT_TYPE_TOKENS = _tokens_after(
    SPEC_SECTIONS[8], "Include event types for at least:", _ALL_CAPS_TOKEN_RE
)
WORLD_EVENT_KIND_CLASS_NAMES = _tokens_after(
    SPEC_SECTIONS[12], "Implement event types:", _PASCAL_TOKEN_RE
)
EVALUATOR_TYPES = _tokens_after(
    SPEC_SECTIONS[28], "Required evaluator concepts include:", _ALL_CAPS_TOKEN_RE
)

# §12 spells the four world event kinds as class names; HLD §10.2 spells the matching
# `WorldEventKind` members. This mapping is the translation, not a re-decision of either.
WORLD_EVENT_KIND_SPEC_TO_HLD = {
    "TimedEvent": "TIMED",
    "ConditionalEvent": "CONDITIONAL",
    "ActionTriggeredEvent": "ACTION_TRIGGERED",
    "SeededRandomEvent": "SEEDED_RANDOM",
}


@pytest.mark.parametrize("token", SESSION_MODES)
def test_spec_session_mode_is_covered(token: str) -> None:
    assert token in enums.SessionMode.__members__, f"SPEC §1 session mode {token} missing"


@pytest.mark.parametrize("token", KNOWLEDGE_STATES)
def test_spec_knowledge_state_is_covered(token: str) -> None:
    assert token in enums.KnowledgeState.__members__, f"SPEC §5 knowledge state {token} missing"


@pytest.mark.parametrize("token", DISCLOSURE_POLICIES)
def test_spec_disclosure_policy_is_covered(token: str) -> None:
    assert token in enums.DisclosurePolicy.__members__, f"SPEC §5 disclosure policy {token} missing"


@pytest.mark.parametrize("token", SESSION_STATES)
def test_spec_session_state_is_covered(token: str) -> None:
    assert token in enums.SessionState.__members__, f"SPEC §7 session state {token} missing"


@pytest.mark.parametrize("token", OPERATOR_112_STATES)
def test_spec_operator_112_stage_state_is_covered(token: str) -> None:
    assert token in enums.Operator112StageState.__members__, (
        f"SPEC §7 Operator 112 stage state {token} missing"
    )


@pytest.mark.parametrize("token", DDS_STATES)
def test_spec_dds_stage_state_is_covered(token: str) -> None:
    assert token in enums.DDSStageState.__members__, f"SPEC §7 DDS stage state {token} missing"


def test_spec_section_8_has_28_event_types() -> None:
    assert len(SPEC_EVENT_TYPE_TOKENS) == 28


@pytest.mark.parametrize("token", SPEC_EVENT_TYPE_TOKENS)
def test_spec_event_type_is_covered(token: str) -> None:
    assert token in EventType.__members__, f"SPEC §8 event type {token} missing from EventType"


def test_spec_section_12_lists_exactly_the_four_world_event_kinds() -> None:
    assert set(WORLD_EVENT_KIND_CLASS_NAMES) == set(WORLD_EVENT_KIND_SPEC_TO_HLD)


@pytest.mark.parametrize("class_name", WORLD_EVENT_KIND_CLASS_NAMES)
def test_spec_world_event_kind_is_covered(class_name: str) -> None:
    hld_member = WORLD_EVENT_KIND_SPEC_TO_HLD[class_name]
    assert hld_member in enums.WorldEventKind.__members__, (
        f"SPEC §12 {class_name} (-> {hld_member}) missing from WorldEventKind"
    )


@pytest.mark.parametrize("token", EVALUATOR_TYPES)
def test_spec_evaluator_type_is_covered(token: str) -> None:
    assert token in enums.EvaluatorType.__members__, f"SPEC §28 evaluator type {token} missing"


def _all_str_enum_classes() -> list[type[Enum]]:
    classes = [
        member
        for _, member in inspect.getmembers(enums, inspect.isclass)
        if issubclass(member, Enum) and member.__module__ == enums.__name__
    ]
    classes.append(EventType)
    return classes


@pytest.mark.parametrize("enum_cls", _all_str_enum_classes(), ids=lambda cls: cls.__name__)
def test_member_name_equals_value(enum_cls: type[Enum]) -> None:
    for member in enum_cls:
        assert member.name == member.value, (
            f"{enum_cls.__name__}.{member.name} has value {member.value!r}, "
            "member name must equal value"
        )
