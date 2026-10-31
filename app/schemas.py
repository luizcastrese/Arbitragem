from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.tax_id import InvalidTaxId, normalize_tax_id


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
        # O árbitro é convidado por uma parte e só atua depois de aceitar a
        # nomeação e ser confirmado pelas duas.
        if value not in {"claimant", "respondent", "arbitrator"}:
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
        if value not in {"claimant", "respondent", "all"}:
            raise ValueError("unsupported assignee")
        return value


class CreateCaseRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=3, max_length=200)
    claimant: str = Field(min_length=2, max_length=200)
    respondent: str = Field(min_length=2, max_length=200)
    # Via do caso: antes do processo ou com processo já ajuizado, que as
    # partes trocam pela Valinor. No segundo caso, número CNJ e juízo.
    entry_point: str = Field(default="pre_litigation", max_length=40)
    lawsuit_number: Optional[str] = Field(default=None, max_length=40)
    court: Optional[str] = Field(default=None, max_length=200)
    # Matéria (framework). Ausente, vale a matéria padrão da plataforma.
    matter_framework_id: Optional[str] = Field(default=None, max_length=80)
    # Em relação de consumo, qual parte é o consumidor.
    consumer_party: Optional[str] = Field(default=None, max_length=20)


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
    # CPF ou CNPJ da própria parte. Qualifica a parte no auto da decisão;
    # ausente, o auto registra que a qualificação não foi informada.
    tax_id: Optional[str] = Field(default=None, max_length=32)
    # Escolha individual, feita depois do conflito, de submeter a disputa à
    # arbitragem se não houver acordo. Ausente mantém a escolha anterior.
    elects_arbitration: Optional[bool] = None

    @field_validator("party")
    @classmethod
    def party_must_be_valid(cls, value: str) -> str:
        if value not in {"claimant", "respondent"}:
            raise ValueError("party must be claimant or respondent")
        return value

    @field_validator("tax_id")
    @classmethod
    def tax_id_must_be_valid(cls, value: Optional[str]) -> Optional[str]:
        try:
            return normalize_tax_id(value)
        except InvalidTaxId as exc:
            raise ValueError(str(exc)) from exc


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


class AgreementResponseRequest(BaseModel):
    """Manifestação individual sobre a proposta de uma rodada.

    A reclamante nunca pode registrar a manifestação da reclamada (ou vice-versa),
    por isso o papel faz parte do corpo e também é conferido contra a
    credencial pelo endpoint.
    """

    party: str
    accepted: bool

    @field_validator("party")
    @classmethod
    def party_must_be_valid(cls, value: str) -> str:
        if value not in {"claimant", "respondent"}:
            raise ValueError("party must be claimant or respondent")
        return value


class ArbitratorAcceptRequest(BaseModel):
    """O árbitro aceita a nomeação, se qualifica e declara independência."""

    model_config = ConfigDict(str_strip_whitespace=True)

    tax_id: str = Field(min_length=11, max_length=32)
    qualification: str = Field(min_length=5, max_length=500)
    independent: bool
    disclosure: str = Field(default="", max_length=5_000)

    @field_validator("tax_id")
    @classmethod
    def tax_id_must_be_cpf(cls, value: str) -> str:
        try:
            normalized = normalize_tax_id(value)
        except InvalidTaxId as exc:
            raise ValueError(str(exc)) from exc
        if not normalized or len(normalized) != 11:
            raise ValueError("o árbitro é pessoa física: informe um CPF")
        return normalized

    @field_validator("independent")
    @classmethod
    def must_declare_independence(cls, value: bool) -> bool:
        if not value:
            raise ValueError(
                "sem independência declarada, a nomeação não pode ser aceita"
            )
        return value


class ArbitratorConfirmRequest(BaseModel):
    party: str

    @field_validator("party")
    @classmethod
    def party_must_be_valid(cls, value: str) -> str:
        if value not in {"claimant", "respondent"}:
            raise ValueError("party must be claimant or respondent")
        return value


class ArbitralAwardRequest(BaseModel):
    """O árbitro adota e assina a decisão como sentença, ou recusa adotá-la."""

    model_config = ConfigDict(str_strip_whitespace=True)

    adopt: bool
    place: str = Field(min_length=2, max_length=200)
    statement: str = Field(default="", max_length=10_000)


class WithdrawToCourtRequest(BaseModel):
    """A parte deixa a Valinor e leva o conflito ao Judiciário.

    É um ato só dela, possível a qualquer momento antes do desfecho. O caso
    encerra e as duas partes recebem o auto com o histórico até ali.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    party: str
    reason: str = Field(default="", max_length=2_000)

    @field_validator("party")
    @classmethod
    def party_must_be_valid(cls, value: str) -> str:
        if value not in {"claimant", "respondent"}:
            raise ValueError("party must be claimant or respondent")
        return value


class SubmissionReadyRequest(BaseModel):
    """A parte encerra ou reabre a própria apresentação. Não conduz o rito."""

    party: str
    ready: bool = True

    @field_validator("party")
    @classmethod
    def party_must_be_valid(cls, value: str) -> str:
        if value not in {"claimant", "respondent"}:
            raise ValueError("party must be claimant or respondent")
        return value


class ConciliationPositionRequest(BaseModel):
    """Posição de uma parte numa rodada. O gestor decide se há outra rodada."""

    model_config = ConfigDict(str_strip_whitespace=True)

    party: str
    text: str = Field(default="", max_length=10_000)
    waived: bool = False

    @field_validator("party")
    @classmethod
    def party_must_be_valid(cls, value: str) -> str:
        if value not in {"claimant", "respondent"}:
            raise ValueError("party must be claimant or respondent")
        return value


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


class DecisionRecordVerifyRequest(BaseModel):
    record: dict
    public_key_b64: str = ""
