"""Versão Word do auto da decisão.

O documento é renderizado a partir do auto já emitido e assinado — nunca do
estado vivo do caso —, então duas cópias do mesmo auto dizem sempre a mesma
coisa. O rodapé de cada página e o bloco final trazem o `record_hash`, que
qualquer pessoa confere em `POST /decision-records/verify`.
"""

from io import BytesIO
from typing import Any, Dict, List

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor

from app.reports.decision_record import PARTY_LABELS, format_money
from app.reports.docx_generator import (
    GREEN,
    _add_callout,
    _add_key_value_table,
    _add_label,
    _configure_page,
    _configure_styles,
    _format_timestamp,
    _remove_paragraph_border,
)

RESPONSE_LABELS = {
    "pending": "resposta pendente",
    "answered": "respondido",
    "challenged": "contestado",
    "waived": "resposta dispensada",
}

FINDING_LABELS = {
    "established": "comprovado",
    "not_established": "não comprovado",
    "disputed": "controvertido",
    "insufficient": "prova insuficiente",
}


def _party_name(record: Dict[str, Any], role: str) -> str:
    party = (record.get("parties") or {}).get(role) or {}
    return party.get("name") or PARTY_LABELS.get(role, role)


def _bullets(document: Document, items: List[str]) -> None:
    for item in items:
        if item:
            document.add_paragraph(str(item), style="List Bullet")


def _qualification(document: Document, record: Dict[str, Any]) -> None:
    document.add_heading("I. Qualificação das partes", level=1)
    for role in ("claimant", "respondent"):
        party = (record.get("parties") or {}).get(role) or {}
        tax_id = party.get("tax_id") or {}
        document.add_heading(party.get("role_label") or PARTY_LABELS[role], level=2)
        consent = party.get("consent") or {}
        terms = (
            f"{consent.get('terms_version')} (SHA-256 {consent.get('terms_sha256')})"
            if consent.get("terms_version")
            else "Não registrado"
        )
        _add_key_value_table(
            document,
            (
                ("Nome", party.get("name") or ""),
                (
                    (tax_id.get("kind") or "CPF/CNPJ").upper(),
                    tax_id.get("formatted") or "Não informado pela parte",
                ),
                ("Adesão", _format_timestamp(consent.get("accepted_at"))),
                ("Termos aceitos", terms),
            ),
        )


def _object(document: Document, record: Dict[str, Any]) -> None:
    subject = record.get("object") or {}
    document.add_heading("II. Objeto da disputa", level=1)
    document.add_paragraph(subject.get("summary") or record.get("case_title") or "Não registrado.")
    for label, key in (
        ("Pedidos do cliente reclamante", "claimant_requests"),
        ("Argumentos da empresa reclamada", "respondent_arguments"),
        ("Fatos incontroversos", "undisputed_facts"),
        ("Fatos controvertidos", "disputed_facts"),
    ):
        if subject.get(key):
            document.add_heading(label, level=3)
            _bullets(document, subject[key])


def _procedure(document: Document, record: Dict[str, Any]) -> None:
    procedure = record.get("procedure") or {}
    document.add_heading("III. Relatório do procedimento", level=1)
    document.add_paragraph(
        "As partes aderiram voluntariamente ao procedimento. Cada material foi "
        "atribuído a quem o apresentou, disponibilizado à contraparte, teve a "
        "ciência registrada e foi respondido, contestado ou teve a resposta "
        "dispensada antes de ser admitido."
    )
    documents = procedure.get("documents") or []
    document.add_heading(f"Material apresentado ({len(documents)})", level=2)
    for item in documents:
        paragraph = document.add_paragraph(style="List Bullet")
        paragraph.add_run(f"{item.get('name')}").bold = True
        author = _party_name(record, item.get("submitted_by") or "")
        response = RESPONSE_LABELS.get(item.get("response_status") or "", item.get("response_status") or "")
        paragraph.add_run(
            f" — apresentado por {author}; {response}; "
            f"{'admitido' if item.get('admitted') else 'não admitido'}. "
            f"Finalidade: {item.get('purpose') or 'não informada'}. SHA-256 {item.get('sha256')}"
        )
    rounds = procedure.get("conciliation_rounds") or []
    document.add_heading(f"Tentativas de composição ({len(rounds)})", level=2)
    if not rounds:
        document.add_paragraph("Não houve rodada de composição.")
    for round_data in rounds:
        document.add_heading(f"Rodada {round_data.get('round_number')}", level=3)
        if round_data.get("neutral_summary"):
            document.add_paragraph(str(round_data["neutral_summary"]))
        if round_data.get("possible_terms"):
            document.add_paragraph("Proposta apresentada às partes:")
            _bullets(document, round_data["possible_terms"])
        for role, position in (round_data.get("positions") or {}).items():
            text = "renunciou a acrescentar algo" if position.get("waived") else position.get("text")
            document.add_paragraph(f"{_party_name(record, role)}: {text}")
        for role, accepted in (round_data.get("proposal_responses") or {}).items():
            document.add_paragraph(
                f"{_party_name(record, role)} {'aceitou' if accepted else 'recusou'} a proposta."
            )


