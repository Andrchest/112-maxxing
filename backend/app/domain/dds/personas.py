"""The AI personas of the ДДС phone — who answers when the ДДС calls a service (HLD
`80-telephony.md` §80.4.1, D24; I3 E6c).

A persona is reference data, not scenario data: `reference/personas/v1.yaml`, sha-pinned in
`reference/manifest.json` and named by a pack (`personas: v1` in `v046_24-r1`). Each entry says
which catalog category it plays (`applies: {code: "101"}` or `applies: {kind: DISTRICT}`), its
Russian title, its gender and its **logical** voice id (resolved by the model profile's
`tts.voice_map`, never a vendor speaker name here), the greeting, how long it takes to pick up,
the memo's words for each status, and whether it does not answer / is busy (REQ-5325).

**Resolution** (`resolve_persona`, pure): a scenario's per-service override
(`expected_response.responders[service_id].persona`, R42) wins; otherwise the most specific
`applies` wins — a persona naming the service's catalog `code` over one naming its `kind`. A
`CLAIMANT` call has no persona (the scenario's `CallerProfile` is the claimant, §80.4.1).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from enum import Enum
from types import MappingProxyType
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from app.domain.dds.response import ServiceResponseStatus

__all__ = [
    "DEFAULT_ANSWER_AFTER_MS",
    "OPERATOR_112_KIND",
    "Persona",
    "PersonaApplies",
    "PersonaCatalog",
    "PersonaGender",
    "resolve_persona",
]

DEFAULT_ANSWER_AFTER_MS = 4000
"""§80.4.1: a persona picks up `answer_after_ms` after the call started, 4 s unless it says."""

OPERATOR_112_KIND = "OPERATOR_112"
"""The one `applies.kind` that is not a catalog `ServiceKind`: the AI 112 operator (E6d)."""


class PersonaGender(str, Enum):
    MALE = "MALE"
    FEMALE = "FEMALE"


class PersonaApplies(BaseModel):
    """Which catalog entries a persona plays: exactly one of `code` or `kind`."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str | None = None
    kind: str | None = None

    def model_post_init(self, context: Any, /) -> None:
        if (self.code is None) == (self.kind is None):
            raise ValueError("a persona applies to exactly one of `code` or `kind`")


class Persona(BaseModel):
    """One entry of `reference/personas/<id>.yaml` (§80.4.1; `openapi.yaml`'s `PersonaView`)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    applies: PersonaApplies
    title_ru: str
    gender: PersonaGender
    voice_id: str
    """A LOGICAL voice id (`ru_male_adult_01`), resolved by the profile's `tts.voice_map`."""
    greeting_ru: str
    answer_after_ms: int = Field(default=DEFAULT_ANSWER_AFTER_MS, ge=0)
    vocabulary: Mapping[ServiceResponseStatus, str] = Field(default_factory=dict)
    """The memo's words for each status the head reports («Прибыли на место»)."""
    no_answer: bool = False
    """The phone rings out (REQ-5325 «не отвечают»)."""
    busy: bool = False
    """The line is busy (REQ-5325 «телефон не работает»)."""


class PersonaCatalog(BaseModel):
    """A versioned persona set (`personas/<catalog_id>.yaml`), entries in file order."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    catalog_id: str
    personas: tuple[Persona, ...]

    _by_id: Mapping[str, Persona] = PrivateAttr(default_factory=dict)

    def model_post_init(self, context: Any, /) -> None:
        by_id: dict[str, Persona] = {}
        for persona in self.personas:
            if persona.id in by_id:
                raise ValueError(f"persona {persona.id!r} is listed twice")
            by_id[persona.id] = persona
        self._by_id = MappingProxyType(by_id)

    def get(self, persona_id: str) -> Persona | None:
        return self._by_id.get(persona_id)

    def __contains__(self, persona_id: object) -> bool:
        return isinstance(persona_id, str) and persona_id in self._by_id

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(persona.id for persona in self.personas)

    def by_code(self, code: str) -> Persona | None:
        return _first(persona for persona in self.personas if persona.applies.code == code)

    def by_kind(self, kind: str) -> Persona | None:
        return _first(persona for persona in self.personas if persona.applies.kind == kind)


def _first(personas: Iterable[Persona]) -> Persona | None:
    return next(iter(personas), None)


def resolve_persona(
    catalog: PersonaCatalog | None,
    *,
    code: str | None,
    kind: str | None,
    override: str | None = None,
) -> Persona | None:
    """The persona that plays a service of this catalog `code` / `kind` (§80.4.1).

    `override` (a scenario's R42 key) wins when it names a persona of `catalog`; then the persona
    whose `applies.code` is the service's code; then the one whose `applies.kind` is its kind.
    `None` when the pack has no personas or none applies.
    """
    if catalog is None:
        return None
    if override is not None:
        chosen = catalog.get(override)
        if chosen is not None:
            return chosen
    if code is not None:
        chosen = catalog.by_code(code)
        if chosen is not None:
            return chosen
    if kind is not None:
        return catalog.by_kind(kind)
    return None
