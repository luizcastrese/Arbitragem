from typing import Dict, List, Optional


cases: Dict[str, dict] = {}


def create_case_record(payload: dict) -> dict:
    case_id = str(len(cases) + 1)

    case = {
        "id": case_id,
        "title": payload.get("title"),
        "claimant": payload.get("claimant"),
        "respondent": payload.get("respondent"),
        "documents": [],
        "chunks": [],
        "organized": None,
        "decision": None,
        "review": None,
        "locked_manifest": None,
        "manifest_locked": False,
        "audit_log": []
    }

    cases[case_id] = case
    return case


def get_case(case_id: str) -> Optional[dict]:
    return cases.get(case_id)


def list_cases() -> List[dict]:
    return list(cases.values())


def append_audit(case: dict, event_type: str, payload: dict):
    case.setdefault("audit_log", []).append({
        "event_type": event_type,
        "payload": payload
    })