def _agreement(document: Document, record: Dict[str, Any]) -> None:
    agreement = record.get("agreement") or {}
    document.add_heading("IV. Termo de acordo", level=1)
    document.add_paragraph(
        f"As partes aceitaram, de forma independente, a proposta da rodada "
        f"{agreement.get('round_number')}, nos seguintes termos:"
    )
    _bullets(document, agreement.get("terms") or [])
    accepted = agreement.get("accepted_at") or {}
    _add_key_value_table(
        document,
        (
            (f"Aceite — {_party_name(record, 'claimant')}", _format_timestamp(accepted.get("claimant"))),
            (f"Aceite — {_party_name(record, 'respondent')}", _format_timestamp(accepted.get("respondent"))),
            ("Hash da proposta", str(agreement.get("proposal_sha256") or "")),
        ),
    )


def _grounds(document: Document, record: Dict[str, Any]) -> None:
    decision = record.get("decision") or {}
    document.add_heading("IV. Fundamentação", level=1)
    findings = decision.get("material_findings") or []
    if not findings:
        document.add_paragraph("A decisão não registrou conclusões sobre fatos.")
    for finding in findings:
        document.add_heading(
            f"{finding.get('finding_id')}: {FINDING_LABELS.get(finding.get('status') or '', finding.get('status'))}",
            level=3,
        )
        document.add_paragraph(str(finding.get("proposition") or ""))
        if finding.get("reasoning"):
            document.add_paragraph(str(finding["reasoning"]))
        for label, key in (("Prova", "evidence"), ("Prova em sentido contrário", "counterevidence")):
            for ref in finding.get(key) or []:
                paragraph = document.add_paragraph(style="List Bullet")
                paragraph.add_run(f"{label} — {ref.get('document_name') or ref.get('document_id')}: ").bold = True
                paragraph.add_run(f"“{ref.get('quoted_text')}”")
    rules = decision.get("rule_applications") or []
    if rules:
        document.add_heading("Regras aplicadas", level=2)
        for rule in rules:
            paragraph = document.add_paragraph(style="List Bullet")
            paragraph.add_run(f"{rule.get('rule_id')} (v{rule.get('rule_version')}): ").bold = True
            paragraph.add_run(f"{rule.get('application_reasoning')} Conclusão: {rule.get('conclusion')}")
    if decision.get("limitations"):
        document.add_heading("Limitações declaradas", level=2)
        _bullets(document, decision["limitations"])


def _operative(document: Document, record: Dict[str, Any]) -> None:
    decision = record.get("decision") or {}
    outcome = record.get("outcome") or {}
    document.add_heading("V. Dispositivo", level=1)
    if outcome.get("kind") == "no_merit_decision":
        _add_callout(
            document,
            outcome.get("conclusion_label") or "Sem decisão de mérito",
            outcome.get("summary") or "",
            warning=True,
        )
        reasons = [item.get("label") for item in decision.get("abstention_reasons") or []]
        if reasons:
            document.add_paragraph("Motivos da abstenção:")
            _bullets(document, reasons)
        return
    _add_callout(document, decision.get("outcome_label") or "Decisão", decision.get("operative_text") or "")
    rows = [("Resultado", decision.get("outcome_label") or "")]
    if decision.get("partial_claimant_bps") is not None:
        rows.append(
            ("Proporção ao reclamante", f"{int(decision['partial_claimant_bps']) / 100:.2f}%")
        )
    remedy = decision.get("remedy_calculation") or {}
    if remedy:
        rows.append(("Valor apurado", format_money(remedy.get("result_minor_units"), remedy.get("currency"))))
        rows.append(("Fórmula", str(remedy.get("formula") or "")))
        for item in remedy.get("inputs") or []:
            rows.append((str(item.get("name")), format_money(item.get("value_minor_units"), item.get("currency"))))
    _add_key_value_table(document, rows)


