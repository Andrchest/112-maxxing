"""`CardIssueKind` — what the ДДС says is wrong with the received card (I3 E5b, HLD 70 §70.7;
«Отметить ошибку в карточке», `dds_card_check: ON`, C1).

The ДДС flags against the frozen `HandoffSnapshot` it received and nothing else (INV 3): a field is
missing, a value is wrong, two values contradict each other, or something else the comment says.
"""

from __future__ import annotations

from enum import Enum

__all__ = ["CardIssueKind"]


class CardIssueKind(str, Enum):
    """`DDS_CARD_ISSUE_FLAGGED.issue_kind` (§70.7)."""

    MISSING = "MISSING"
    WRONG = "WRONG"
    CONTRADICTION = "CONTRADICTION"
    OTHER = "OTHER"
