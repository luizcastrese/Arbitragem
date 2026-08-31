from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import relationship

from app.db.session import Base


def utc_now():
    return datetime.now(timezone.utc)


class Case(Base):
    __tablename__ = "cases"

    id = Column(String, primary_key=True, index=True)
    title = Column(String, nullable=False)
    claimant = Column(String, nullable=False)
    respondent = Column(String, nullable=False)
    status = Column(String, nullable=False, default="draft")
    claimant_consent = Column(Boolean, nullable=False, default=False)
    respondent_consent = Column(Boolean, nullable=False, default=False)
    claimant_consent_at = Column(String, nullable=True)
    respondent_consent_at = Column(String, nullable=True)
    # Versão e hash do texto de termos efetivamente exibido e aceito por cada
    # parte. O hash é o que permite provar, depois, o que foi aceito.
    claimant_terms_version = Column(String, nullable=True)
    claimant_terms_sha256 = Column(String, nullable=True)
    respondent_terms_version = Column(String, nullable=True)
    respondent_terms_sha256 = Column(String, nullable=True)
    claimant_token_hash = Column(String, nullable=True)
    respondent_token_hash = Column(String, nullable=True)
    manager_token_hash = Column(String, nullable=True)
    manifest_locked = Column(Boolean, nullable=False, default=False)
    locked_manifest_json = Column(Text, nullable=True)
    conciliation_json = Column(Text, nullable=True)
    organized_json = Column(Text, nullable=True)
    decision_json = Column(Text, nullable=True)
    review_json = Column(Text, nullable=True)
    attestation_json = Column(Text, nullable=True)
    nostr_anchor_json = Column(Text, nullable=True)
    escrow_id = Column(String, nullable=True)
    contested_at = Column(String, nullable=True)
    contested_by = Column(String, nullable=True)
    procedure_conclusion = Column(String, nullable=True)
    row_version = Column(Integer, nullable=False, default=1)
    processing_started_at = Column(DateTime(timezone=True), nullable=True)
    current_decision_run_id = Column(String, nullable=True)
    current_review_run_id = Column(String, nullable=True)
    verification_json = Column(Text, nullable=True)
    stability_json = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    documents = relationship(
        "Document",
        back_populates="case",
        cascade="all, delete-orphan",
        order_by="Document.created_at",
    )
    chunks = relationship(
        "Chunk",
        back_populates="case",
        cascade="all, delete-orphan",
        order_by="Chunk.created_at",
    )
    audit_events = relationship(
        "AuditEvent",
        back_populates="case",
        cascade="all, delete-orphan",
        order_by="AuditEvent.id",
    )
    members = relationship("CaseMember", back_populates="case", cascade="all, delete-orphan")
    invitations = relationship("Invitation", back_populates="case", cascade="all, delete-orphan")
    deadlines = relationship("Deadline", back_populates="case", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="case", cascade="all, delete-orphan")
    llm_executions = relationship(
        "LLMExecution", back_populates="case", cascade="all, delete-orphan"
    )
    decision_runs = relationship(
        "DecisionRun", back_populates="case", cascade="all, delete-orphan"
    )
    review_runs = relationship(
        "AutomaticReviewRun", back_populates="case", cascade="all, delete-orphan"
    )
    verifications = relationship(
        "DecisionVerification", back_populates="case", cascade="all, delete-orphan"
    )
    appeals = relationship(
        "AutomaticAppeal", back_populates="case", cascade="all, delete-orphan"
    )
    attestation_records = relationship(
        "AttestationRecord", back_populates="case", cascade="all, delete-orphan"
    )


class Document(Base):
    __tablename__ = "documents"

    id = Column(String, primary_key=True, index=True)
    case_id = Column(String, ForeignKey("cases.id"), nullable=False, index=True)

    name = Column(String, nullable=False)
    # Os bytes ficam no object store; o banco guarda apenas as referências.
    content_key = Column(String, nullable=False)
    original_key = Column(String, nullable=True)
    original_media_type = Column(String, nullable=True)
    byte_size = Column(Integer, nullable=False, default=0)
    sha256 = Column(String, nullable=False)
    submitted_by = Column(String, nullable=False, default="claimant")
    material_type = Column(String, nullable=False, default="evidence")
    purpose = Column(Text, nullable=False, default="")
    disclosed_at = Column(String, nullable=True)
    acknowledged_at = Column(String, nullable=True)
    acknowledged_by = Column(String, nullable=True)
    response_status = Column(String, nullable=False, default="pending")
    response_text = Column(Text, nullable=False, default="")
    responded_at = Column(String, nullable=True)
    admitted = Column(Boolean, nullable=False, default=False)
    admitted_at = Column(String, nullable=True)
    chunks_count = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    case = relationship("Case", back_populates="documents")
    chunks = relationship(
        "Chunk",
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="Chunk.created_at",
    )


