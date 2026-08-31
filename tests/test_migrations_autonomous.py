"""Upgrade Alembic sobre banco vazio e leitura de colunas novas."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect


def test_alembic_head_is_the_autonomous_revision():
    cfg = Config(str(Path("alembic.ini")))
    script = ScriptDirectory.from_config(cfg)
    assert script.get_current_head() == "f4b8d2a7c1e9"


def test_alembic_upgrade_empty_sqlite(tmp_path, monkeypatch):
    from alembic import command
    from app.core.config import get_settings

    db_path = tmp_path / "mig.db"
    url = f"sqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    try:
        cfg = Config(str(Path("alembic.ini")))
        command.upgrade(cfg, "head")
        engine = create_engine(url)
        tables = set(inspect(engine).get_table_names())
        assert "decision_runs" in tables
        assert "automatic_appeals" in tables
        columns = {item["name"] for item in inspect(engine).get_columns("cases")}
        assert "procedure_conclusion" in columns
        member_columns = {
            item["name"] for item in inspect(engine).get_columns("case_members")
        }
        assert "party" in member_columns
        command.downgrade(cfg, "b7c4e91a5d20")
        engine.dispose()
        engine = create_engine(url)
        tables = set(inspect(engine).get_table_names())
        assert "decision_runs" not in tables
        command.upgrade(cfg, "head")
    finally:
        get_settings.cache_clear()


def test_alembic_upgrade_preserves_legacy_case(tmp_path, monkeypatch):
    from datetime import datetime, timezone

    from alembic import command
    from sqlalchemy import text

    from app.core.config import get_settings

    db_path = tmp_path / "legacy.db"
    url = f"sqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)
    get_settings.cache_clear()
    try:
        cfg = Config(str(Path("alembic.ini")))
        command.upgrade(cfg, "b7c4e91a5d20")
        engine = create_engine(url)
        now = datetime.now(timezone.utc).isoformat()
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO cases (id, title, claimant, respondent, status, "
                    "claimant_consent, respondent_consent, manifest_locked, "
                    "decision_json, created_at, updated_at) "
                    "VALUES (:id, :title, :claimant, :respondent, :status, "
                    "0, 0, 0, :decision, :created_at, :updated_at)"
                ),
                {
                    "id": "legacy-case",
                    "title": "caso legado",
                    "claimant": "Alfa",
                    "respondent": "Beta",
                    "status": "reviewed",
                    "decision": '{"outcome":"inconclusive","requires_human_review":true}',
                    "created_at": now,
                    "updated_at": now,
                },
            )
        engine.dispose()
        command.upgrade(cfg, "head")
        engine = create_engine(url)
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT decision_json, procedure_conclusion FROM cases WHERE id = 'legacy-case'"
                )
            ).one()
        assert "requires_human_review" in row[0]
        assert row[1] is None
        engine.dispose()
    finally:
        get_settings.cache_clear()
