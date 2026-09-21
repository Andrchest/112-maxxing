"""Operator 112 stage use cases (E7, SPEC §7, §9, §10; §10.6, §10.8, §10.9; D3, D5, D8, D12).

Nine operations of `openapi.yaml`'s `operator` tag, and the one simulation-driven call flow behind
them:

| module | operation | `x-action` |
|:--|:--|:--|
| `answer_call` | `answerCall` | `answer` |
| `end_call` | `endCall` | `end_call` |
| `get_card` | `getOperatorCard` | — |
| `set_card_field` | `setCardField` | `edit_card` |
| `list_card_revisions` | `listCardRevisions` | — |
| `select_service` | `selectRecipientService` | `select_services` |
| `deselect_service` | `deselectRecipientService` | `select_services` |
| `begin_handoff_preparation` | `beginHandoffPreparation` | `open_handoff_preparation` |
| `back_to_interview` | `backToInterview` | `back_to_interview` |
| `call_flow` | — (`SIMULATION` fires `ring` / `begin_interview`) | — |

Each module's docstring states that operation's `x-emits` and how it meets it; the tests read the
`x-emits` list straight out of `openapi.yaml` rather than from a copy of it.

Every *command* runs through the single pipeline of `command_context.OperatorCommandGate` — one
Unit of Work, one row lock, D8's two gates, one commit. `views` holds the materialized views they
answer with and the pure fold that gives call state without a table.

Two operations of the tag are **not** here: `createHandoff` and `completeOperatorStage` are
TODO(E9), together with the session-completing use case that owns `SESSION_COMPLETED.total_events`
and the `continueToNextStage` role transition that only a completed 112 stage can reach.

INV 4 (SPEC §42 test 4) is why the card writers are exactly three modules — `set_card_field`,
`select_service`, `deselect_service` — and why none of them can see a transcript:
`backend/tests/invariants/test_inv_04_asr_never_mutates_card.py` scans for both halves.
"""

from __future__ import annotations

from app.application.operator.answer_call import AnswerCall
from app.application.operator.back_to_interview import BackToInterview
from app.application.operator.begin_handoff_preparation import BeginHandoffPreparation
from app.application.operator.call_flow import AdvanceCallFlow
from app.application.operator.command_context import (
    ActionNotAvailableError,
    OperatorCommandContext,
    OperatorCommandGate,
    SessionNotActiveError,
)
from app.application.operator.deselect_service import DeselectRecipientService
from app.application.operator.end_call import EndCall
from app.application.operator.get_card import GetOperatorCard
from app.application.operator.list_card_revisions import ListCardRevisions
from app.application.operator.select_service import SelectRecipientService
from app.application.operator.set_card_field import (
    CardFieldNotSettableError,
    CardFieldUnknownError,
    CardValueTypeMismatchError,
    SetCardField,
    SetCardFieldResult,
)
from app.application.operator.views import (
    ActionView,
    CallPhase,
    CallStateView,
    CardRevisionView,
    OperatorCardView,
    OperatorStageView,
    ServiceSelectionView,
    project_call_state,
)

__all__ = [
    "ActionNotAvailableError",
    "ActionView",
    "AdvanceCallFlow",
    "AnswerCall",
    "BackToInterview",
    "BeginHandoffPreparation",
    "CallPhase",
    "CallStateView",
    "CardFieldNotSettableError",
    "CardFieldUnknownError",
    "CardRevisionView",
    "CardValueTypeMismatchError",
    "DeselectRecipientService",
    "EndCall",
    "GetOperatorCard",
    "ListCardRevisions",
    "OperatorCardView",
    "OperatorCommandContext",
    "OperatorCommandGate",
    "OperatorStageView",
    "SelectRecipientService",
    "ServiceSelectionView",
    "SessionNotActiveError",
    "SetCardField",
    "SetCardFieldResult",
    "project_call_state",
]
