"""`ResponseValidator` — the deterministic SPEC §24 gate between the model and the trainee's ear
(HLD `50-voice-pipeline.md` §3.6, §7, D10).

Every check here is code. None of it asks a model anything, none of it touches a clock, a database
or a network, and `validate()` is synchronous on purpose: a validator that could await is a
validator that could be skipped under load, and SPEC §16's "forbidden levers" list names exactly
that.

`validate()` returns **all** failures it found, not the first one. The §43 adversarial suite asserts
on the set of codes a hostile answer produced, and a first-only validator would make "the leak was
caught" indistinguishable from "something else was caught first".

The validator is the one component that legitimately *sees* the values the caller may not say
(`forbidden_values`, §7.6): it is code, and the prompt builder — which is what the model sees — has
no parameter those values could arrive through (D3, R3).

HLD gaps resolved here, in the reading closest to SPEC (all listed in this task's report):

* **§7.1's token length** is measured with "the same tokenizer the LLM uses, obtained from
  `LLMClient.count_tokens`". The `LLMClient` port (§2.5) has no `count_tokens` member, and adding
  one would make a deterministic gate test depend on a real tokenizer. The character guard §7.1
  applies *first* is applied, then the same deterministic `ceil(len/3)` estimate the interpreter
  and the prompt builder budget with. E18 can swap a real tokenizer behind `estimate_tokens`.
* **§7.3's forbidden identifier set** is specified as "every `fact_id` in the `ScenarioVersion`",
  but §3.6 fixes `validate()`'s parameter list and no `ScenarioVersion` is in it. The stricter
  reading is implemented: *any* identifier-shaped substring (one containing `_` or `.` between
  word characters) is forbidden, whatever scenario it came from, plus the fixed enum-literal and
  literal-string sets §7.3 lists. That is a superset of the documented rule and needs no extra
  parameter.
* **§7.4's Latin-run rule** predates enum-typed caller values: the demo scenario releases
  `incident.type = FIRE`, so a caller who repeats a value the gate released would be rejected for
  speaking English. A Latin token that is in this turn's permitted set is therefore exempt.
* **§7.5's `SMALL_COUNT_ALLOWLIST`** is specified as applying "when the token is a bare count
  adjacent to a noun", which is not decidable without a part-of-speech model. The allowlist is
  applied to the value alone; the §43 run empties it, which is where the difference matters.
* **`caller_max_sentences`** has no value anywhere in §7.1 (it names only length and schema). The
  reading closest to SPEC §23 ("отвечай … кратко", "ОДНОЙ короткой репликой") is a small cap; the
  default is 3 and it is a setting, not a literal.
"""

from __future__ import annotations

import enum
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Annotated

from pydantic import BaseModel, ConfigDict, ValidationError

from app.application.dialogue.grammar import SpokenText
from app.application.dialogue.meta_lexicon import (
    LATIN_ALLOWLIST,
    META_LEXICON_EN,
    META_LEXICON_RU,
    META_MIN_LATIN_RUN,
)
from app.application.dialogue.text_normalization import (
    IDENTIFIER_PATTERN,
    NormalizedText,
    Token,
    normalize_text,
)
from app.config.settings import Settings
from app.domain.enums import (
    DDSStageState,
    DisclosurePolicy,
    GateOutcome,
    GateReason,
    KnowledgeState,
    Operator112StageState,
    SessionState,
    SpeechAct,
)
from app.domain.events.types import EventType
from app.domain.facts.gate import AllowedFactsPackage

__all__ = [
    "ADDRESS_PATTERN",
    "CALLER_UTTERANCE_FIELD",
    "EMERGENCY_NUMBERS",
    "CallerUtterance",
    "ResponseValidator",
    "ValidationFailure",
    "ValidationFailureCode",
    "ValidationVerdict",
    "ValidatorConfig",
    "estimate_tokens",
    "validator_config_from_settings",
]

_CHARS_PER_TOKEN = 3


