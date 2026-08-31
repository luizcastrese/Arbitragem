"""autonomous decision runs, reviews, appeals and verifications

Revision ID: e9f2a1c8d3b7
Revises: b7c4e91a5d20
Create Date: 2026-08-31
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e9f2a1c8d3b7"
down_revision: Union[str, None] = "b7c4e91a5d20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("cases", sa.Column("procedure_conclusion", sa.String(), nullable=True))
    op.add_column(
        "cases",
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column("cases", sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("cases", sa.Column("current_decision_run_id", sa.String(), nullable=True))
    op.add_column("cases", sa.Column("current_review_run_id", sa.String(), nullable=True))
    op.add_column("cases", sa.Column("verification_json", sa.Text(), nullable=True))
    op.add_column("cases", sa.Column("stability_json", sa.Text(), nullable=True))

    op.create_table(
        "llm_executions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("case_id", sa.String(), sa.ForeignKey("cases.id"), nullable=False),
        sa.Column("agent", sa.String(), nullable=False),
        sa.Column("task", sa.String(), nullable=False, server_default=""),
        sa.Column("requested_provider", sa.String(), nullable=False, server_default=""),
        sa.Column("requested_model", sa.String(), nullable=False, server_default=""),
        sa.Column("effective_provider", sa.String(), nullable=False, server_default=""),
        sa.Column("effective_model", sa.String(), nullable=True),
        sa.Column("provider_response_id", sa.String(), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("completion_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("fallback_used", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("fallback_reason", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="completed"),
        sa.Column("input_hash", sa.String(), nullable=True),
        sa.Column("output_hash", sa.String(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_llm_executions_case_id", "llm_executions", ["case_id"])
    op.create_index("ix_llm_executions_agent", "llm_executions", ["agent"])

    op.create_table(
        "decision_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("case_id", sa.String(), sa.ForeignKey("cases.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("supersedes_id", sa.String(), sa.ForeignKey("decision_runs.id"), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="processing"),
        sa.Column("role", sa.String(), nullable=False, server_default="judge"),
        sa.Column("execution_id", sa.String(), nullable=True),
        sa.Column("idempotency_key", sa.String(), nullable=True),
        sa.Column("input_hash", sa.String(), nullable=True),
        sa.Column("output_hash", sa.String(), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("provenance_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("case_id", "version", name="uq_decision_runs_case_version"),
        sa.UniqueConstraint("case_id", "idempotency_key", name="uq_decision_runs_idempotency"),
    )
    op.create_index("ix_decision_runs_case_id", "decision_runs", ["case_id"])
    op.create_index("ix_decision_runs_status", "decision_runs", ["status"])

    op.create_table(
        "automatic_review_runs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("case_id", sa.String(), sa.ForeignKey("cases.id"), nullable=False),
        sa.Column("decision_run_id", sa.String(), sa.ForeignKey("decision_runs.id"), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("supersedes_id", sa.String(), sa.ForeignKey("automatic_review_runs.id"), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="processing"),
        sa.Column("outcome", sa.String(), nullable=True),
        sa.Column("execution_id", sa.String(), nullable=True),
        sa.Column("input_hash", sa.String(), nullable=True),
        sa.Column("output_hash", sa.String(), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("case_id", "version", name="uq_review_runs_case_version"),
    )
    op.create_index("ix_automatic_review_runs_case_id", "automatic_review_runs", ["case_id"])

    op.create_table(
        "decision_verifications",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("case_id", sa.String(), sa.ForeignKey("cases.id"), nullable=False),
        sa.Column("decision_run_id", sa.String(), sa.ForeignKey("decision_runs.id"), nullable=True),
        sa.Column("valid", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("result_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("result_hash", sa.String(), nullable=False, server_default=""),
        sa.Column("execution_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_decision_verifications_case_id", "decision_verifications", ["case_id"])

    op.create_table(
        "automatic_appeals",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("case_id", sa.String(), sa.ForeignKey("cases.id"), nullable=False),
        sa.Column("filed_by", sa.String(), nullable=False),
        sa.Column("grounds_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("original_decision_hash", sa.String(), nullable=False, server_default=""),
        sa.Column("status", sa.String(), nullable=False, server_default="filed"),
        sa.Column("appeal_provider", sa.String(), nullable=True),
        sa.Column("appeal_model", sa.String(), nullable=True),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("result_hash", sa.String(), nullable=True),
        sa.Column("idempotency_key", sa.String(), nullable=True),
        sa.Column("execution_id", sa.String(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("supersedes_id", sa.String(), sa.ForeignKey("automatic_appeals.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("case_id", "idempotency_key", name="uq_appeals_idempotency"),
    )
    op.create_index("ix_automatic_appeals_case_id", "automatic_appeals", ["case_id"])
    op.create_index("ix_automatic_appeals_status", "automatic_appeals", ["status"])

    op.create_table(
        "attestation_records",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("case_id", sa.String(), sa.ForeignKey("cases.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("supersedes_id", sa.String(), sa.ForeignKey("attestation_records.id"), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="issued"),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("attestation_hash", sa.String(), nullable=False),
        sa.Column("decision_run_id", sa.String(), sa.ForeignKey("decision_runs.id"), nullable=True),
        sa.Column("review_run_id", sa.String(), sa.ForeignKey("automatic_review_runs.id"), nullable=True),
        sa.Column("verification_id", sa.String(), sa.ForeignKey("decision_verifications.id"), nullable=True),
        sa.Column("appeal_id", sa.String(), sa.ForeignKey("automatic_appeals.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("case_id", "version", name="uq_attestation_records_version"),
    )
    op.create_index("ix_attestation_records_case_id", "attestation_records", ["case_id"])
    op.create_index("ix_attestation_records_hash", "attestation_records", ["attestation_hash"])


def downgrade() -> None:
    op.drop_table("attestation_records")
    op.drop_table("automatic_appeals")
    op.drop_table("decision_verifications")
    op.drop_table("automatic_review_runs")
    op.drop_table("decision_runs")
    op.drop_table("llm_executions")
    op.drop_column("cases", "stability_json")
    op.drop_column("cases", "verification_json")
    op.drop_column("cases", "current_review_run_id")
    op.drop_column("cases", "current_decision_run_id")
    op.drop_column("cases", "processing_started_at")
    op.drop_column("cases", "row_version")
    op.drop_column("cases", "procedure_conclusion")
