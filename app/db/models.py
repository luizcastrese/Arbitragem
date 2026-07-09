from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text
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
    claimant_token_hash = Column(String, nullable=True)
    respondent_token_hash = Column(String, nullable=True)
    manager_token_hash = Column(String, nullable=True)
    manifest_locked = Column(Boolean, nullable=False, default=False)
    locked_manifest_json = Column(Text, nullable=True)
    conciliation_json = Column(Text, nullable=True)
    organized_json = Column(Text, nullable=True)
    decision_json = Column(Text, nullable=True)
    review_json = Column(Text, nullable=True)
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


class Document(Base):
    __tablename__ = "documents"

    id = Column(String, primary_key=True, index=True)
    case_id = Column(String, ForeignKey("cases.id"), nullable=False, index=True)

    name = Column(String, nullable=False)
    content = Column(Text, nullable=False)
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
