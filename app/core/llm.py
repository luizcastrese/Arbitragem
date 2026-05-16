import json
import os
from typing import Any, Dict, List

from openai import OpenAI


client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))



def call_openai_json(system_prompt: str, user_payload: Dict[str, Any], model: str = "gpt-4.1-mini") -> Dict[str, Any]:
    """Call OpenAI and request a JSON response."""

    response = client.responses.create(
        model=model,
        input=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)}
        ],
        temperature=0,
        response_format={"type": "json_object"}
    )

    text = response.output_text
    return json.loads(text)



def generate_embedding(text: str, model: str = "text-embedding-3-small") -> List[float]:
    response = client.embeddings.create(
        model=model,
        input=text
    )

    return response.data[0].embedding
