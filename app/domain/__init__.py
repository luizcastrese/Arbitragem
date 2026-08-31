"""Domínio da decisão autônoma: enums, modelos, verificação e proveniência.

Este pacote não chama provedores de IA. A orquestração que usa IA vive em
`app.domain.procedure`.
"""

from app.domain.enums import (
    ABSTENTION_REASONS,
    APPEAL_GROUNDS,
    APPEAL_OUTCOMES,
    AUTOMATIC_REVIEW_OUTCOMES,
    DECISION_OUTCOMES,
    PROCEDURE_CONCLUSIONS,
    AbstentionReason,
    AppealGround,
    AppealOutcome,
    AutomaticReviewOutcome,
    DecisionOutcome,
    ProcedureConclusion,
)
from app.domain.legacy import (
    normalize_legacy_decision,
    normalize_legacy_review,
)

__all__ = [
    "ABSTENTION_REASONS",
    "APPEAL_GROUNDS",
    "APPEAL_OUTCOMES",
    "AUTOMATIC_REVIEW_OUTCOMES",
    "DECISION_OUTCOMES",
    "PROCEDURE_CONCLUSIONS",
    "AbstentionReason",
    "AppealGround",
    "AppealOutcome",
    "AutomaticReviewOutcome",
    "DecisionOutcome",
    "ProcedureConclusion",
    "normalize_legacy_decision",
    "normalize_legacy_review",
]
