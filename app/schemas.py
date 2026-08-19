from pydantic import BaseModel, ConfigDict, Field, field_validator


class RegisterRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    display_name: str = Field(min_length=2, max_length=120)
    email: str = Field(min_length=5, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=10, max_length=200)


class LoginRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=1, max_length=200)


# O procedimento tem exatamente dois papéis humanos. O terceiro que conduz o
# rito não é uma pessoa e por isso não aparece em nenhum payload.
PARTY_ROLES = {"claimant", "respondent"}


class InvitationRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    email: str = Field(min_length=5, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    role: str

    @field_validator("role")
    @classmethod
    def role_must_be_valid(cls, value: str) -> str:
        if value not in PARTY_ROLES:
            raise ValueError("role must be claimant or respondent")
        return value


class EmailRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    email: str = Field(min_length=5, max_length=254)


class TokenRequest(BaseModel):
    token: str = Field(min_length=20, max_length=300)


class PasswordResetRequest(BaseModel):
    token: str = Field(min_length=20, max_length=300)
    password: str = Field(min_length=10, max_length=200)


class AcceptInvitationRequest(BaseModel):
    token: str = Field(min_length=20, max_length=300)


class CreateCaseRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    title: str = Field(min_length=3, max_length=200)
    claimant: str = Field(min_length=2, max_length=200)
    respondent: str = Field(min_length=2, max_length=200)
    # Quem abre o caso declara de que lado está. Ninguém entra como terceiro.
    creator_role: str

    @field_validator("creator_role")
    @classmethod
    def creator_role_must_be_a_party(cls, value: str) -> str:
        if value not in PARTY_ROLES:
            raise ValueError("creator_role must be claimant or respondent")
        return value


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
    """A versão dos termos não vem daqui: quem a define é o servidor, para que
    o registro diga o que foi apresentado e não o que o cliente afirmou."""

    party: str
    accepted: bool

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


class SubmissionClosureRequest(BaseModel):
    """Encerramento (ou reabertura) da produção de material pela própria parte.
    O papel de quem age vem da credencial, nunca do corpo da requisição."""

    closed: bool = True


class CompositionPositionRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    position: str = Field(min_length=1, max_length=10_000)


class RatificationRequest(BaseModel):
    """Manifestação da parte sobre uma decisão que a auditoria ressalvou.

    Aceitar dispensa justificativa; recusar exige, porque a recusa encerra o
    caso sem decisão executável e o motivo passa a integrar o registro.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    accepted: bool
    reason: str = Field(default="", max_length=10_000)

    @field_validator("reason")
    @classmethod
    def rejection_needs_a_reason(cls, value: str, info) -> str:
        if info.data.get("accepted") is False and len(value.strip()) < 10:
            raise ValueError("Informe o motivo da recusa")
        return value


class ContestRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    reason: str = Field(min_length=10, max_length=10_000)


class AttestationVerifyRequest(BaseModel):
    attestation: dict
    public_key_b64: str = ""
