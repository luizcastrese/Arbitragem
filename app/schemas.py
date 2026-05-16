from typing import List, Optional

from pydantic import BaseModel


class CreateCaseRequest(BaseModel):
    title: str
    claimant: str
    respondent: str


class AddDocumentRequest(BaseModel):
    name: str
    content: str


class ChunkRecord(BaseModel):
    id: str
    document_id: str
    text: str
    sha256: str
    embedding: Optional[List[float]] = None


class DecisionResponse(BaseModel):
    framework: str
    decision: str
    confidence: float
