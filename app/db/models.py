from sqlalchemy import Column, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from app.db.session import Base


class Case(Base):
    __tablename__ = "cases"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    claimant = Column(String, nullable=False)
    respondent = Column(String, nullable=False)

    documents = relationship("Document", back_populates="case")


class Document(Base):
    __tablename__ = "documents"

    id = Column(Integer, primary_key=True, index=True)
    case_id = Column(Integer, ForeignKey("cases.id"))

    name = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    sha256 = Column(String, nullable=False)

    case = relationship("Case", back_populates="documents")
    chunks = relationship("Chunk", back_populates="document")


class Chunk(Base):
    __tablename__ = "chunks"

    id = Column(Integer, primary_key=True, index=True)
    document_id = Column(Integer, ForeignKey("documents.id"))

    text = Column(Text, nullable=False)
    sha256 = Column(String, nullable=False)
    embedding_preview = Column(Text, nullable=True)
    similarity_score = Column(Float, nullable=True)

    document = relationship("Document", back_populates="chunks")
