"""Ponto de entrada da API Valinor.

Cria a aplicação FastAPI, aplica middleware, registra os routers de cada
domínio (autenticação, casos, documentos, manifesto, fluxo de IA, attestation
e relatórios) e monta a interface estática quando disponível.
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.deps import API_VERSION, settings
from app.api.routers import (
    attestation,
    auth,
    cases,
    documents,
    manifest,
    participants,
    reports,
    system,
    workflow,
)
from app.db.init_db import init_db


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Valinor",
    version=API_VERSION,
    description="Fluxo auditável de decisão de disputas documentais por IA.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(system.router)
app.include_router(auth.router)
app.include_router(cases.router)
app.include_router(participants.router)
app.include_router(documents.router)
app.include_router(manifest.router)
app.include_router(workflow.router)
app.include_router(attestation.router)
app.include_router(reports.router)


frontend_dist = Path(__file__).resolve().parents[1] / "frontend" / "dist"
if frontend_dist.exists():
    app.mount("/ui", StaticFiles(directory=frontend_dist, html=True), name="ui")
