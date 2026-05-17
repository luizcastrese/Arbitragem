from datetime import datetime, timezone
from typing import Dict

from app.core.hashing import sha256_text



def build_audit_event(event_type: str, payload: Dict) -> Dict:
    timestamp = datetime.now(timezone.utc).isoformat()

    event = {
        "event_type": event_type,
        "timestamp_utc": timestamp,
        "payload": payload,
    }

    event["event_hash"] = sha256_text(str(event))
    return event