class Chunk(Base):
    __tablename__ = "chunks"

    id = Column(String, primary_key=True, index=True)
    case_id = Column(String, ForeignKey("cases.id"), nullable=False, index=True)
    document_id = Column(String, ForeignKey("documents.id"), nullable=False, index=True)

    text = Column(Text, nullable=False)
    sha256 = Column(String, nullable=False)
    embedding_json = Column(Text, nullable=True)
    embedding_error = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    case = relationship("Case", back_populates="chunks")
    document = relationship("Document", back_populates="chunks")


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id = Column(Integer, primary_key=True, index=True)
    case_id = Column(String, ForeignKey("cases.id"), nullable=False, index=True)
    event_type = Column(String, nullable=False)
    timestamp_utc = Column(String, nullable=False)
    payload_json = Column(Text, nullable=False)
    previous_hash = Column(String, nullable=False, default="")
    event_hash = Column(String, nullable=False, index=True)

    case = relationship("Case", back_populates="audit_events")


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True)
    email = Column(String, nullable=False, unique=True, index=True)
    display_name = Column(String, nullable=False)
    password_hash = Column(Text, nullable=False)
    active = Column(Boolean, nullable=False, default=True)
    email_verified_at = Column(DateTime(timezone=True), nullable=True)
    failed_login_attempts = Column(Integer, nullable=False, default=0)
    locked_until = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    sessions = relationship("AuthSession", back_populates="user", cascade="all, delete-orphan")
    memberships = relationship("CaseMember", back_populates="user", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="user")
    auth_tokens = relationship(
        "AuthToken",
        back_populates="user",
        cascade="all, delete-orphan",
    )


