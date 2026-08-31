"""Estruturas Pydantic verificáveis da decisão, da revisão e do recurso."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.hashing import sha256_text
from app.domain.enums import (
    AbstentionReason,
    AppealGround,
    AppealOutcome,
    AutomaticReviewOutcome,
    DecisionOutcome,
    FindingStatus,
    ProcedureConclusion,
    SupportType,
)


class EvidenceReference(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    document_id: str = Field(min_length=1, max_length=120)
    document_sha256: str = Field(min_length=64, max_length=64)
    chunk_id: str = Field(min_length=1, max_length=120)
    chunk_sha256: str = Field(min_length=64, max_length=64)
    quoted_text: str = Field(min_length=1, max_length=8_000)
    quoted_text_sha256: str = Field(default="", max_length=64)
    support_type: SupportType
    page_number: Optional[int] = Field(default=None, ge=1)
    start_offset: Optional[int] = Field(default=None, ge=0)
    end_offset: Optional[int] = Field(default=None, ge=0)

    @field_validator("document_sha256", "chunk_sha256", "quoted_text_sha256")
    @classmethod
    def _hex_hash(cls, value: str) -> str:
        if not value:
            return value
        if len(value) != 64 or any(char not in "0123456789abcdef" for char in value.lower()):
            raise ValueError("hash SHA-256 inválido")
        return value.lower()

    @model_validator(mode="after")
    def _fill_quote_hash_and_offsets(self) -> "EvidenceReference":
        expected = sha256_text(self.quoted_text)
        if self.quoted_text_sha256 and self.quoted_text_sha256 != expected:
            raise ValueError("quoted_text_sha256 não confere com o trecho citado")
        object.__setattr__(self, "quoted_text_sha256", expected)
        if (self.start_offset is None) ^ (self.end_offset is None):
            raise ValueError("offsets devem ser informados em par")
        if (
            self.start_offset is not None
            and self.end_offset is not None
            and self.end_offset < self.start_offset
        ):
            raise ValueError("end_offset deve ser >= start_offset")
        return self


class MaterialFinding(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    finding_id: str = Field(min_length=1, max_length=120)
    proposition: str = Field(min_length=1, max_length=8_000)
    status: FindingStatus
    evidence: List[EvidenceReference] = Field(default_factory=list)
    counterevidence: List[EvidenceReference] = Field(default_factory=list)
    reasoning: str = Field(default="", max_length=8_000)
    confidence: float = Field(ge=0, le=1)


class RuleApplication(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    rule_id: str = Field(min_length=1, max_length=200)
    rule_version: str = Field(min_length=1, max_length=40)
    findings_used: List[str] = Field(default_factory=list)
    application_reasoning: str = Field(min_length=1, max_length=8_000)
    conclusion: str = Field(min_length=1, max_length=4_000)


class CalculationInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(min_length=1, max_length=120)
    value_minor_units: int
    currency: str = Field(min_length=3, max_length=8)
    evidence_refs: List[EvidenceReference] = Field(default_factory=list)

    @field_validator("value_minor_units", mode="before")
    @classmethod
    def _no_bool_money(cls, value):
        if isinstance(value, bool) or isinstance(value, float) or not isinstance(value, int):
            raise ValueError("valores monetários devem ser inteiros em minor units")
        return value

    @field_validator("currency")
    @classmethod
    def _currency_upper(cls, value: str) -> str:
        return value.upper()


class RemedyCalculation(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    formula: str = Field(min_length=1, max_length=2_000)
    inputs: List[CalculationInput] = Field(default_factory=list)
    result_minor_units: int
    currency: str = Field(min_length=3, max_length=8)

    @field_validator("result_minor_units", mode="before")
    @classmethod
    def _no_bool_result(cls, value):
        if isinstance(value, bool) or isinstance(value, float) or not isinstance(value, int):
            raise ValueError("valores monetários devem ser inteiros em minor units")
        return value

    @field_validator("currency")
    @classmethod
    def _currency_upper(cls, value: str) -> str:
        return value.upper()


class DecisionOutput(BaseModel):
    """Saída estruturada do julgador. Não contém `requires_human_review`."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    framework_id: str = Field(min_length=1, max_length=80)
    framework_version: str = Field(min_length=1, max_length=40)
    framework: str = Field(default="", max_length=200)
    outcome: DecisionOutcome
    procedure_conclusion: Optional[ProcedureConclusion] = None
    partial_claimant_bps: Optional[int] = Field(default=None, ge=0, le=10000)
    decision: str = Field(min_length=1, max_length=20_000)
    material_findings: List[MaterialFinding] = Field(default_factory=list)
    rule_applications: List[RuleApplication] = Field(default_factory=list)
    remedy_calculation: Optional[RemedyCalculation] = None
    confidence: float = Field(ge=0, le=1)
    limitations: List[str] = Field(default_factory=list)
    abstention_reasons: List[AbstentionReason] = Field(default_factory=list)
    execution: Dict[str, Any] = Field(default_factory=dict)
    verification_summary: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _partial_requires_bps(self) -> "DecisionOutput":
        if self.outcome == "partial" and self.partial_claimant_bps is None:
            raise ValueError(
                "outcome 'partial' exige partial_claimant_bps em basis points"
            )
        return self


