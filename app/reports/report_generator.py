from typing import Dict


def build_report(case: Dict) -> Dict:
    return {
        "case_id": case.get("id"),
        "title": case.get("title"),
        "organized": case.get("organized"),
        "decision": case.get("decision"),
        "review": case.get("review")
    }
