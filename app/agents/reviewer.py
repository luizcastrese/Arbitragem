from typing import Dict


def review_decision(decision: Dict) -> Dict:
    confidence = decision.get("confidence", 0)

    return {
        "approved": confidence >= 0.7,
        "issues": [],
        "needs_human": confidence < 0.7
    }
