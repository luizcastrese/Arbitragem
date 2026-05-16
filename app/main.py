from fastapi import FastAPI

app = FastAPI(title="Arbitragem MVP")

cases = {}

@app.get("/")
def root():
    return {
        "project": "Arbitragem MVP",
        "status": "running"
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
        "organized": None,
        "decision": None,
        "review": None
    }

    return cases[case_id]

@app.post("/cases/{case_id}/documents/text")
def add_document(case_id: str, payload: dict):
    document = {
        "name": payload.get("name"),
        "content": payload.get("content")
    }

    cases[case_id]["documents"].append(document)

    return {
        "message": "document added",
        "document": document
    }

@app.post("/cases/{case_id}/organize")
def organize_case(case_id: str):
    case = cases[case_id]

    organized = {
        "summary": "Potential dispute regarding delivery and payment.",
        "controversial_points": [
            "partial delivery",
            "deadline compliance"
        ],
        "documents_count": len(case["documents"])
    }

    case["organized"] = organized

    return organized

@app.post("/cases/{case_id}/decide")
def decide_case(case_id: str):
    case = cases[case_id]

    decision = {
        "framework": "Commercial Balanced",
        "decision": "Release 70% payment to contractor.",
        "confidence": 0.81
    }

    case["decision"] = decision

    return decision

@app.post("/cases/{case_id}/review")
def review_case(case_id: str):
    case = cases[case_id]

    review = {
        "approved": True,
        "issues": [],
        "needs_human": False
    }

    case["review"] = review

    return review

@app.get("/cases/{case_id}/report")
def report(case_id: str):
    return cases[case_id]
