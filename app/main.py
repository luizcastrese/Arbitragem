from fastapi import FastAPI, File, HTTPException, UploadFile

from app.agents.judge import decide_case as judge_decide_case
from app.agents.organizer import organize_case as organizer_organize_case
from app.agents.reviewer import review_decision
from app.core.hashing import sha256_text
from app.documents.chunker import chunk_text
from app.documents.embeddings import build_embedding, retrieve_by_embedding
from app.documents.pdf_parser import extract_text_from_pdf_bytes
from app.documents.retrieval import retrieve_relevant_chunks
from app.reports.report_generator import build_report

app = FastAPI(title="Arbitragem MVP")

cases = {}


@app.get("/")
def root():
    return {
        "project": "Arbitragem MVP",
        "status": "running",
        "description": "AI-assisted arbitration workflow prototype"
    }


@app.post("/cases")
def create_case(payload: dict):
    case_id = str(len(cases) + 1)

    cases[case_id] = {
        "id": case_id,
        "title": payload.get("title"),
        "claimant": payload.get("claimant"),
        "respondent": payload.get("respondent"),
        "documents": [],
        "chunks": [],
        "organized": None,
        "decision": None,
        "review": None
    }

    return cases[case_id]



def get_case_or_404(case_id: str):
    if case_id not in cases:
        raise HTTPException(status_code=404, detail="Case not found")
    return cases[case_id]



def process_document(case: dict, name: str, content: str):
    document_id = f"D{len(case['documents']) + 1}"
    document_hash = sha256_text(content)
    chunks = chunk_text(content)

    document = {
        "id": document_id,
        "name": name,
        "content": content,
        "sha256": document_hash,
        "chunks_count": len(chunks)
    }

    case["documents"].append(document)

    for index, chunk in enumerate(chunks, start=1):
        chunk_record = {
            "id": f"{document_id}-C{index}",
            "document_id": document_id,
            "text": chunk,
            "sha256": sha256_text(chunk),
            "embedding": None
        }

        try:
            chunk_record["embedding"] = build_embedding(chunk)
        except Exception:
            chunk_record["embedding_error"] = True

        case["chunks"].append(chunk_record)

    return document


@app.post("/cases/{case_id}/documents/text")
def add_document(case_id: str, payload: dict):
    case = get_case_or_404(case_id)

    content = payload.get("content", "")

    if not content:
        raise HTTPException(status_code=400, detail="Document content is required")

    document = process_document(
        case=case,
        name=payload.get("name", "text_document"),
        content=content
    )

    return {
        "message": "document added",
        "document": document
    }


@app.post("/cases/{case_id}/documents/pdf")
async def upload_pdf(case_id: str, file: UploadFile = File(...)):
    case = get_case_or_404(case_id)

    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    file_bytes = await file.read()

    try:
        extracted_text = extract_text_from_pdf_bytes(file_bytes)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"PDF parsing failed: {str(exc)}")

    if not extracted_text.strip():
        raise HTTPException(status_code=400, detail="No readable text found in PDF")

    document = process_document(
        case=case,
        name=file.filename,
        content=extracted_text
    )

    return {
        "message": "pdf processed",
        "document": document,
        "text_preview": extracted_text[:1000]
    }


@app.get("/cases/{case_id}/chunks")
def list_chunks(case_id: str):
    case = get_case_or_404(case_id)
    return case["chunks"]


@app.get("/cases/{case_id}/retrieve")
def retrieve_chunks(case_id: str, query: str, method: str = "embedding"):
    case = get_case_or_404(case_id)

    if method == "embedding":
        try:
            return retrieve_by_embedding(
                query=query,
                chunks=case["chunks"],
                limit=5
            )
        except Exception:
            pass

    return retrieve_relevant_chunks(
        query=query,
        chunks=case["chunks"],
        limit=5
    )


@app.post("/cases/{case_id}/organize")
def organize_case(case_id: str):
    case = get_case_or_404(case_id)

    organized = organizer_organize_case(
        documents=case["documents"],
        chunks=case["chunks"]
    )

    case["organized"] = organized

    return organized


@app.post("/cases/{case_id}/decide")
def decide_case(case_id: str):
    case = get_case_or_404(case_id)

    if not case.get("organized"):
        raise HTTPException(status_code=400, detail="Case must be organized before decision")

    decision_context = {
        "organized_case": case["organized"],
        "retrieved_evidence": {
            "delivery": retrieve_chunks(case_id, "delivery obligations and partial fulfillment"),
            "payment": retrieve_chunks(case_id, "payment terms and proportional payment"),
            "deadline": retrieve_chunks(case_id, "deadline compliance and delay")
        }
    }

    decision = judge_decide_case(decision_context)
    case["decision"] = decision

    return decision


@app.post("/cases/{case_id}/review")
def review_case(case_id: str):
    case = get_case_or_404(case_id)

    if not case.get("decision"):
        raise HTTPException(status_code=400, detail="Case must be decided before review")

    review = review_decision(case["decision"])
    case["review"] = review

    return review


@app.get("/cases/{case_id}/report")
def report(case_id: str):
    case = get_case_or_404(case_id)
    return build_report(case)