class ReviewIssue(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str = Field(min_length=1, max_length=80)
    message: str = Field(min_length=1, max_length=4_000)
    finding_id: Optional[str] = None
    document_id: Optional[str] = None
    chunk_id: Optional[str] = None


class AutomaticReview(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    outcome: AutomaticReviewOutcome
    issues: List[ReviewIssue] = Field(default_factory=list)
    challenged_findings: List[str] = Field(default_factory=list)
    ignored_evidence: List[str] = Field(default_factory=list)
    unsupported_findings: List[str] = Field(default_factory=list)
    calculation_issues: List[str] = Field(default_factory=list)
    framework_issues: List[str] = Field(default_factory=list)
    recommended_conclusion: Optional[ProcedureConclusion] = None
    confidence: float = Field(ge=0, le=1)
    execution: Dict[str, Any] = Field(default_factory=dict)

    @property
    def approved(self) -> bool:
        return self.outcome == "approved"


class StabilityResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    stable: bool
    compared_runs: int = Field(ge=1)
    outcome_agreement: bool
    material_findings_agreement: bool
    remedy_agreement: bool
    material_disagreements: List[str] = Field(default_factory=list)
    execution_ids: List[str] = Field(default_factory=list)
    threshold: float = Field(ge=0, le=1, default=1.0)


class VerificationIssue(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str = Field(min_length=1, max_length=80)
    severity: str = Field(min_length=1, max_length=20)
    message: str = Field(min_length=1, max_length=4_000)
    finding_id: Optional[str] = None
    document_id: Optional[str] = None
    chunk_id: Optional[str] = None


class DecisionVerificationResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    valid: bool
    errors: List[VerificationIssue] = Field(default_factory=list)
    warnings: List[VerificationIssue] = Field(default_factory=list)
    verified_evidence_count: int = 0
    verified_findings_count: int = 0
    verified_rule_applications_count: int = 0
    verified_calculations_count: int = 0
    verifier_version: str = "1.0.0"


class AppealResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    outcome: AppealOutcome
    explanation: str = Field(default="", max_length=20_000)
    corrected_decision: Optional[DecisionOutput] = None
    issues: List[ReviewIssue] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0, le=1)
    execution: Dict[str, Any] = Field(default_factory=dict)


class DecisionProvenance(BaseModel):
    model_config = ConfigDict(extra="ignore")

    hash_algorithm: str = "sha256"
    canonicalization_version: str = "1.0"
    attestation_schema_version: str = "2.0"
    decision_payload_hash: str
    decision_input_hash: str
    evidence_map_hash: str
    framework_hash: str
    prompt_hash: str
    response_schema_hash: str
    model_policy_hash: str
    verification_result_hash: str
    manifest_hash: str
    document_set_hash: str
    timestamp_utc: str
    execution_id: str
