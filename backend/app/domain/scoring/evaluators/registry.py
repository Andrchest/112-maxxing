"""`EVALUATOR_CONFIG_MODELS` and `parse_rule_config` (HLD `10-domain-model.md` §10.14).

Maps every `EvaluatorType` member to the Pydantic config model that validates the matching
`ScoringRule.config`. `Evaluator.evaluate(...)` itself (referenced by §10.14's "every evaluator
implements `evaluate(rule, ctx) -> ScoreResult`") is E15's slice; this module only owns config
validation, which scenario load-time validation (D4, §30.8 item 20) depends on.
"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel

from app.domain.enums import EvaluatorType
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
from app.domain.scoring.rules import ScoringRule

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


def parse_rule_config(rule: ScoringRule) -> BaseModel:
    """Validate `rule.config` against `rule.evaluator_type`'s config model.

    Raises `pydantic.ValidationError` (propagated, not wrapped) when the config does not match —
    scenario load-time validation (§30.8 item 20) relies on that exception surfacing as-is.
    """
    model = EVALUATOR_CONFIG_MODELS[rule.evaluator_type]
    return model.model_validate(rule.config)
