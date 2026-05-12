"""phase E2 eval harness tables

Creates eval_runs + eval_case_results. See docs/EVAL_HARNESS.md §7 for the
schema rationale.

NOTE: the autogenerator also detected the LangGraph checkpoint_* tables as
"removed" because LangGraph manages those programmatically (via
AsyncPostgresSaver.setup()), not via Alembic. We deliberately strip those
drops here — touching them would wipe conversation memory. They are
re-created idempotently on each app start by the checkpointer module.

Revision ID: cf69b33713d6
Revises: c831274dc9b9
Create Date: 2026-05-12 13:34:55.988115
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "cf69b33713d6"
down_revision: Union[str, Sequence[str], None] = "c831274dc9b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "eval_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("started_at", postgresql.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("finished_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("git_sha", sa.String(), nullable=True),
        sa.Column("git_branch", sa.String(), nullable=True),
        sa.Column("triggered_by", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("total_cases", sa.Integer(), nullable=False),
        sa.Column("total_phrasings", sa.Integer(), nullable=False),
        sa.Column("strict_passed", sa.Integer(), nullable=False),
        sa.Column("soft_passed", sa.Integer(), nullable=False),
        sa.Column("failed", sa.Integer(), nullable=False),
        sa.Column("errored", sa.Integer(), nullable=False),
        sa.Column("total_latency_ms", sa.Integer(), nullable=False),
        sa.Column("total_cost_usd", sa.Numeric(precision=10, scale=4), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_eval_runs_started_at"), "eval_runs", ["started_at"], unique=False
    )

    op.create_table(
        "eval_case_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("case_id", sa.String(), nullable=False),
        sa.Column("phrasing", sa.Text(), nullable=False),
        sa.Column("repeat_index", sa.Integer(), nullable=False),
        sa.Column("verdict", sa.String(), nullable=False),
        sa.Column("errored", sa.Boolean(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "tool_calls", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("final_response", sa.Text(), nullable=False),
        sa.Column(
            "failure_reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("tokens_in", sa.Integer(), nullable=True),
        sa.Column("tokens_out", sa.Integer(), nullable=True),
        sa.Column("cost_usd", sa.Numeric(precision=10, scale=6), nullable=True),
        sa.Column("langsmith_trace_id", sa.String(), nullable=True),
        sa.Column("langsmith_trace_url", sa.Text(), nullable=True),
        sa.Column("langsmith_thread_id", sa.String(), nullable=True),
        sa.Column("agent_thread_id", sa.String(), nullable=True),
        sa.Column("intent_question_type", sa.String(), nullable=False),
        sa.Column("intent_complexity", sa.String(), nullable=False),
        sa.Column("intent_domain", sa.String(), nullable=False),
        sa.Column("intent_answer_shape", sa.String(), nullable=False),
        sa.Column("tags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["run_id"], ["eval_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    for col in (
        "agent_thread_id",
        "case_id",
        "intent_complexity",
        "intent_domain",
        "intent_question_type",
        "langsmith_trace_id",
        "run_id",
        "verdict",
    ):
        op.create_index(
            op.f(f"ix_eval_case_results_{col}"),
            "eval_case_results",
            [col],
            unique=False,
        )


def downgrade() -> None:
    for col in (
        "verdict",
        "run_id",
        "langsmith_trace_id",
        "intent_question_type",
        "intent_domain",
        "intent_complexity",
        "case_id",
        "agent_thread_id",
    ):
        op.drop_index(
            op.f(f"ix_eval_case_results_{col}"), table_name="eval_case_results"
        )
    op.drop_table("eval_case_results")
    op.drop_index(op.f("ix_eval_runs_started_at"), table_name="eval_runs")
    op.drop_table("eval_runs")
