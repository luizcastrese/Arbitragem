"""Verificador determinístico da decisão. Não chama IA."""

from __future__ import annotations

import ast
import operator
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from pydantic import ValidationError

from app.core.hashing import sha256_text
from app.domain.enums import EXECUTABLE_OUTCOMES
from app.domain.frameworks import Framework
from app.domain.legacy import normalize_legacy_decision
from app.domain.models import (
    DecisionOutput,
    DecisionVerificationResult,
    EvidenceReference,
    VerificationIssue,
)

VERIFIER_VERSION = "1.0.0"

_ALLOWED_CALC_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
}


def _issue(
    code: str,
    message: str,
    *,
    severity: str = "error",
    finding_id: Optional[str] = None,
    document_id: Optional[str] = None,
    chunk_id: Optional[str] = None,
) -> VerificationIssue:
    return VerificationIssue(
        code=code,
        severity=severity,
        message=message,
        finding_id=finding_id,
        document_id=document_id,
        chunk_id=chunk_id,
    )


def _index_documents(documents: Sequence[Mapping[str, Any]]) -> Dict[str, Mapping[str, Any]]:
    return {str(item.get("id")): item for item in documents if item.get("id")}


def _index_chunks(chunks: Sequence[Mapping[str, Any]]) -> Dict[str, Mapping[str, Any]]:
    return {str(item.get("id")): item for item in chunks if item.get("id")}


def _admitted_ids(admitted_documents: Iterable[Any]) -> Set[str]:
    ids: Set[str] = set()
    for item in admitted_documents:
        if isinstance(item, str):
            ids.add(item)
        elif isinstance(item, Mapping) and item.get("id"):
            ids.add(str(item["id"]))
            if item.get("admitted") is False:
                ids.discard(str(item["id"]))
    return ids


