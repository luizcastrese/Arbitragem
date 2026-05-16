from typing import Dict

from app.core.llm import call_openai_json


SYSTEM_PROMPT = """
You are a critical reviewer for an AI-assisted arbitration system.

Your task is NOT to produce a new decision.
Your task is to audit the existing decision.

Analyze:
- contradictions
- unsupported claims
- ignored evidence
- low confidence reasoning
- framework violations
- missing evidence
- logical inconsistencies

Return ONLY valid JSON with:
- approved
- issues
- risks
- contradictions
- missing_evidence
- framework_alignment
- confidence_assessment
- requires_human_review
"""



def review_decision(decision: Dict) -> Dict:
    try:
        result = call_openai_json(
            system_prompt=SYSTEM_PROMPT,
            user_payload=decision
        )

        return result

    except Exception:
        confidence = decision.get("confidence", 0)

        return {
            "approved": confidence >= 0.7,
            "issues": [],
            "risks": [],
            "contradictions": [],
            "missing_evidence": [],
            "framework_alignment": "unknown",
            "confidence_assessment": confidence,
            "requires_human_review": confidence < 0.7
        }
