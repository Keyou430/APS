import importlib.util
from pathlib import Path

from alembic.ddl.base import AddColumn
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.database import Base
from app.schemas.pipeline import PipelineTaskCreate


def test_pipeline_approval_contract_has_task_policy_and_decision_audit_fields() -> None:
    tasks = Base.metadata.tables["pipeline_tasks"].c
    decisions = Base.metadata.tables["dashboard_decisions"].c

    assert "approval_required" in tasks
    assert "approval_assignee_type" in tasks
    assert "approval_assignee_id" in tasks
    assert "approval_role_name" in tasks
    assert "approval_reminder_after_minutes" in tasks
    assert "approval_escalation_after_minutes" in tasks
    assert "approval_escalation_role_name" in tasks

    assert "approver_user_id" in decisions
    assert "approval_comment" in decisions
    assert "rejection_reason" in decisions
    assert "reason_type" in decisions
    assert "decided_at" in decisions
    assert "reminder_sent_at" in decisions
    assert "escalation_sent_at" in decisions


def test_pipeline_approval_boolean_defaults_compile_for_postgresql() -> None:
    migration_path = (
        Path(__file__).parents[1]
        / "migrations"
        / "versions"
        / "20260827_0023_pipeline_approval.py"
    )
    spec = importlib.util.spec_from_file_location("pipeline_approval_migration", migration_path)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    migration_sql = str(
        AddColumn("pipeline_tasks", migration._approval_required_column()).compile(
            dialect=postgresql.dialect()
        )
    )
    model_sql = str(
        CreateTable(Base.metadata.tables["pipeline_tasks"]).compile(
            dialect=postgresql.dialect()
        )
    )

    assert "BOOLEAN DEFAULT true NOT NULL" in migration_sql
    assert "approval_required BOOLEAN DEFAULT true NOT NULL" in model_sql


def test_disabling_approval_normalizes_unused_assignee_fields() -> None:
    request = PipelineTaskCreate(
        title="日报",
        prompt="生成一份行业日报",
        task_type="general",
        schedule=None,
        timezone="Asia/Shanghai",
        input_sources=[],
        output_format="markdown",
        approval_required=False,
        approval_assignee_type="role",
        approval_role_name=None,
        confirmed=True,
    )

    assert request.approval_assignee_type == "creator"
    assert request.approval_assignee_id is None
    assert request.approval_role_name is None