def _safe_eval_formula(formula: str, names: Mapping[str, int]) -> Optional[int]:
    """Avalia fórmula aritmética simples. Recusa nomes e nós inesperados."""
    try:
        tree = ast.parse(formula, mode="eval")
    except SyntaxError:
        return None

    def _eval(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return float(node.value)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = _eval(node.operand)
            return value if isinstance(node.op, ast.UAdd) else -value
        if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_CALC_BINOPS:
            left = _eval(node.left)
            right = _eval(node.right)
            return _ALLOWED_CALC_BINOPS[type(node.op)](left, right)
        if isinstance(node, ast.Name):
            if node.id not in names:
                raise ValueError("unknown_name")
            return float(names[node.id])
        raise ValueError("unsupported")

    try:
        result = _eval(tree)
    except (ValueError, ZeroDivisionError, TypeError, OverflowError):
        return None
    if isinstance(result, bool) or not isinstance(result, (int, float)):
        return None
    rounded = int(round(result))
    return rounded


def verify_evidence_reference(
    ref: EvidenceReference,
    *,
    manifest_documents: Mapping[str, Mapping[str, Any]],
    manifest_chunks: Mapping[str, Mapping[str, Any]],
    admitted_ids: Set[str],
    finding_id: Optional[str] = None,
) -> List[VerificationIssue]:
    errors: List[VerificationIssue] = []
    document = manifest_documents.get(ref.document_id)
    if document is None:
        errors.append(
            _issue(
                "unknown_document",
                "Documento citado não está no manifesto travado.",
                finding_id=finding_id,
                document_id=ref.document_id,
                chunk_id=ref.chunk_id,
            )
        )
        return errors
    if document.get("sha256") != ref.document_sha256:
        errors.append(
            _issue(
                "document_hash_mismatch",
                "Hash do documento não confere com o manifesto.",
                finding_id=finding_id,
                document_id=ref.document_id,
            )
        )
    if ref.document_id not in admitted_ids:
        errors.append(
            _issue(
                "document_not_admitted",
                "Documento citado não foi admitido.",
                finding_id=finding_id,
                document_id=ref.document_id,
            )
        )
    if document.get("admitted") is False:
        errors.append(
            _issue(
                "document_not_admitted",
                "Documento citado consta como não admitido.",
                finding_id=finding_id,
                document_id=ref.document_id,
            )
        )

    chunk = manifest_chunks.get(ref.chunk_id)
    if chunk is None:
        errors.append(
            _issue(
                "unknown_chunk",
                "Trecho citado não está no manifesto travado.",
                finding_id=finding_id,
                document_id=ref.document_id,
                chunk_id=ref.chunk_id,
            )
        )
        return errors
    if chunk.get("text_integrity_failed"):
        errors.append(
            _issue(
                "chunk_hash_mismatch",
                "O texto em runtime não confere com o hash do chunk travado.",
                finding_id=finding_id,
                chunk_id=ref.chunk_id,
            )
        )
        return errors
    if chunk.get("sha256") != ref.chunk_sha256:
        errors.append(
            _issue(
                "chunk_hash_mismatch",
                "Hash do trecho não confere com o manifesto.",
                finding_id=finding_id,
                chunk_id=ref.chunk_id,
            )
        )
    if chunk.get("document_id") != ref.document_id:
        errors.append(
            _issue(
                "chunk_document_mismatch",
                "Trecho não pertence ao documento citado.",
                finding_id=finding_id,
                document_id=ref.document_id,
                chunk_id=ref.chunk_id,
            )
        )

    chunk_text = str(chunk.get("text") or "")
    if ref.quoted_text not in chunk_text:
        errors.append(
            _issue(
                "quoted_text_missing",
                "Trecho citado não existe no chunk do manifesto.",
                finding_id=finding_id,
                document_id=ref.document_id,
                chunk_id=ref.chunk_id,
            )
        )
    if sha256_text(ref.quoted_text) != ref.quoted_text_sha256:
        errors.append(
            _issue(
                "quoted_text_hash_mismatch",
                "Hash do trecho citado não confere.",
                finding_id=finding_id,
                chunk_id=ref.chunk_id,
            )
        )
    if ref.start_offset is not None and ref.end_offset is not None:
        extracted = chunk_text[ref.start_offset : ref.end_offset]
        if extracted != ref.quoted_text:
            errors.append(
                _issue(
                    "quoted_text_offset_mismatch",
                    "Offsets não reproduzem o trecho citado.",
                    finding_id=finding_id,
                    chunk_id=ref.chunk_id,
                )
            )
    return errors


def _collect_refs(decision: DecisionOutput) -> List[Tuple[Optional[str], EvidenceReference]]:
    refs: List[Tuple[Optional[str], EvidenceReference]] = []
    for finding in decision.material_findings:
        for ref in finding.evidence:
            refs.append((finding.finding_id, ref))
        for ref in finding.counterevidence:
            refs.append((finding.finding_id, ref))
    if decision.remedy_calculation:
        for calc_input in decision.remedy_calculation.inputs:
            for ref in calc_input.evidence_refs:
                refs.append((None, ref))
    return refs


def verify_decision(
    decision: Mapping[str, Any] | DecisionOutput,
    locked_manifest: Mapping[str, Any] | None,
    admitted_documents: Sequence[Any] | None,
    chunks: Sequence[Mapping[str, Any]],
    framework: Framework,
) -> DecisionVerificationResult:
    errors: List[VerificationIssue] = []
    warnings: List[VerificationIssue] = []
    verified_evidence = 0
    verified_findings = 0
    verified_rules = 0
    verified_calcs = 0

    manifest = locked_manifest or {}
    manifest_documents = _index_documents(manifest.get("documents") or [])
    manifest_chunks = _index_chunks(manifest.get("chunks") or [])
    # Texto dos chunks pode não estar no manifesto; usa o índice runtime.
    runtime_chunks = _index_chunks(chunks)
    merged_chunks: Dict[str, Dict[str, Any]] = {}
    for chunk_id, item in manifest_chunks.items():
        merged = dict(item)
        runtime = runtime_chunks.get(chunk_id) or {}
        runtime_text = runtime.get("text")
        if runtime_text and not merged.get("text"):
            actual = sha256_text(str(runtime_text))
            locked_hash = merged.get("sha256") or runtime.get("sha256")
            if locked_hash and actual != locked_hash:
                merged["text_integrity_failed"] = True
            else:
                merged["text"] = runtime_text
        merged_chunks[chunk_id] = merged
    for chunk_id, item in runtime_chunks.items():
        merged_chunks.setdefault(chunk_id, dict(item))

    explicit_admission = admitted_documents is not None
    if explicit_admission:
        admitted_ids = _admitted_ids(admitted_documents)
    else:
        admitted_ids = set(
            (manifest.get("contradictory") or {}).get("admitted_document_ids") or []
        )
        for document in manifest_documents.values():
            if document.get("admitted"):
                admitted_ids.add(str(document["id"]))

    raw = decision.model_dump() if isinstance(decision, DecisionOutput) else dict(decision)
    try:
        parsed = decision if isinstance(decision, DecisionOutput) else DecisionOutput.model_validate(
            {
                **normalize_legacy_decision(raw),
                "framework_id": raw.get("framework_id") or framework.id,
                "framework_version": raw.get("framework_version") or framework.version,
            }
        )
    except ValidationError as exc:
        return DecisionVerificationResult(
            valid=False,
            errors=[
                _issue("invalid_schema", "A decisão não satisfaz o schema estruturado.")
            ],
            warnings=[],
            verifier_version=VERIFIER_VERSION,
        )

    if parsed.framework_id != framework.id:
        errors.append(
            _issue(
                "framework_mismatch",
                "framework_id da decisão diverge do framework fixado no manifesto.",
            )
        )
    if parsed.framework_version != framework.version:
        warnings.append(
            _issue(
                "framework_version_mismatch",
                "Versão do framework na decisão diverge da versão fixada.",
                severity="warning",
            )
        )

    finding_ids = [finding.finding_id for finding in parsed.material_findings]
    if len(finding_ids) != len(set(finding_ids)):
        errors.append(_issue("duplicate_finding_id", "Há findings com o mesmo finding_id."))

    findings_by_id = {finding.finding_id: finding for finding in parsed.material_findings}

    if parsed.outcome in EXECUTABLE_OUTCOMES and not parsed.material_findings:
        errors.append(
            _issue(
                "missing_material_findings",
                "Conclusão de mérito exige ao menos um MaterialFinding.",
            )
        )
    if parsed.outcome in EXECUTABLE_OUTCOMES and not parsed.rule_applications:
        errors.append(
            _issue(
                "missing_rule_applications",
                "Conclusão de mérito exige ao menos uma RuleApplication.",
            )
        )

    for finding in parsed.material_findings:
        if finding.status == "established" and not finding.evidence:
            errors.append(
                _issue(
                    "established_without_evidence",
                    "Finding estabelecido sem evidência válida.",
                    finding_id=finding.finding_id,
                )
            )
            continue
        finding_ok = True
        for ref in list(finding.evidence) + list(finding.counterevidence):
            ref_errors = verify_evidence_reference(
                ref,
                manifest_documents=manifest_documents,
                manifest_chunks=merged_chunks,
                admitted_ids=admitted_ids,
                finding_id=finding.finding_id,
            )
            if ref_errors:
                finding_ok = False
                errors.extend(ref_errors)
            else:
                verified_evidence += 1
        if finding.status == "established" and finding_ok and finding.evidence:
            verified_findings += 1

    used_finding_ids: Set[str] = set()
    for application in parsed.rule_applications:
        rule = framework.rule_by_id(application.rule_id)
        if rule is None:
            errors.append(
                _issue(
                    "unknown_rule",
                    "Regra aplicada não existe no framework fixado.",
                )
            )
            continue
        if application.rule_version != rule.version:
            warnings.append(
                _issue(
                    "rule_version_mismatch",
                    "Versão da regra aplicada diverge da versão do framework.",
                    severity="warning",
                )
            )
        if parsed.outcome in EXECUTABLE_OUTCOMES and rule.allowed_outcomes and parsed.outcome not in rule.allowed_outcomes:
            errors.append(
                _issue(
                    "outcome_not_allowed_by_rule",
                    "Outcome incompatível com a regra aplicada.",
                )
            )
        orphan = [item for item in application.findings_used if item not in findings_by_id]
        if orphan:
            errors.append(
                _issue(
                    "orphan_finding_reference",
                    "RuleApplication referencia finding inexistente.",
                )
            )
        used_finding_ids.update(application.findings_used)
        verified_rules += 1

    if parsed.outcome in EXECUTABLE_OUTCOMES:
        unused = [item for item in finding_ids if item not in used_finding_ids]
        # Findings existem para fundamentar; não é erro ter finding não usado,
        # mas a conclusão precisa apontar para ao menos um.
        if parsed.rule_applications and not used_finding_ids and finding_ids:
            errors.append(
                _issue(
                    "conclusion_without_finding",
                    "As regras aplicadas não apontam para nenhum MaterialFinding.",
                )
            )

    if parsed.remedy_calculation:
        calc = parsed.remedy_calculation
        if not calc.inputs:
            errors.append(_issue("calculation_without_inputs", "Cálculo sem insumos."))
        currencies = {item.currency for item in calc.inputs}
        currencies.add(calc.currency)
        if len(currencies) > 1:
            errors.append(_issue("currency_mismatch", "Moedas divergentes no cálculo."))
        for calc_input in calc.inputs:
            if not calc_input.evidence_refs:
                errors.append(
                    _issue(
                        "monetary_value_without_evidence",
                        "Valor monetário sem origem documental.",
                    )
                )
            for ref in calc_input.evidence_refs:
                ref_errors = verify_evidence_reference(
                    ref,
                    manifest_documents=manifest_documents,
                    manifest_chunks=merged_chunks,
                    admitted_ids=admitted_ids,
                )
                if ref_errors:
                    errors.extend(ref_errors)
                else:
                    verified_evidence += 1
        names = {item.name: item.value_minor_units for item in calc.inputs}
        evaluated = _safe_eval_formula(calc.formula, names)
        if evaluated is None:
            errors.append(
                _issue(
                    "calculation_formula_invalid",
                    "Fórmula do cálculo não é determinística ou referencia insumos ausentes.",
                )
            )
        elif evaluated != calc.result_minor_units:
            errors.append(
                _issue(
                    "calculation_result_mismatch",
                    "Resultado do cálculo não confere com a fórmula e os insumos.",
                )
            )
        else:
            verified_calcs += 1

        if parsed.outcome == "inconclusive":
            errors.append(
                _issue(
                    "remedy_on_inconclusive",
                    "Decisão inconclusiva não pode carregar cálculo executável.",
                )
            )
        if parsed.outcome == "respondent" and calc.result_minor_units > 0:
            warnings.append(
                _issue(
                    "remedy_on_respondent",
                    "Outcome favorável à reclamada com valor positivo ao reclamante.",
                    severity="warning",
                )
            )
        if parsed.outcome == "partial":
            if parsed.partial_claimant_bps is None:
                errors.append(
                    _issue(
                        "partial_without_bps",
                        "Resultado parcial sem basis points.",
                    )
                )
            elif parsed.partial_claimant_bps in {0, 10000}:
                errors.append(
                    _issue(
                        "partial_inconsistent_bps",
                        "Resultado parcial com basis points equivalente a vitória total.",
                    )
                )

    if parsed.outcome == "partial" and parsed.partial_claimant_bps is None:
        errors.append(_issue("partial_without_bps", "Resultado parcial sem basis points."))

    if parsed.outcome in EXECUTABLE_OUTCOMES and parsed.abstention_reasons:
        errors.append(
            _issue(
                "merit_with_abstention",
                "Outcome de mérito incompatível com razões de abstenção.",
            )
        )

    # Material posterior ao lock: chunk/documento fora do manifesto.
    for _finding_id, ref in _collect_refs(parsed):
        if ref.document_id not in manifest_documents:
            # já coberto por unknown_document
            continue
        if ref.chunk_id not in manifest_chunks and ref.chunk_id in runtime_chunks:
            errors.append(
                _issue(
                    "post_lock_material",
                    "Referência a material que não estava no manifesto travado.",
                    document_id=ref.document_id,
                    chunk_id=ref.chunk_id,
                )
            )

    valid = not any(item.severity == "error" for item in errors)
    return DecisionVerificationResult(
        valid=valid,
        errors=errors,
        warnings=warnings,
        verified_evidence_count=verified_evidence,
        verified_findings_count=verified_findings,
        verified_rule_applications_count=verified_rules,
        verified_calculations_count=verified_calcs,
        verifier_version=VERIFIER_VERSION,
    )
