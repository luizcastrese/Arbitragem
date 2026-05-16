from sqlalchemy.orm import Session

from app.db.models import Case, Chunk, Document



def create_case(db: Session, title: str, claimant: str, respondent: str):
    case = Case(
        title=title,
        claimant=claimant,
        respondent=respondent
    )

    db.add(case)
    db.commit()
    db.refresh(case)

    return case



def create_document(db: Session, case_id: int, name: str, content: str, sha256: str):
    document = Document(
        case_id=case_id,
        name=name,
        content=content,
        sha256=sha256
    )

    db.add(document)
    db.commit()
    db.refresh(document)

    return document



def create_chunk(db: Session, document_id: int, text: str, sha256: str, embedding_preview: str = ""):
    chunk = Chunk(
        document_id=document_id,
        text=text,
        sha256=sha256,
        embedding_preview=embedding_preview
    )

    db.add(chunk)
    db.commit()
    db.refresh(chunk)

    return chunk
