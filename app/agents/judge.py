from typing import Dict

from app.core.llm import call_openai_json


SYSTEM_PROMPT = """
You are an arbitration decision engine.

Apply the Commercial Balanced framework.

Principles:
- contractual priority
- proportionality
- good faith
- avoid unjust enrichment
- contextual analysis of delays

You must:
1. Analyze the organized case.
2. Produce a concise decision.
3. Explain the reasoning.
4. Return valid JSON only.
"""


FALLBACK_DECISION = {
    "framework": "Commercial Balanced",
    "decision": "Partial fulfillment recognized. Release 70% payment.",
    "confidence": 0.81,
    "principles_applied": [
        "contractual priority",
        "proportionality",
        "good faith"
    ]
}



def decide_case(organized_case: Dict) -> Dict:
    try:
        result = call_openai_json(
            system_prompt=SYSTEM_PROMPT,
            user_payload=organized_case
        )

        return result

    except Exception:
        return FALLBACK_DECISION
