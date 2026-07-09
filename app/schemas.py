from pydantic import BaseModel, ConfigDict, Field, field_validator


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
