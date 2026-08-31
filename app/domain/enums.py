"""Estados autônomos do procedimento. Centralizados para API, domínio e UI.

Novos resultados nunca usam `requires_human_review`. Registros antigos que
contenham esse campo continuam legíveis via `app.domain.legacy`.
"""

from typing import FrozenSet, Literal, Tuple

DecisionOutcome = Literal["claimant", "respondent", "partial", "inconclusive"]

ProcedureConclusion = Literal[
    "agreement",
    "decided",
    "inconclusive",
    "inadmissible",
    "invalidated",
    "system_failure",
]

AutomaticReviewOutcome = Literal["approved", "rejected", "inconclusive"]

AppealOutcome = Literal[
    "upheld",
    "corrected",
    "annulled",
    "inconclusive",
    "inadmissible",
]

AbstentionReason = Literal[
    "insufficient_evidence",
    "contradictory_material_evidence",
    "missing_mandatory_document",
    "unsupported_calculation",
    "material_model_disagreement",
    "framework_not_applicable",
    "technical_expertise_required",
    "procedure_integrity_failure",
    "prompt_injection_detected",
    "provider_unavailable",
    "out_of_scope",
    "unsupported_claim",
    "unstable_decision",
    "system_failure",
]

AppealGround = Literal[
    "ignored_evidence",
    "invented_fact",
    "wrong_document_attribution",
    "incorrect_calculation",
    "incorrect_rule_application",
    "contradictory_reasoning",
    "procedure_violation",
    "integrity_failure",
    "model_policy_violation",
    "decision_beyond_claim",
    "other_structured",
]

FindingStatus = Literal[
    "established",
    "not_established",
    "disputed",
    "insufficient",
]

SupportType = Literal["direct", "corroborative", "contextual", "contradictory"]

DECISION_OUTCOMES: Tuple[str, ...] = (
    "claimant",
    "respondent",
    "partial",
    "inconclusive",
)
PROCEDURE_CONCLUSIONS: Tuple[str, ...] = (
    "agreement",
    "decided",
    "inconclusive",
    "inadmissible",
    "invalidated",
    "system_failure",
)
AUTOMATIC_REVIEW_OUTCOMES: Tuple[str, ...] = (
    "approved",
    "rejected",
    "inconclusive",
)
APPEAL_OUTCOMES: Tuple[str, ...] = (
    "upheld",
    "corrected",
    "annulled",
    "inconclusive",
    "inadmissible",
)
ABSTENTION_REASONS: Tuple[str, ...] = (
    "insufficient_evidence",
    "contradictory_material_evidence",
    "missing_mandatory_document",
    "unsupported_calculation",
    "material_model_disagreement",
    "framework_not_applicable",
    "technical_expertise_required",
    "procedure_integrity_failure",
    "prompt_injection_detected",
    "provider_unavailable",
    "out_of_scope",
    "unsupported_claim",
    "unstable_decision",
    "system_failure",
)
APPEAL_GROUNDS: Tuple[str, ...] = (
    "ignored_evidence",
    "invented_fact",
    "wrong_document_attribution",
    "incorrect_calculation",
    "incorrect_rule_application",
    "contradictory_reasoning",
    "procedure_violation",
    "integrity_failure",
    "model_policy_violation",
    "decision_beyond_claim",
    "other_structured",
)

EXECUTABLE_OUTCOMES: FrozenSet[str] = frozenset({"claimant", "respondent", "partial"})
MERIT_CONCLUSIONS: FrozenSet[str] = frozenset({"decided", "agreement"})
