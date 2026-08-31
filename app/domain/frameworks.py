"""Frameworks versionados do procedimento.

Não são legislação. São conjuntos contratuais e computacionais fixados no
manifesto: regras com IDs estáveis, exclusões e condições de abstenção.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from app.core.canonical import canonical_hash


@dataclass(frozen=True)
class FrameworkRule:
    id: str
    version: str
    title: str
    description: str
    required_findings: Sequence[str] = field(default_factory=tuple)
    allowed_outcomes: Sequence[str] = field(default_factory=tuple)
    calculation_policy: str = ""
    exclusions: Sequence[str] = field(default_factory=tuple)
    abstention_conditions: Sequence[str] = field(default_factory=tuple)

    def as_dict(self) -> Dict:
        return {
            "id": self.id,
            "version": self.version,
            "title": self.title,
            "description": self.description,
            "required_findings": list(self.required_findings),
            "allowed_outcomes": list(self.allowed_outcomes),
            "calculation_policy": self.calculation_policy,
            "exclusions": list(self.exclusions),
            "abstention_conditions": list(self.abstention_conditions),
        }


@dataclass(frozen=True)
class Framework:
    id: str
    version: str
    name: str
    description: str
    in_scope: Sequence[str]
    exclusions: Sequence[str]
    rules: Sequence[FrameworkRule]
    principles: Sequence[str] = field(default_factory=tuple)
    disclaimer: str = (
        "Este framework é um conjunto contratual e computacional do "
        "procedimento Valinor. Não constitui legislação, sentença judicial "
        "nem sentença arbitral."
    )
    case_value_limit_minor_units: Optional[int] = None
    case_value_currency: str = "BRL"

    def rule_by_id(self, rule_id: str) -> Optional[FrameworkRule]:
        for rule in self.rules:
            if rule.id == rule_id:
                return rule
        return None

    def rule_ids(self) -> List[str]:
        return [rule.id for rule in self.rules]

    def hash(self) -> str:
        return canonical_hash(self.as_dict())

    def as_dict(self) -> Dict:
        return {
            "id": self.id,
            "version": self.version,
            "name": self.name,
            "description": self.description,
            "in_scope": list(self.in_scope),
            "exclusions": list(self.exclusions),
            "principles": list(self.principles),
            "disclaimer": self.disclaimer,
            "case_value_limit_minor_units": self.case_value_limit_minor_units,
            "case_value_currency": self.case_value_currency,
            "rules": [rule.as_dict() for rule in self.rules],
        }

    def lock_summary(self) -> Dict:
        """Recorte fixado no manifesto: identidade, hash e IDs das regras."""
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "hash": self.hash(),
            "principles": list(self.principles),
            "exclusions": list(self.exclusions),
            "rule_ids": self.rule_ids(),
            "disclaimer": self.disclaimer,
            "case_value_limit_minor_units": self.case_value_limit_minor_units,
            "case_value_currency": self.case_value_currency,
        }


def _commercial_balanced() -> Framework:
    prefix = "commercial_balanced_v1"
    rules = (
        FrameworkRule(
            id=f"{prefix}:contract:priority",
            version="1.0.0",
            title="Prioridade contratual",
            description="Obrigações expressas no contrato prevalecem sobre alegações posteriores sem lastro.",
            required_findings=("contract_terms",),
            allowed_outcomes=("claimant", "respondent", "partial", "inconclusive"),
            calculation_policy="none",
            abstention_conditions=("insufficient_evidence",),
        ),
        FrameworkRule(
            id=f"{prefix}:delivery:partial",
            version="1.0.0",
            title="Cumprimento parcial",
            description="Cumprimento parcial pode justificar pagamento proporcional quando a fração for documentada.",
            required_findings=("delivery_extent",),
            allowed_outcomes=("partial", "inconclusive"),
            calculation_policy="proportional_to_established_fraction",
            abstention_conditions=("unsupported_calculation", "insufficient_evidence"),
        ),
        FrameworkRule(
            id=f"{prefix}:good_faith",
            version="1.0.0",
            title="Boa-fé",
            description="A boa-fé mitiga penalidades quando demonstrada no registro admitido.",
            required_findings=(),
            allowed_outcomes=("claimant", "respondent", "partial", "inconclusive"),
            calculation_policy="none",
        ),
        FrameworkRule(
            id=f"{prefix}:unjust_enrichment",
            version="1.0.0",
            title="Vedação ao enriquecimento injusto",
            description="Nenhuma parte deve reter valor sem contraprestação correspondente no registro.",
            required_findings=("payment_status",),
            allowed_outcomes=("claimant", "respondent", "partial", "inconclusive"),
            calculation_policy="net_of_established_consideration",
        ),
        FrameworkRule(
            id=f"{prefix}:delay:contextual",
            version="1.0.0",
            title="Atraso contextual",
            description="Atrasos devem ser analisados à luz de dependências e comunicações admitidas.",
            required_findings=("delay_attribution",),
            allowed_outcomes=("claimant", "respondent", "partial", "inconclusive"),
            calculation_policy="none",
            abstention_conditions=("contradictory_material_evidence",),
        ),
    )
    return Framework(
        id="commercial_balanced_v1",
        version="1.0.0",
        name="Comercial Equilibrado",
        description="Framework genérico de equilíbrio comercial para disputas documentais.",
        in_scope=(
            "obrigações contratuais documentadas",
            "entrega e pagamento em relações comerciais",
            "atraso e cumprimento parcial",
        ),
        exclusions=(
            "dano corporal",
            "saúde",
            "trabalho",
            "família",
            "fraude relevante",
            "atividade criminal",
            "direito indisponível",
        ),
        principles=(
            "prioridade contratual",
            "proporcionalidade",
            "boa-fé",
            "vedação ao enriquecimento injusto",
            "análise contextual de atrasos",
            "cumprimento parcial pode justificar pagamento proporcional",
            "prioridade à solução consensual quando houver convergência de interesses",
        ),
        rules=rules,
    )


def _digital_services_b2b() -> Framework:
    prefix = "digital_services_b2b_v1"
    rules = (
        FrameworkRule(
            id=f"{prefix}:scope:original",
            version="1.0.0",
            title="Escopo original",
            description="O escopo é o descrito no contrato ou proposta admitida, sem ampliar pedidos não documentados.",
            required_findings=("original_scope",),
            allowed_outcomes=("claimant", "respondent", "partial", "inconclusive"),
            calculation_policy="none",
            abstention_conditions=("insufficient_evidence", "out_of_scope"),
        ),
        FrameworkRule(
            id=f"{prefix}:scope:change_order",
            version="1.0.0",
            title="Alteração de escopo",
            description="Alteração de escopo só produz efeito se houver ordem de mudança ou aceite documentado.",
            required_findings=("scope_change",),
            allowed_outcomes=("claimant", "respondent", "partial", "inconclusive"),
            calculation_policy="add_or_subtract_documented_change",
            abstention_conditions=("insufficient_evidence",),
        ),
        FrameworkRule(
            id=f"{prefix}:delivery:full",
            version="1.0.0",
            title="Entrega integral",
            description="Entrega integral do escopo documentado autoriza o pagamento contratual correspondente.",
            required_findings=("delivery_complete",),
            allowed_outcomes=("respondent", "inconclusive"),
            calculation_policy="contract_price_if_established",
        ),
        FrameworkRule(
            id=f"{prefix}:delivery:partial",
            version="1.0.0",
            title="Entrega parcial",
            description="Entrega parcial documentada autoriza pagamento proporcional, nunca um percentual inventado.",
            required_findings=("delivery_extent",),
            allowed_outcomes=("partial", "inconclusive"),
            calculation_policy="proportional_to_established_fraction",
            abstention_conditions=("unsupported_calculation", "insufficient_evidence"),
        ),
        FrameworkRule(
            id=f"{prefix}:acceptance:express",
            version="1.0.0",
            title="Aceite expresso",
            description="Aceite expresso documentado confirma a entrega na extensão aceita.",
            required_findings=("express_acceptance",),
            allowed_outcomes=("claimant", "respondent", "partial", "inconclusive"),
            calculation_policy="none",
        ),
        FrameworkRule(
            id=f"{prefix}:acceptance:silence_not_consent",
            version="1.0.0",
            title="Silêncio não é aceite",
            description="O silêncio da contratante não equivale a aceite, salvo cláusula admitida em sentido contrário.",
            required_findings=(),
            allowed_outcomes=("claimant", "respondent", "partial", "inconclusive"),
            calculation_policy="none",
        ),
        FrameworkRule(
            id=f"{prefix}:delay:provider",
            version="1.0.0",
            title="Atraso imputável ao prestador",
            description="Atraso imputável ao prestador, com prazo documentado, pode justificar correção, redução ou rescisão proporcional.",
            required_findings=("delay_by_provider",),
            allowed_outcomes=("claimant", "partial", "inconclusive"),
            calculation_policy="none",
            abstention_conditions=("contradictory_material_evidence",),
        ),
        FrameworkRule(
            id=f"{prefix}:delay:client_dependency",
            version="1.0.0",
            title="Atraso por dependência do cliente",
            description="Atraso causado por dependência não satisfeita da contratante não se imputa ao prestador.",
            required_findings=("client_dependency",),
            allowed_outcomes=("respondent", "partial", "inconclusive"),
            calculation_policy="none",
        ),
        FrameworkRule(
            id=f"{prefix}:payment:proportional",
            version="1.0.0",
            title="Pagamento proporcional",
            description="Valores devidos seguem a fração estabelecida da entrega, em minor units e moeda do contrato.",
            required_findings=("delivery_extent", "contract_price"),
            allowed_outcomes=("partial", "claimant", "respondent", "inconclusive"),
            calculation_policy="result = contract_price_minor_units * established_bps / 10000",
            abstention_conditions=("unsupported_calculation",),
        ),
        FrameworkRule(
            id=f"{prefix}:termination:refund",
            version="1.0.0",
            title="Rescisão e reembolso",
            description="Rescisão documentada pode gerar reembolso do valor pago não coberto por entrega estabelecida.",
            required_findings=("termination", "payments_made"),
            allowed_outcomes=("claimant", "partial", "inconclusive"),
            calculation_policy="refund = payments_made_minor_units - value_of_established_delivery",
        ),
    )
    return Framework(
        id="digital_services_b2b_v1",
        version="1.0.0",
        name="Serviços digitais B2B",
        description=(
            "Framework contratual do procedimento para disputas documentais de "
            "serviços digitais entre empresas: sites, software simples sob "
            "encomenda, design, marketing, conteúdo, audiovisual, consultoria "
            "operacional e automação não crítica."
        ),
        in_scope=(
            "desenvolvimento de sites",
            "software simples sob encomenda",
            "design",
            "marketing",
            "gestão de conteúdo",
            "produção audiovisual",
            "consultoria operacional",
            "automação não crítica",
            "entrega, atraso, pagamento, reembolso, alteração de escopo, aceite, rescisão, correção e pagamento proporcional",
        ),
        exclusions=(
            "dano corporal",
            "saúde",
            "trabalho",
            "família",
            "fraude relevante",
            "atividade criminal",
            "incapacidade",
            "discriminação",
            "assédio",
            "segurança crítica",
            "vazamento de dados",
            "propriedade intelectual complexa",
            "perícia técnica indispensável",
            "lucros cessantes elevados",
            "urgência",
            "direito indisponível",
            "valor acima do limite configurado",
        ),
        principles=(
            "escopo documental prevalece",
            "silêncio não é aceite",
            "entrega parcial autoriza apenas pagamento proporcional lastreado",
            "atraso depende de imputação documentada",
            "o sistema pode se abster; nunca é obrigado a declarar um vencedor",
        ),
        rules=rules,
        case_value_limit_minor_units=5_000_000_00,
        case_value_currency="BRL",
    )


_REGISTRY: Dict[str, Framework] = {}


def register_framework(framework: Framework) -> Framework:
    _REGISTRY[framework.id] = framework
    return framework


register_framework(_commercial_balanced())
register_framework(_digital_services_b2b())

DEFAULT_FRAMEWORK_ID = "digital_services_b2b_v1"


def get_framework(framework_id: str) -> Framework:
    try:
        return _REGISTRY[framework_id]
    except KeyError as exc:
        raise LookupError(f"framework desconhecido: {framework_id}") from exc


def list_frameworks() -> List[Framework]:
    return [item for _, item in sorted(_REGISTRY.items())]


def resolve_framework(framework_id: Optional[str] = None) -> Framework:
    return get_framework(framework_id or DEFAULT_FRAMEWORK_ID)