class AuthToken(Base):
    """Token de uso único para verificação de e-mail e redefinição de senha.

    Só o hash é persistido: quem tem acesso ao banco não consegue reconstruir
    o link enviado por e-mail.
    """

    __tablename__ = "auth_tokens"

    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    purpose = Column(String, nullable=False, index=True)
    token_hash = Column(String, nullable=False, unique=True, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    user = relationship("User", back_populates="auth_tokens")


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    id = Column(String, primary_key=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    token_hash = Column(String, nullable=False, unique=True, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    user = relationship("User", back_populates="sessions")


class CaseMember(Base):
    __tablename__ = "case_members"
    __table_args__ = (UniqueConstraint("case_id", "user_id", "role"),)

    id = Column(String, primary_key=True)
    case_id = Column(String, ForeignKey("cases.id"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False, index=True)
    role = Column(String, nullable=False)
    joined_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    case = relationship("Case", back_populates="members")
    user = relationship("User", back_populates="memberships")


class Invitation(Base):
    __tablename__ = "invitations"

    id = Column(String, primary_key=True)
    case_id = Column(String, ForeignKey("cases.id"), nullable=False, index=True)
    email = Column(String, nullable=False, index=True)
    role = Column(String, nullable=False)
    token_hash = Column(String, nullable=False, unique=True, index=True)
    status = Column(String, nullable=False, default="pending")
    expires_at = Column(DateTime(timezone=True), nullable=False)
    accepted_at = Column(DateTime(timezone=True), nullable=True)
    invited_by_user_id = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    case = relationship("Case", back_populates="invitations")


class Deadline(Base):
    __tablename__ = "deadlines"

    id = Column(String, primary_key=True)
    case_id = Column(String, ForeignKey("cases.id"), nullable=False, index=True)
    label = Column(String, nullable=False)
    kind = Column(String, nullable=False)
    assigned_to = Column(String, nullable=False)
    due_at = Column(DateTime(timezone=True), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    case = relationship("Case", back_populates="deadlines")


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(String, primary_key=True)
    case_id = Column(String, ForeignKey("cases.id"), nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=True, index=True)
    party = Column(String, nullable=False)
    event_type = Column(String, nullable=False)
    title = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    read_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    case = relationship("Case", back_populates="notifications")
    user = relationship("User", back_populates="notifications")


class LLMExecution(Base):
    __tablename__ = "llm_executions"

    id = Column(String, primary_key=True)
    case_id = Column(String, ForeignKey("cases.id"), nullable=False, index=True)
    agent = Column(String, nullable=False, index=True)
    task = Column(String, nullable=False, default="")
    requested_provider = Column(String, nullable=False, default="")
    requested_model = Column(String, nullable=False, default="")
    effective_provider = Column(String, nullable=False, default="")
    effective_model = Column(String, nullable=True)
    provider_response_id = Column(String, nullable=True)
    prompt_tokens = Column(Integer, nullable=True)
    completion_tokens = Column(Integer, nullable=True)
    total_tokens = Column(Integer, nullable=True)
    latency_ms = Column(Float, nullable=True)
    attempts = Column(Integer, nullable=False, default=1)
    fallback_used = Column(Boolean, nullable=False, default=False)
    fallback_reason = Column(String, nullable=True)
    status = Column(String, nullable=False, default="completed")
    input_hash = Column(String, nullable=True)
    output_hash = Column(String, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    case = relationship("Case", back_populates="llm_executions")


class DecisionRun(Base):
    __tablename__ = "decision_runs"
    __table_args__ = (
        UniqueConstraint("case_id", "version", name="uq_decision_runs_case_version"),
        UniqueConstraint("case_id", "idempotency_key", name="uq_decision_runs_idempotency"),
    )

    id = Column(String, primary_key=True)
    case_id = Column(String, ForeignKey("cases.id"), nullable=False, index=True)
    version = Column(Integer, nullable=False, default=1)
    supersedes_id = Column(String, ForeignKey("decision_runs.id"), nullable=True)
    status = Column(String, nullable=False, default="processing", index=True)
    role = Column(String, nullable=False, default="judge")
    execution_id = Column(String, nullable=True, index=True)
    idempotency_key = Column(String, nullable=True)
    input_hash = Column(String, nullable=True)
    output_hash = Column(String, nullable=True)
    payload_json = Column(Text, nullable=True)
    provenance_json = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    case = relationship("Case", back_populates="decision_runs")


class AutomaticReviewRun(Base):
    __tablename__ = "automatic_review_runs"
    __table_args__ = (
        UniqueConstraint("case_id", "version", name="uq_review_runs_case_version"),
    )

    id = Column(String, primary_key=True)
    case_id = Column(String, ForeignKey("cases.id"), nullable=False, index=True)
    decision_run_id = Column(String, ForeignKey("decision_runs.id"), nullable=True)
    version = Column(Integer, nullable=False, default=1)
    supersedes_id = Column(String, ForeignKey("automatic_review_runs.id"), nullable=True)
    status = Column(String, nullable=False, default="processing", index=True)
    outcome = Column(String, nullable=True)
    execution_id = Column(String, nullable=True)
    input_hash = Column(String, nullable=True)
    output_hash = Column(String, nullable=True)
    payload_json = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    case = relationship("Case", back_populates="review_runs")


class DecisionVerification(Base):
    __tablename__ = "decision_verifications"

    id = Column(String, primary_key=True)
    case_id = Column(String, ForeignKey("cases.id"), nullable=False, index=True)
    decision_run_id = Column(String, ForeignKey("decision_runs.id"), nullable=True)
    valid = Column(Boolean, nullable=False, default=False)
    result_json = Column(Text, nullable=False, default="{}")
    result_hash = Column(String, nullable=False, default="")
    execution_id = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    case = relationship("Case", back_populates="verifications")


class AutomaticAppeal(Base):
    __tablename__ = "automatic_appeals"
    __table_args__ = (
        UniqueConstraint("case_id", "idempotency_key", name="uq_appeals_idempotency"),
    )

    id = Column(String, primary_key=True)
    case_id = Column(String, ForeignKey("cases.id"), nullable=False, index=True)
    filed_by = Column(String, nullable=False)
    grounds_json = Column(Text, nullable=False, default="[]")
    original_decision_hash = Column(String, nullable=False, default="")
    status = Column(String, nullable=False, default="filed", index=True)
    appeal_provider = Column(String, nullable=True)
    appeal_model = Column(String, nullable=True)
    result_json = Column(Text, nullable=True)
    result_hash = Column(String, nullable=True)
    idempotency_key = Column(String, nullable=True)
    execution_id = Column(String, nullable=True)
    version = Column(Integer, nullable=False, default=1)
    supersedes_id = Column(String, ForeignKey("automatic_appeals.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    completed_at = Column(DateTime(timezone=True), nullable=True)

    case = relationship("Case", back_populates="appeals")


class AttestationRecord(Base):
    __tablename__ = "attestation_records"
    __table_args__ = (
        UniqueConstraint("case_id", "version", name="uq_attestation_records_version"),
    )

    id = Column(String, primary_key=True)
    case_id = Column(String, ForeignKey("cases.id"), nullable=False, index=True)
    version = Column(Integer, nullable=False, default=1)
    supersedes_id = Column(String, ForeignKey("attestation_records.id"), nullable=True)
    status = Column(String, nullable=False, default="issued")
    payload_json = Column(Text, nullable=False)
    attestation_hash = Column(String, nullable=False, index=True)
    decision_run_id = Column(String, ForeignKey("decision_runs.id"), nullable=True)
    review_run_id = Column(String, ForeignKey("automatic_review_runs.id"), nullable=True)
    verification_id = Column(String, ForeignKey("decision_verifications.id"), nullable=True)
    appeal_id = Column(String, ForeignKey("automatic_appeals.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)

    case = relationship("Case", back_populates="attestation_records")
