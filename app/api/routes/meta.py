"""Rotas públicas de informação: raiz, saúde, termos, política de privacidade,
frameworks e chave de assinatura.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api import context as ctx
from app.core.attestation import AttestationError, key_set, public_key_info
from app.core.config import get_settings
from app.core.privacy import (
    PrivacyPolicyNotFound,
    current_policy,
    current_version,
    get_policy,
    list_versions as list_privacy_versions,
)
from app.core.terms import (
    TermsNotFound,
    current_terms,
    get_terms,
    list_versions as list_terms_versions,
)
from app.db.session import get_db
from app.domain.frameworks import framework_kind, list_frameworks

router = APIRouter()


@router.get("/")
def root():
    return {
        "project": "Valinor",
        "version": ctx.APP_VERSION,
        "status": "running",
        "docs": "/docs" if ctx.settings.expose_api_docs else None,
        "ui": "/ui/",
        "privacy_policy": "/privacy",
        "openai_enabled": ctx.settings.openai_enabled,
        "openrouter_enabled": ctx.settings.openrouter_enabled,
        "llm_enabled": ctx.settings.llm_enabled,
        # A interface só menciona pagamento quando a instância o habilita.
        "payments_enabled": get_settings().payments_enabled,
        "auth_required": ctx.settings.auth_required,
        "mission": (
            "Tirar conflitos da Justiça: acordo primeiro e, sem acordo, "
            "decisão da IA com raciocínio e cálculos visíveis, antes do "
            "processo ou em processo já ajuizado."
        ),
        "procedure_terms": {
            "version": current_terms().version,
            "principles": [
                "acordo antes de decisão",
                "transparência total: raciocínio, provas e cálculos visíveis",
                "adesão voluntária; arbitragem só por escolha das duas partes",
                "em consumo, arbitragem só por escolha do consumidor depois do conflito",
                "abstenção quando houver dúvida",
                "participação voluntária e regras iguais para as partes",
                "conhecimento e oportunidade de resposta a todo material",
                "tentativas de composição dependem de aceitação das partes",
                "decisão por IA fundamentada apenas no registro admitido",
                "auditoria automática independente, verificador determinístico e recurso automático",
                "o sistema pode se abster; não há julgador humano interno",
                "o gestor do procedimento é uma IA e não uma das partes",
            ],
        },
        "warnings": [
            warning
            for warning in [
                (
                    "OPENROUTER_API_KEY ausente: agentes usarão modo seguro inconclusivo."
                    if not ctx.settings.llm_enabled
                    else None
                ),
                (
                    "PLATFORM_SIGNING_SECRET usa valor de desenvolvimento."
                    if ctx.settings.using_development_signing_secret
                    else None
                ),
                (
                    "TRUSTED_PROXY_IPS vazio com rate limit ligado: atrás de um "
                    "proxy todas as requisições dividem a mesma chave."
                    if ctx.settings.proxy_awareness_missing
                    else None
                ),
                (
                    "DATA_CONTROLLER_NAME não declarado: a política de "
                    "privacidade fica sem o nome do controlador dos dados."
                    if not ctx.settings.privacy_contacts_declared
                    else None
                ),
            ]
            if warning
        ],
    }


@router.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {
        "status": "ok",
        "database": "ok",
        "openai_enabled": ctx.settings.openai_enabled,
        "openrouter_enabled": ctx.settings.openrouter_enabled,
        "llm_enabled": ctx.settings.llm_enabled,
        "email_configured": ctx.settings.email_enabled,
        "attestation_enabled": ctx.settings.attestation_enabled,
    }


@router.get("/terms")
def get_current_terms():
    """Texto vigente dos termos, com versão e hash. É este texto que a parte
    precisa ver antes de aceitar."""
    return {**current_terms().as_dict(), "available_versions": list_terms_versions()}


@router.get("/terms/{version}")
def get_terms_version(version: str):
    try:
        terms = get_terms(version)
    except TermsNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Versão de termos desconhecida: {version}",
        ) from exc
    return {
        **terms.as_dict(),
        "current": version == current_terms().version,
        "available_versions": list_terms_versions(),
    }


@router.get("/privacy")
def get_current_privacy_policy():
    """Política de privacidade vigente, com versão, hash e identificação do
    controlador. É o endereço que os termos do procedimento referenciam."""
    settings_now = get_settings()
    return {
        **current_policy(settings_now).as_dict(),
        "available_versions": list_privacy_versions(),
        "controller": {
            "name": settings_now.data_controller_name or None,
            "contact_email": settings_now.privacy_contact,
            "declared": settings_now.privacy_contacts_declared,
        },
        "retention": {
            "document_retention_days": settings_now.document_retention_days,
            "enabled": settings_now.document_retention_days > 0,
        },
        "processing": {
            "llm_enabled": settings_now.llm_enabled,
            "llm_providers": sorted(
                {
                    provider
                    for provider, enabled in (
                        ("openrouter", settings_now.openrouter_enabled),
                        ("openai", settings_now.openai_enabled),
                    )
                    if enabled
                }
            ),
            "nostr_anchor_enabled": settings_now.nostr_anchor_enabled,
        },
        "rights_endpoints": {
            "access_and_portability": "GET /account/data-export",
            "erasure": "POST /account/erasure",
        },
    }


@router.get("/privacy/{version}")
def get_privacy_policy_version(version: str):
    try:
        policy = get_policy(version, get_settings())
    except PrivacyPolicyNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Versão de política de privacidade desconhecida: {version}",
        ) from exc
    return {
        **policy.as_dict(),
        "current": version == current_version(),
        "available_versions": list_privacy_versions(),
    }


@router.get("/.well-known/valinor-signing-key")
def signing_key():
    """Conjunto de chaves de assinatura da plataforma.

    Os campos de topo descrevem a chave ativa (o formato que executores
    externos já consomem). `keys` traz o conjunto completo: a ativa e as
    aposentadas, que continuam válidas para verificar attestations emitidas
    antes de uma rotação.
    """
    settings_now = get_settings()
    if not settings_now.attestation_enabled:
        raise HTTPException(
            status_code=404,
            detail="A emissão de attestations não está habilitada nesta instância",
        )
    try:
        keys = key_set()
    except AttestationError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {**public_key_info(), **keys}


@router.get("/frameworks")
def get_frameworks():
    return [
        {**item.lock_summary(), "kind": framework_kind(item.id)}
        for item in list_frameworks()
    ]
