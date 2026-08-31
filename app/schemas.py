from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class RegisterRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    display_name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=5, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=10, max_length=200)


class LoginRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=1, max_length=200)


class VerifyEmailRequest(BaseModel):
    token: str = Field(min_length=20, max_length=300)


class PasswordResetRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    email: str = Field(min_length=5, max_length=254)


class PasswordResetConfirmRequest(BaseModel):
    token: str = Field(min_length=20, max_length=300)
    password: str = Field(min_length=10, max_length=200)


class InvitationRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    email: str = Field(min_length=5, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    role: str

    @field_validator("role")
    @classmethod
    def role_must_be_valid(cls, value: str) -> str:
        if value not in {"claimant", "respondent", "manager"}:
            raise ValueError("unsupported role")
        return value


class AcceptInvitationRequest(BaseModel):
    token: str = Field(min_length=20, max_length=300)


class DeadlineRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    label: str = Field(min_length=3, max_length=200)
    kind: str = Field(default="procedural", max_length=50)
    assigned_to: str
    due_at: str

    @field_validator("assigned_to")
    @classmethod
    def assigned_to_must_be_valid(cls, value: str) -> str:
        if value not in {"claimant", "respondent", "manager", "all"}:
            raise ValueError("unsupported assignee")
        return value


class CreateCaseRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=3, max_length=200)
    claimant: str = Field(min_length=2, max_length=200)
    respondent: str = Field(min_length=2, max_length=200)


class AddDocumentRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1, max_length=500_000)
    submitted_by: str
    material_type: str = "evidence"
    purpose: str = Field(default="", max_length=2_000)

    @field_validator("content")
    @classmethod
    def content_must_have_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Document content cannot be blank")
        return value

    @field_validator("submitted_by")
    @classmethod
    def submitted_by_must_be_a_party(cls, value: str) -> str:
        if value not in {"claimant", "respondent"}:
            raise ValueError("submitted_by must be claimant or respondent")
        return value

    @field_validator("material_type")
    @classmethod
    def material_type_must_be_supported(cls, value: str) -> str:
        if value not in {"evidence", "argument"}:
            raise ValueError("material_type must be evidence or argument")
        return value


class ConsentRequest(BaseModel):
    party: str
    accepted: bool
    # Versão dos termos efetivamente exibida à parte. Ausente significa "a
    # versão vigente"; uma versão desconhecida é recusada pelo servidor.
    terms_version: Optional[str] = Field(default=None, max_length=40)

    @field_validator("party")
    @classmethod
    def party_must_be_valid(cls, value: str) -> str:
        if value not in {"claimant", "respondent"}:
            raise ValueError("party must be claimant or respondent")
        return value


class EvidenceActionRequest(BaseModel):
    party: str
    response_status: str = "answered"
    response_text: str = Field(default="", max_length=20_000)

    @field_validator("party")
    @classmethod
    def action_party_must_be_valid(cls, value: str) -> str:
        if value not in {"claimant", "respondent"}:
            raise ValueError("party must be claimant or respondent")
        return value

    @field_validator("response_status")
    @classmethod
    def response_status_must_be_valid(cls, value: str) -> str:
        if value not in {"answered", "waived", "challenged"}:
            raise ValueError("unsupported response_status")
        return value


class ConciliationRoundRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    advance: bool = False
    claimant_response: str = Field(default="", max_length=10_000)
    respondent_response: str = Field(default="", max_length=10_000)
    new_information: str = Field(default="", max_length=10_000)


class ContestRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    reason: str = Field(default="", max_length=10_000)
    explanation: str = Field(default="", max_length=10_000)
    grounds: List[str] = Field(default_factory=list)
    challenged_finding_ids: List[str] = Field(default_factory=list)
    evidence_refs: List[dict] = Field(default_factory=list)
    requested_correction: str = Field(default="", max_length=10_000)

    @field_validator("grounds")
    @classmethod
    def grounds_must_be_supported(cls, value: List[str]) -> List[str]:
        allowed = {
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
        }
        invalid = [item for item in value if item not in allowed]
        if invalid:
            raise ValueError("unsupported appeal ground")
        return value

    def resolved_explanation(self) -> str:
        return (self.explanation or self.reason or "").strip()

    def resolved_grounds(self) -> List[str]:
        return list(self.grounds) or (["other_structured"] if self.resolved_explanation() else [])

    @model_validator(mode="after")
    def explanation_or_reason_required(self) -> "ContestRequest":
        if len(self.resolved_explanation()) < 10:
            raise ValueError("explanation must be at least 10 characters")
        return self


class AttestationVerifyRequest(BaseModel):
    attestation: dict
    public_key_b64: str = ""
