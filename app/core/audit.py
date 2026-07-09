from datetime import datetime, timezone
from typing import Dict, List, Tuple

from app.core.canonical import canonical_hash



def build_audit_event(
    event_type: str,
    payload: Dict,
    previous_hash: str = "",
) -> Dict:
    timestamp = datetime.now(timezone.utc).isoformat()

    event = {
        "event_type": event_type,
        "timestamp_utc": timestamp,
        "payload": payload,
        "previous_hash": previous_hash,
    }

    event["event_hash"] = canonical_hash(event)
    return event


def verify_audit_chain(events: List[Dict]) -> Tuple[bool, List[str]]:
    errors = []
    previous_hash = ""

    for index, event in enumerate(events):
        expected_base = {
            "event_type": event.get("event_type"),
            "timestamp_utc": event.get("timestamp_utc"),
            "payload": event.get("payload", {}),
            "previous_hash": previous_hash,
        }
        expected_hash = canonical_hash(expected_base)

        if event.get("previous_hash", "") != previous_hash:
            errors.append(f"Event {index + 1} has an invalid previous_hash")
        if event.get("event_hash") != expected_hash:
            errors.append(f"Event {index + 1} has an invalid event_hash")

        previous_hash = event.get("event_hash", "")

    return not errors, errors
