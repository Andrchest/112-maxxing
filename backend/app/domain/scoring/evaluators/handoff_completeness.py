"""`HANDOFF_COMPLETENESS` evaluator (HLD `10-domain-model.md` §10.14 #10,
`30-scenario-format.md` §30.7 example #10).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.domain.enums import RoleType
from app.domain.scoring import evidence
from app.domain.scoring.comparisons import is_present
from app.domain.scoring.context import ScoringContext
from app.domain.scoring.results import ScoreEvidence, ScoreResult
from app.domain.scoring.rules import ScoringRule


class HandoffCompletenessConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    required_field_paths: tuple[str, ...]
    points_per_field: float
    all_or_nothing: bool = False
    penalty_per_missing: float = 0.0
    treat_false_as_present: bool = True


def evaluate(
    rule: ScoringRule,
    config: HandoffCompletenessConfig,
    ctx: ScoringContext,
) -> ScoreResult:
    """How complete was the card that actually went to the DDS? (§10.14 #10)

    `HANDOFF_CREATED.card_values` only — the frozen copy that was handed over, not the live card
    (D3: "copied from `OperatorCard` by value"), and not anything the operator typed afterwards.
    SPEC §10 is explicit that "if the 112 operator omitted a critical fact, the omission
    propagates": a gap here is a gap the DDS really had to work with.

    A session with no `HANDOFF_CREATED` at all — a DDS-only run — has nothing to score as
    complete, so every required path counts as missing and the evidence points at the event that
    closed the session instead (D11).
    """
    handoff = ctx.handoff_event
    values = ctx.handoff_card_values
    present = [
        path
        for path in config.required_field_paths
        if is_present(values.get(path), treat_false_as_present=config.treat_false_as_present)
    ]
    missing = [path for path in config.required_field_paths if path not in present]

    if config.all_or_nothing:
        earned = rule.max_points if not missing else 0.0
    else:
        earned = config.points_per_field * len(present)
    points = earned + config.penalty_per_missing * len(missing)
    passed = not missing

    items: list[ScoreEvidence] = []
    if handoff is not None:
        items.append(
            evidence.from_snapshot(
                handoff,
                f"Передано полей: {len(present)} из {len(config.required_field_paths)}.",
            )
        )
        for path in missing:
            items.append(
                evidence.from_snapshot(handoff, f"Поле «{path}» в переданной карточке пустое.")
            )
    else:
        bound = evidence.bounding_event(ctx, RoleType.OPERATOR_112)
        items.append(evidence.from_event(bound, "Карточка в ДДС не передавалась."))
        for path in missing:
            items.append(evidence.from_event(bound, f"Поле «{path}» передано не было."))
    return evidence.result(rule, points=points, passed=passed, evidence=items)
