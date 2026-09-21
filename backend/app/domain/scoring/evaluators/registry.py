"""`EVALUATOR_CONFIG_MODELS` and `parse_rule_config` (HLD `10-domain-model.md` §10.14).

Maps every `EvaluatorType` member to the Pydantic config model that validates the matching
`ScoringRule.config`, and every `EvaluatorType` member to the `evaluate(...)` that scores it
(§10.14's "every evaluator implements `evaluate(rule, ctx) -> ScoreResult`"). Both maps carry the
same totality assert, so a new `EvaluatorType` cannot be half-wired.

`parse_rule_config` propagates `pydantic.ValidationError` unwrapped because scenario load-time
validation (D4, §30.8 item 20) depends on that exception surfacing as-is.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol

from pydantic import BaseModel

from app.domain.enums import EvaluatorType
from app.domain.scoring.context import ScoringContext
from app.domain.scoring.evaluators import card_contradiction as _card_contradiction
from app.domain.scoring.evaluators import card_field_correct as _card_field_correct
from app.domain.scoring.evaluators import card_field_present as _card_field_present
from app.domain.scoring.evaluators import deadline as _deadline
from app.domain.scoring.evaluators import fact_obtained as _fact_obtained
from app.domain.scoring.evaluators import handoff_completeness as _handoff_completeness
from app.domain.scoring.evaluators import required_status_update as _required_status_update
from app.domain.scoring.evaluators import resource_selection as _resource_selection
from app.domain.scoring.evaluators import service_selection as _service_selection
from app.domain.scoring.evaluators import workflow_action as _workflow_action
from app.domain.scoring.evaluators.card_contradiction import CardContradictionConfig
from app.domain.scoring.evaluators.card_field_correct import CardFieldCorrectConfig
from app.domain.scoring.evaluators.card_field_present import CardFieldPresentConfig
from app.domain.scoring.evaluators.deadline import DeadlineConfig
from app.domain.scoring.evaluators.fact_obtained import FactObtainedConfig
from app.domain.scoring.evaluators.handoff_completeness import HandoffCompletenessConfig
from app.domain.scoring.evaluators.required_status_update import RequiredStatusUpdateConfig
from app.domain.scoring.evaluators.resource_selection import ResourceSelectionConfig
from app.domain.scoring.evaluators.service_selection import ServiceSelectionConfig
from app.domain.scoring.evaluators.workflow_action import WorkflowActionConfig
from app.domain.scoring.results import ScoreResult
from app.domain.scoring.rules import ScoringRule


class Evaluator(Protocol):
    """What every `evaluate(...)` is (§10.14: "every evaluator implements `evaluate(...)`").

    `config` is the already-parsed config model for `rule.evaluator_type`, so an evaluator never
    re-reads `rule.config` and never has to decide what to do with a shape it does not know:
    `parse_rule_config` raised long before, at scenario import time (§30.8 item 20).
    """

    def __call__(self, rule: ScoringRule, config: Any, ctx: ScoringContext) -> ScoreResult: ...


EVALUATOR_CONFIG_MODELS: Mapping[EvaluatorType, type[BaseModel]] = {
    EvaluatorType.FACT_OBTAINED: FactObtainedConfig,
    EvaluatorType.CARD_FIELD_CORRECT: CardFieldCorrectConfig,
    EvaluatorType.CARD_FIELD_PRESENT: CardFieldPresentConfig,
    EvaluatorType.CARD_CONTRADICTION: CardContradictionConfig,
    EvaluatorType.SERVICE_SELECTION: ServiceSelectionConfig,
    EvaluatorType.DEADLINE: DeadlineConfig,
    EvaluatorType.WORKFLOW_ACTION: WorkflowActionConfig,
    EvaluatorType.RESOURCE_SELECTION: ResourceSelectionConfig,
    EvaluatorType.REQUIRED_STATUS_UPDATE: RequiredStatusUpdateConfig,
    EvaluatorType.HANDOFF_COMPLETENESS: HandoffCompletenessConfig,
}

assert frozenset(EVALUATOR_CONFIG_MODELS) == frozenset(EvaluatorType)

EVALUATORS: Mapping[EvaluatorType, Evaluator] = {
    EvaluatorType.FACT_OBTAINED: _fact_obtained.evaluate,
    EvaluatorType.CARD_FIELD_CORRECT: _card_field_correct.evaluate,
    EvaluatorType.CARD_FIELD_PRESENT: _card_field_present.evaluate,
    EvaluatorType.CARD_CONTRADICTION: _card_contradiction.evaluate,
    EvaluatorType.SERVICE_SELECTION: _service_selection.evaluate,
    EvaluatorType.DEADLINE: _deadline.evaluate,
    EvaluatorType.WORKFLOW_ACTION: _workflow_action.evaluate,
    EvaluatorType.RESOURCE_SELECTION: _resource_selection.evaluate,
    EvaluatorType.REQUIRED_STATUS_UPDATE: _required_status_update.evaluate,
    EvaluatorType.HANDOFF_COMPLETENESS: _handoff_completeness.evaluate,
}
"""`EvaluatorType -> evaluate` (§10.14). Total by the same assert the config map carries: an
`EvaluatorType` added without an evaluator fails at import, not at the end of a training session.
"""

assert frozenset(EVALUATORS) == frozenset(EvaluatorType)


def parse_rule_config(rule: ScoringRule) -> BaseModel:
    """Validate `rule.config` against `rule.evaluator_type`'s config model.

    Raises `pydantic.ValidationError` (propagated, not wrapped) when the config does not match —
    scenario load-time validation (§30.8 item 20) relies on that exception surfacing as-is.
    """
    model = EVALUATOR_CONFIG_MODELS[rule.evaluator_type]
    return model.model_validate(rule.config)