def _review(document: Document, record: Dict[str, Any]) -> None:
    review = record.get("review")
    appeal = record.get("appeal")
    if not review and not appeal:
        return
    document.add_heading("VI. Auditoria e recurso", level=1)
    if review:
        verification = review.get("verification_valid")
        _add_key_value_table(
            document,
            (
                ("Auditoria automática", "aprovada" if review.get("approved") else "não aprovada"),
                (
                    "Verificação determinística",
                    "válida" if verification else ("inválida" if verification is False else "não executada"),
                ),
            ),
        )
        _bullets(document, review.get("issues") or [])
    if appeal:
        rows = [("Prazo de recurso", _format_timestamp(appeal.get("window_ends_utc")))]
        if appeal.get("filed"):
            rows.append(("Recurso apresentado por", _party_name(record, appeal.get("filed_by") or "")))
            rows.append(("Resultado do recurso", str(appeal.get("outcome") or "em análise")))
        _add_key_value_table(document, rows)
        if appeal.get("explanation"):
            document.add_paragraph(str(appeal["explanation"]))


def _integrity(document: Document, record: Dict[str, Any]) -> None:
    integrity = record.get("integrity") or {}
    document.add_heading("VII. Autenticidade", level=1)
    _add_key_value_table(
        document,
        (
            ("Auto nº", str(record.get("record_number"))),
            ("Emitido em", _format_timestamp(record.get("issued_at_utc"))),
            ("Hash do auto", str(record.get("record_hash") or "")),
            ("Assinatura", f"{record.get('signature_algorithm')} {record.get('key_id') or ''}".strip()),
            ("Substitui o auto", str(record.get("supersedes_record_hash") or "—")),
            ("Hash do manifesto", str(integrity.get("manifest_hash") or "")),
            ("Topo da trilha de auditoria", str(integrity.get("audit_chain_head") or "")),
            ("Eventos na trilha", str(integrity.get("audit_chain_length") or 0)),
        ),
    )
    document.add_paragraph(
        "Para conferir a autenticidade, envie o auto em JSON (GET "
        f"/cases/{record.get('case_id')}/decision-record) para POST "
        "/decision-records/verify. Um único caractere alterado invalida o hash."
    )


def build_decision_record_docx(record: Dict[str, Any]) -> BytesIO:
    document = Document()
    _configure_styles(document)
    _configure_page(document)
    section = document.sections[0]
    header = section.header.paragraphs[0]
    header.runs[0].text = "VALINOR  |  AUTO DA DECISÃO"
    footer = section.footer.paragraphs[0]
    footer.runs[0].text = f"Auto {str(record.get('record_hash') or '')[:16]}  |  página "

    _add_label(document, "Auto da decisão")
    title = document.add_heading(record.get("case_title") or "Procedimento Valinor", 0)
    _remove_paragraph_border(title)
    subtitle = document.add_paragraph(style="Subtitle")
    subtitle.add_run(
        f"{_party_name(record, 'claimant')} × {_party_name(record, 'respondent')}  |  "
        f"Caso {record.get('case_id')}  |  Auto nº {record.get('record_number')}"
    )
    outcome = record.get("outcome") or {}
    _add_callout(
        document,
        outcome.get("conclusion_label") or "Desfecho",
        outcome.get("summary") or "",
        warning=outcome.get("kind") == "no_merit_decision",
    )

    _qualification(document, record)
    _object(document, record)
    _procedure(document, record)
    if outcome.get("kind") == "agreement":
        _agreement(document, record)
    else:
        _grounds(document, record)
        _operative(document, record)
        _review(document, record)
    _integrity(document, record)

    document.add_heading("Natureza deste documento", level=1)
    _add_callout(document, "Decisão não vinculante", record.get("legal_notice") or "", warning=True)

    closing = document.add_paragraph()
    closing.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = closing.add_run(f"SHA-256 {record.get('record_hash')}")
    run.font.size = Pt(8)
    run.font.color.rgb = RGBColor.from_string(GREEN)

    output = BytesIO()
    document.save(output)
    output.seek(0)
    return output