def estimate_tokens(text: str) -> int:
    """`ceil(len(text) / 3)` — the one deterministic token estimate this epic budgets with.

    Behind a single function so E18 can put a real tokenizer here (§5.3, §7.1) without touching a
    call site. See the module docstring's first HLD gap.
    """
    if not text:
        return 0
    return -(-len(text) // _CHARS_PER_TOKEN)


class ValidationFailureCode(enum.StrEnum):
    """§7's ten codes, verbatim and in the document's order."""

    TOO_LONG = "TOO_LONG"
    SCHEMA_INVALID = "SCHEMA_INVALID"
    EXTRA_FIELD = "EXTRA_FIELD"
    FORBIDDEN_IDENTIFIER = "FORBIDDEN_IDENTIFIER"
    META_LANGUAGE = "META_LANGUAGE"
    NEW_NUMBER = "NEW_NUMBER"
    NEW_ADDRESS_TOKEN = "NEW_ADDRESS_TOKEN"
    NEW_NAME = "NEW_NAME"
    WORLD_VALUE_LEAK = "WORLD_VALUE_LEAK"
    EMPTY = "EMPTY"


#: The one field of the caller's schema-constrained output (§5.2's `CALLER_JSON_SCHEMA`).
CALLER_UTTERANCE_FIELD = "utterance"


#: §7.1's EMPTY rule, widened in E19-C2: an utterance that carries no letter at all is empty
#: *speech*, whatever characters it contains. E19-C measured the Qwen3.5 family filling the
#: grammar's `utterance` string with a bare `}` (13-27 of 46 dialogue turns, depending on the
#: model) and this validator passing it through to the trainee's ear, because `"}".strip()` is
#: truthy. Latin is accepted as well as Cyrillic here even though §7.4 dislikes Latin runs: that
#: is `META_LANGUAGE`/§7.4's job, and `EMPTY` must not quietly become a second language check.
_LETTER_RE = re.compile(r"[^\W\d_]", re.UNICODE)


class CallerUtterance(BaseModel):
    """§7.1's Pydantic model: `{"utterance": str}` and nothing else (`extra="forbid"`).

    `SpokenText` is a grammar-only marker (`app.application.dialogue.grammar`): it makes the
    generated GBNF require at least one Cyrillic letter inside the string, so the model cannot
    *produce* `{"utterance":"}"}` in the first place. pydantic ignores it for validation and for
    `model_json_schema()`, so `CALLER_JSON_SCHEMA` — the non-grammar fallback — is unchanged.
    The `EMPTY` check below is the second boundary: the grammar stops it being generated, the
    validator stops it being spoken, and neither relies on the other (SPEC §44).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    utterance: Annotated[str, SpokenText()]


@dataclass(frozen=True, slots=True)
class ValidationFailure:
    """One reason a candidate answer was rejected (§7)."""

    code: ValidationFailureCode
    detail: str = ""
    """A short, value-free explanation for the instructor log. It never names the offending
    value: the repair prompt is built from `code` alone (§7.7) and a detail that quoted the value
    would end up beside it in an event payload an instructor reads."""


@dataclass(frozen=True, slots=True)
class ValidationVerdict:
    """§3.6's output: `{ok, failures, normalized_text}`."""

    ok: bool
    failures: tuple[ValidationFailure, ...] = ()
    normalized_text: str = ""
    utterance: str = ""
    """The parsed `utterance` field, stripped — empty when the output did not parse."""

    @property
    def codes(self) -> tuple[ValidationFailureCode, ...]:
        """Every failure code, in the order the checks ran."""
        return tuple(failure.code for failure in self.failures)


@dataclass(frozen=True, slots=True)
class ValidatorConfig:
    """Every limit the validator applies, from settings — never a literal in a check (§7)."""

    max_chars: int = 400
    max_sentences: int = 3
    max_response_tokens: int = 80
    entity_lookback_turns: int = 6
    small_count_allowlist: frozenset[str] = field(
        default_factory=lambda: frozenset({"0", "1", "2", "3"})
    )
    """§7.5's `validator.small_count_allowlist`; the §43 adversarial run empties it."""


def validator_config_from_settings(settings: Settings) -> ValidatorConfig:
    """`SIM_CALLER_MAX_CHARS` / `SIM_CALLER_MAX_SENTENCES` / `SIM_LLM_GENERATOR_MAX_TOKENS`."""
    return ValidatorConfig(
        max_chars=settings.caller_max_chars,
        max_sentences=settings.caller_max_sentences,
        max_response_tokens=settings.llm_generator_max_tokens,
    )


#: §7.5's address keyword pattern, verbatim.
ADDRESS_PATTERN = re.compile(
    r"^(д|дом|кв|квартира|корп|корпус|стр|строение|подъезд|этаж|ул|улица|пр|проспект|пер|"
    r"переулок|ш|шоссе|б-р|бульвар|наб|набережная|пл|площадь)$"
)

#: §7.5: "the fixed set `{"112", "01", "02", "03", "04"}`" every caller may say.
EMERGENCY_NUMBERS: frozenset[str] = frozenset({"112", "01", "02", "03", "04"})

#: §7.5: sentence-initial-only words and interjections a capital letter does not make a name.
RU_COMMON_CAPITALIZED: frozenset[str] = frozenset(
    {
        "алло",
        "ало",
        "да",
        "нет",
        "ой",
        "ах",
        "простите",
        "извините",
        "пожалуйста",
        "здравствуйте",
        "спасибо",
        "хорошо",
        "там",
        "тут",
        "это",
        "я",
        "мы",
        "он",
        "она",
        "они",
        "вы",
        "ты",
        "у",
        "в",
        "на",
        "и",
        "а",
        "но",
        "что",
        "кто",
        "как",
        "когда",
        "где",
        "тип",
        "адрес",
        "телефон",
        "скорее",
        "быстрее",
        "помогите",
        "горит",
        "дым",
        "пожар",
    }
)

#: §7.5's given-name membership half; the suffix half is `_NAME_SUFFIXES`.
RU_GIVEN_NAMES: frozenset[str] = frozenset(
    {
        "иван",
        "ирина",
        "петр",
        "петрович",
        "петровна",
        "анна",
        "мария",
        "сергей",
        "алексей",
        "ольга",
        "елена",
        "николай",
        "андрей",
        "татьяна",
        "дмитрий",
        "светлана",
        "владимир",
        "наталья",
    }
)
_NAME_SUFFIXES: tuple[str, ...] = ("ов", "ев", "ин", "ский", "ко", "ич")

#: §7.3's enum-literal half. Every member of the enums §7.3 names, upper-cased.
_ENUM_LITERALS: frozenset[str] = frozenset(
    member.value.lower()
    for members in (
        KnowledgeState,
        DisclosurePolicy,
        GateOutcome,
        GateReason,
        SpeechAct,
        SessionState,
        Operator112StageState,
        DDSStageState,
    )
    for member in members
) | frozenset(event_type.value.lower() for event_type in EventType)

#: §7.3's literal-string half, verbatim.
_FORBIDDEN_LITERALS: frozenset[str] = frozenset(
    {
        "allowed_facts",
        "already_revealed",
        "worldtruth",
        "callerbelief",
        "world_value",
        "caller_value",
        "fact_id",
        "semantic_confidence",
    }
)

_SENTENCE_SPLIT = re.compile(r"[.!?…]+")


def _sentence_count(text: str) -> int:
    return len([part for part in _SENTENCE_SPLIT.split(text) if part.strip()])


def _subsequence(haystack: Sequence[str], needle: Sequence[str]) -> bool:
    """True when `needle` appears as a **contiguous** run inside `haystack` (§7.6)."""
    if not needle or len(needle) > len(haystack):
        return False
    first = needle[0]
    for start in range(len(haystack) - len(needle) + 1):
        if haystack[start] != first:
            continue
        if tuple(haystack[start : start + len(needle)]) == tuple(needle):
            return True
    return False


def _phrase_present(tokens: Sequence[str], phrase: str) -> bool:
    parts = normalize_text(phrase).texts
    if len(parts) == 1:
        return parts[0] in tokens
    return _subsequence(tokens, parts)


@dataclass(frozen=True, slots=True)
class _Permitted:
    """§7.5's permitted value set, already run through §7.2."""

    tokens: frozenset[str]
    numbers: frozenset[str]


class ResponseValidator:
    """§7's algorithm, in order. Pure, synchronous, and it returns every failure it found."""

    def __init__(self, config: ValidatorConfig | None = None) -> None:
        self._config = config or ValidatorConfig()

    @property
    def config(self) -> ValidatorConfig:
        """The limits this validator applies."""
        return self._config

    def validate(
        self,
        raw: str,
        *,
        package: AllowedFactsPackage,
        revealed_values: Sequence[str],
        operator_utterances: Sequence[str],
        persona_whitelist: Sequence[str],
        forbidden_values: Sequence[str],
    ) -> ValidationVerdict:
        """Check one raw model output against §7.1–§7.6 and report every failure (§3.6)."""
        failures: list[ValidationFailure] = []
        utterance = self._parse(raw, failures)
        if utterance is None:
            return ValidationVerdict(ok=False, failures=tuple(failures))

        stripped = utterance.strip()
        if not _LETTER_RE.search(stripped):
            failures.append(
                ValidationFailure(
                    ValidationFailureCode.EMPTY,
                    "the utterance contains no letter — there is nothing to say",
                )
            )
            return ValidationVerdict(ok=False, failures=tuple(failures))

        self._check_length(stripped, failures)
        normalized = normalize_text(stripped)
        permitted = self._permitted(
            package, revealed_values, operator_utterances, persona_whitelist
        )

        self._check_identifiers(normalized, failures)
        self._check_meta_language(normalized, permitted, failures)
        self._check_entities(normalized, permitted, failures)
        self._check_world_values(normalized, forbidden_values, failures)

        return ValidationVerdict(
            ok=not failures,
            failures=tuple(failures),
            normalized_text=normalized.normalized,
            utterance=stripped,
        )

    # -- §7.1 ---------------------------------------------------------------------------------

    def _parse(self, raw: str, failures: list[ValidationFailure]) -> str | None:
        try:
            document = json.loads(raw)
        except (TypeError, ValueError):
            failures.append(
                ValidationFailure(ValidationFailureCode.SCHEMA_INVALID, "the output is not JSON")
            )
            return None
        if not isinstance(document, dict):
            failures.append(
                ValidationFailure(
                    ValidationFailureCode.SCHEMA_INVALID, "the output is not a JSON object"
                )
            )
            return None
        extra = sorted(key for key in document if key != CALLER_UTTERANCE_FIELD)
        if extra:
            failures.append(
                ValidationFailure(
                    ValidationFailureCode.EXTRA_FIELD,
                    f"unexpected field(s): {', '.join(extra)}",
                )
            )
        try:
            parsed = CallerUtterance.model_validate(
                {CALLER_UTTERANCE_FIELD: document.get(CALLER_UTTERANCE_FIELD)}
            )
        except ValidationError:
            failures.append(
                ValidationFailure(
                    ValidationFailureCode.SCHEMA_INVALID,
                    f"{CALLER_UTTERANCE_FIELD!r} is missing or is not a string",
                )
            )
            return None
        return parsed.utterance

    def _check_length(self, utterance: str, failures: list[ValidationFailure]) -> None:
        config = self._config
        if len(utterance) > config.max_chars:
            failures.append(
                ValidationFailure(
                    ValidationFailureCode.TOO_LONG,
                    f"{len(utterance)} characters exceeds {config.max_chars}",
                )
            )
            return
        tokens = estimate_tokens(utterance)
        if tokens > config.max_response_tokens:
            failures.append(
                ValidationFailure(
                    ValidationFailureCode.TOO_LONG,
                    f"about {tokens} tokens exceeds {config.max_response_tokens}",
                )
            )
            return
        sentences = _sentence_count(utterance)
        if sentences > config.max_sentences:
            failures.append(
                ValidationFailure(
                    ValidationFailureCode.TOO_LONG,
                    f"{sentences} sentences exceeds {config.max_sentences}",
                )
            )

    # -- §7.5's permitted set ------------------------------------------------------------------

    def _permitted(
        self,
        package: AllowedFactsPackage,
        revealed_values: Sequence[str],
        operator_utterances: Sequence[str],
        persona_whitelist: Sequence[str],
    ) -> _Permitted:
        sources: list[str] = [fact.value_ru for fact in package.allowed if fact.value is not None]
        sources.extend(revealed_values)
        sources.extend(operator_utterances[-self._config.entity_lookback_turns :])
        sources.extend(persona_whitelist)
        sources.extend(sorted(EMERGENCY_NUMBERS))
        tokens: set[str] = set()
        numbers: set[str] = set(EMERGENCY_NUMBERS)
        for source in sources:
            normalized = normalize_text(source)
            tokens.update(normalized.texts)
            numbers.update(normalized.number_values)
        return _Permitted(tokens=frozenset(tokens), numbers=frozenset(numbers))

    # -- §7.3 ---------------------------------------------------------------------------------

    def _check_identifiers(
        self, normalized: NormalizedText, failures: list[ValidationFailure]
    ) -> None:
        lowered = normalized.normalized.lower()
        if IDENTIFIER_PATTERN.search(lowered):
            failures.append(
                ValidationFailure(
                    ValidationFailureCode.FORBIDDEN_IDENTIFIER,
                    "an identifier-shaped token (dotted or underscored) is not ordinary speech",
                )
            )
            return
        for token in normalized.tokens:
            if token.text in _ENUM_LITERALS or token.text in _FORBIDDEN_LITERALS:
                failures.append(
                    ValidationFailure(
                        ValidationFailureCode.FORBIDDEN_IDENTIFIER,
                        "a domain enum literal or reserved word reached the utterance",
                    )
                )
                return

    # -- §7.4 ---------------------------------------------------------------------------------

    def _check_meta_language(
        self,
        normalized: NormalizedText,
        permitted: _Permitted,
        failures: list[ValidationFailure],
    ) -> None:
        texts = normalized.texts
        for phrase in (*META_LEXICON_RU, *META_LEXICON_EN):
            if _phrase_present(texts, phrase):
                failures.append(
                    ValidationFailure(
                        ValidationFailureCode.META_LANGUAGE,
                        "the utterance talks about the system rather than the incident",
                    )
                )
                return
        for token in normalized.tokens:
            if not token.is_latin or len(token.text) < META_MIN_LATIN_RUN:
                continue
            if token.text in LATIN_ALLOWLIST or token.text in permitted.tokens:
                continue
            failures.append(
                ValidationFailure(
                    ValidationFailureCode.META_LANGUAGE,
                    "a Latin-script run a Russian caller has no reason to say",
                )
            )
            return

    # -- §7.5 ---------------------------------------------------------------------------------

    def _check_entities(
        self,
        normalized: NormalizedText,
        permitted: _Permitted,
        failures: list[ValidationFailure],
    ) -> None:
        self._check_numbers(normalized, permitted, failures)
        self._check_address(normalized, permitted, failures)
        self._check_names(normalized, permitted, failures)

    def _check_numbers(
        self,
        normalized: NormalizedText,
        permitted: _Permitted,
        failures: list[ValidationFailure],
    ) -> None:
        allowlist = self._config.small_count_allowlist
        for run in normalized.numbers:
            if run.value in permitted.numbers or run.value in allowlist:
                continue
            failures.append(
                ValidationFailure(
                    ValidationFailureCode.NEW_NUMBER,
                    "a number nobody told the caller appeared in the answer",
                )
            )
            return

    def _check_address(
        self,
        normalized: NormalizedText,
        permitted: _Permitted,
        failures: list[ValidationFailure],
    ) -> None:
        tokens = normalized.tokens
        for index, token in enumerate(tokens):
            if not ADDRESS_PATTERN.match(token.text):
                continue
            for candidate in _neighbours(tokens, index):
                if _is_address_payload(candidate) and not _permits(candidate, permitted):
                    failures.append(
                        ValidationFailure(
                            ValidationFailureCode.NEW_ADDRESS_TOKEN,
                            "a part of an address nobody told the caller appeared in the answer",
                        )
                    )
                    return

    def _check_names(
        self,
        normalized: NormalizedText,
        permitted: _Permitted,
        failures: list[ValidationFailure],
    ) -> None:
        tokens = normalized.tokens
        for index, token in enumerate(tokens):
            if not _looks_like_a_name(token, tokens, index):
                continue
            if token.text in permitted.tokens:
                continue
            failures.append(
                ValidationFailure(
                    ValidationFailureCode.NEW_NAME,
                    "a name nobody told the caller appeared in the answer",
                )
            )
            return

    # -- §7.6 ---------------------------------------------------------------------------------

    def _check_world_values(
        self,
        normalized: NormalizedText,
        forbidden_values: Sequence[str],
        failures: list[ValidationFailure],
    ) -> None:
        haystack = normalized.texts
        for value in forbidden_values:
            needle = normalize_text(value).texts
            if not needle:
                continue
            if _subsequence(haystack, needle):
                failures.append(
                    ValidationFailure(
                        ValidationFailureCode.WORLD_VALUE_LEAK,
                        "the answer contains a scenario value outside this turn's package",
                    )
                )
                return


def _neighbours(tokens: Sequence[Token], index: int) -> list[Token]:
    found: list[Token] = []
    if index > 0:
        found.append(tokens[index - 1])
    if index + 1 < len(tokens):
        found.append(tokens[index + 1])
    return found


def _is_address_payload(candidate: Token) -> bool:
    """§7.5's "attached value": a digit run beside the keyword, or a capitalised token beside it.

    HLD gap (see the module docstring's list): §7.5 also calls the **keyword** itself address-like
    and requires it to be in `permitted`, which would reject «дом 27» whenever the gate released
    only `27` — «дом» is ordinary Russian and is not an incident fact. SPEC §24 item 5 forbids
    "new numeric/address/name **entities**", and the entity is the value, so only the attached
    value is checked here.
    """
    if candidate.number is not None:
        return True
    first = candidate.original[:1]
    return bool(first) and first.isupper() and first.isalpha()


def _permits(candidate: Token, permitted: _Permitted) -> bool:
    if candidate.number is not None:
        return candidate.number in permitted.numbers
    return candidate.text in permitted.tokens


def _looks_like_a_name(token: Token, tokens: Sequence[Token], index: int) -> bool:
    """§7.5's capitalised-name rule, including its sentence-initial special case."""
    first = token.original[:1]
    if not first or not first.isupper() or not _is_cyrillic(first):
        return False
    if len(token.text) < 3:
        return False
    if token.text in RU_COMMON_CAPITALIZED:
        return False
    if ADDRESS_PATTERN.match(token.text):
        return False
    if any(ADDRESS_PATTERN.match(neighbour.text) for neighbour in _neighbours(tokens, index)):
        # An address keyword's neighbour is §7.5's `NEW_ADDRESS_TOKEN` case, not `NEW_NAME`.
        return False
    if not token.sentence_start:
        return True
    return token.text in RU_GIVEN_NAMES or token.text.endswith(_NAME_SUFFIXES)


def _is_cyrillic(char: str) -> bool:
    return "Ѐ" <= char <= "ӿ"
