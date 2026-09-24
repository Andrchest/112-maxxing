"""The weight-proposal prompt — pure, no I/O (HLD 70 §70.3.7, I3 E9a; SPEC §2, D11).

`build_messages` is a function of exactly one thing: the cards' `CardMetadata`. That signature is
the whole input whitelist — no parameter could carry a `ScenarioVersion`, its `world_truth`, the
caller's knowledge or a disclosure rule, so nothing upstream can hand one over by mistake;
`backend/tests/invariants/test_weight_proposer_reads_metadata_only.py` pins the parameter list and
`CardMetadata`'s fields, not just today's call sites.

One call per lesson: the model sees every card and answers `{"proposals": [{"position",
"weight", "reason_ru"}]}` under a JSON schema. `parse_proposals` accepts an answer only when it
names every plan position exactly once with an integer weight in 1..10 and a non-empty Russian
reason; anything else raises `WeightProposalOutputError`, and the adapter answers the heuristic.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from pydantic import ValidationError

from app.application.ports.llm import ChatMessage, JsonSchemaSpec
from app.domain.lesson.weights import (
    MAX_PROPOSED_WEIGHT,
    MIN_PROPOSED_WEIGHT,
    CardMetadata,
    ProposedWeight,
)

__all__ = [
    "RESPONSE_FORMAT",
    "WeightProposalOutputError",
    "build_messages",
    "parse_proposals",
]

_REASON_MAX_CHARS = 400

RESPONSE_FORMAT = JsonSchemaSpec(
    name="lesson_weight_proposals",
    schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["proposals"],
        "properties": {
            "proposals": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["position", "weight", "reason_ru"],
                    "properties": {
                        "position": {"type": "integer", "minimum": 1},
                        "weight": {
                            "type": "integer",
                            "minimum": MIN_PROPOSED_WEIGHT,
                            "maximum": MAX_PROPOSED_WEIGHT,
                        },
                        "reason_ru": {"type": "string", "minLength": 1, "maxLength": 300},
                    },
                },
            }
        },
    },
)
"""The JSON schema the model's answer is constrained to (llama.cpp `response_format`)."""

_SYSTEM_PROMPT = (
    "Ты помогаешь инструктору центра обработки вызовов 112 оценить сложность учебных карточек "
    "занятия. Для каждой карточки предложи вес — целое число от 1 до 10 баллов (чем сложнее "
    "карточка, тем больше вес) — и короткое обоснование по-русски, одно предложение.\n\n"
    "Правила:\n"
    "- Опирайся только на перечисленные свойства карточки: название, сложность по шкале 1–5, "
    "тип карточки, число служб, таймеры, особые варианты и источник. Не придумывай фактов о "
    "происшествии.\n"
    "- Сложность 1–5 — главный ориентир; служб больше — вес выше; разговор с заявителем, отказ "
    "службы по компетенции и ошибка в карточке для проверки усложняют задание.\n"
    '- Ответь строго JSON-объектом {"proposals": [{"position", "weight", "reason_ru"}]}, '
    "по одному элементу на каждую карточку, с теми же номерами position."
)

_CARD_SOURCE_RU = {
    "GENERATED_CARD": "готовая карточка (без разговора с заявителем)",
    "CALLER_VOICE": "разговор с заявителем и заполнение карточки",
}
_ROLE_RU = {"OPERATOR_112": "оператор 112", "DDS": "ДДС", "EDDS": "ЕДДС"}


def _seconds(ms: int) -> str:
    return f"{ms // 1000} с"


def _card_lines(card: CardMetadata) -> list[str]:
    lines = [
        f"Карточка {card.position}: «{card.title}»",
        f"  сложность: {card.difficulty} из 5",
        f"  тип карточки: {_CARD_SOURCE_RU.get(card.card_source.value, card.card_source.value)}",
        "  рабочие места: " + ", ".join(_ROLE_RU.get(r.value, r.value) for r in card.role_chain),
        f"  служб к оповещению: {card.required_service_count}"
        + (
            f" (и ещё {card.optional_service_count} по желанию)"
            if card.optional_service_count
            else ""
        ),
        f"  таймеры: принять за {_seconds(card.accept_within_ms)}, заполнить за "
        f"{_seconds(card.fill_within_ms)}, «не завершено» через "
        f"{_seconds(card.not_completed_after_ms)}",
    ]
    specials = []
    if card.has_competence_decline:
        specials.append("служба отказывает по компетенции")
    if card.has_card_check:
        specials.append("в карточке есть ошибка для проверки ДДС")
    lines.append("  особые варианты: " + (", ".join(specials) if specials else "нет"))
    if card.provenance_source is not None:
        lines.append(
            f"  источник: {card.provenance_source}, билет {card.provenance_ticket}, "
            f"вызов {card.provenance_call}"
        )
    return lines


def build_messages(cards: Sequence[CardMetadata]) -> list[ChatMessage]:
    """`[system, user]` — the whole input a weight-proposal LLM call may see."""
    body: list[str] = [f"Карточек в занятии: {len(cards)}."]
    for card in cards:
        body.extend(_card_lines(card))
    return [
        ChatMessage(role="system", content=_SYSTEM_PROMPT),
        ChatMessage(role="user", content="\n".join(body)),
    ]


class WeightProposalOutputError(ValueError):
    """The model's answer is not a complete, valid proposal list."""


def parse_proposals(text: str, positions: Sequence[int]) -> tuple[ProposedWeight, ...]:
    """The answer's proposals in `positions` order, or `WeightProposalOutputError`."""
    try:
        document: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        raise WeightProposalOutputError(f"the answer is not JSON: {exc.msg}") from exc
    items = document.get("proposals") if isinstance(document, dict) else None
    if not isinstance(items, list):
        raise WeightProposalOutputError("the answer has no `proposals` list")
    by_position: dict[int, ProposedWeight] = {}
    for item in items:
        if not isinstance(item, dict) or isinstance(item.get("weight"), bool):
            raise WeightProposalOutputError(f"a proposal is malformed: {item!r}")
        reason = str(item.get("reason_ru", "")).strip()[:_REASON_MAX_CHARS]
        try:
            proposal = ProposedWeight(
                position=item.get("position"), weight=item.get("weight"), reason_ru=reason
            )
        except ValidationError as exc:
            raise WeightProposalOutputError(f"a proposal is invalid: {item!r}") from exc
        if not isinstance(item.get("weight"), int):
            raise WeightProposalOutputError(f"a weight is not an integer: {item!r}")
        if proposal.position in by_position:
            raise WeightProposalOutputError(f"position {proposal.position} is proposed twice")
        by_position[proposal.position] = proposal
    if sorted(by_position) != sorted(positions):
        raise WeightProposalOutputError(
            f"the answer covers positions {sorted(by_position)}, the plan has {sorted(positions)}"
        )
    return tuple(by_position[position] for position in positions)
