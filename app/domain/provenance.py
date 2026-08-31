"""Hashes canônicos da decisão e da proveniência.

A canonicalização é a mesma de `app.core.canonical` (JSON ordenado, SHA-256).
A versão é rotulada; o algoritmo existente não muda.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Optional, Type
from uuid import uuid4

from pydantic import BaseModel

from app.core.canonical import canonical_hash
from app.core.hashing import sha256_text
from app.domain.models import DecisionProvenance, DecisionVerificationResult

HASH_ALGORITHM = "sha256"
CANONICALIZATION_VERSION = "1.0"
ATTESTATION_SCHEMA_VERSION = "2.0"
RESPONSE_SCHEMA_VERSION = "1.0"


def _without_execution(payload: Mapping[str, Any]) -> Dict[str, Any]:
    data = dict(payload)
    data.pop("execution", None)
    data.pop("verification_summary", None)
    data.pop("provenance", None)
    return data


def decision_payload_hash(decision: Mapping[str, Any]) -> str:
    return canonical_hash(_without_execution(decision))


def decision_input_hash(payload: Mapping[str, Any]) -> str:
    return canonical_hash(payload)


def evidence_map_hash(
    documents: Any,
    chunks: Any,
    admitted_ids: Any,
) -> str:
    return canonical_hash(
        {
            "documents": documents,
            "chunks": [
                {
                    "id": chunk.get("id") if isinstance(chunk, Mapping) else chunk,
                    "document_id": chunk.get("document_id") if isinstance(chunk, Mapping) else None,
                    "sha256": chunk.get("sha256") if isinstance(chunk, Mapping) else None,
                }
                for chunk in (chunks or [])
            ],
            "admitted_document_ids": list(admitted_ids or []),
        }
    )


def document_set_hash(documents: Any) -> str:
    items = []
    for document in documents or []:
        if isinstance(document, Mapping):
            items.append(
                {
                    "id": document.get("id"),
                    "sha256": document.get("sha256"),
                    "admitted": document.get("admitted"),
                }
            )
        else:
            items.append(document)
    return canonical_hash(items)


def framework_hash(framework: Mapping[str, Any] | Any) -> str:
    if hasattr(framework, "hash") and callable(framework.hash):
        return framework.hash()
    if isinstance(framework, Mapping):
        return canonical_hash(framework)
    return sha256_text(str(framework))


def prompt_hash(prompt_ref: Mapping[str, Any] | str) -> str:
    if isinstance(prompt_ref, Mapping):
        return str(prompt_ref.get("sha256") or canonical_hash(prompt_ref))
    return sha256_text(str(prompt_ref))


def response_schema_hash(model: Type[BaseModel]) -> str:
    return canonical_hash(
        {
            "schema_version": RESPONSE_SCHEMA_VERSION,
            "schema": model.model_json_schema(),
        }
    )


def model_policy_hash(policy: Mapping[str, Any]) -> str:
    return canonical_hash(policy)


def verification_result_hash(result: Mapping[str, Any] | DecisionVerificationResult) -> str:
    payload = result.model_dump() if isinstance(result, DecisionVerificationResult) else dict(result)
    return canonical_hash(payload)


def build_provenance(
    *,
    decision: Mapping[str, Any],
    decision_input: Mapping[str, Any],
    documents: Any,
    chunks: Any,
    admitted_ids: Any,
    framework: Any,
    prompt_ref: Mapping[str, Any] | str,
    response_model: Type[BaseModel],
    model_policy: Mapping[str, Any],
    verification: Mapping[str, Any] | DecisionVerificationResult,
    manifest_hash: str,
    execution_id: Optional[str] = None,
    timestamp_utc: Optional[str] = None,
) -> Dict[str, Any]:
    provenance = DecisionProvenance(
        hash_algorithm=HASH_ALGORITHM,
        canonicalization_version=CANONICALIZATION_VERSION,
        attestation_schema_version=ATTESTATION_SCHEMA_VERSION,
        decision_payload_hash=decision_payload_hash(decision),
        decision_input_hash=decision_input_hash(decision_input),
        evidence_map_hash=evidence_map_hash(documents, chunks, admitted_ids),
        framework_hash=framework_hash(framework),
        prompt_hash=prompt_hash(prompt_ref),
        response_schema_hash=response_schema_hash(response_model),
        model_policy_hash=model_policy_hash(model_policy),
        verification_result_hash=verification_result_hash(verification),
        manifest_hash=manifest_hash,
        document_set_hash=document_set_hash(documents),
        timestamp_utc=timestamp_utc or datetime.now(timezone.utc).isoformat(),
        execution_id=execution_id or uuid4().hex,
    )
    return provenance.model_dump()
