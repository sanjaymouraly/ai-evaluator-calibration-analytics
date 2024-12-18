"""Initial schema for evaluation platform.

Revision ID: 0001
Revises:
Create Date: 2026-10-17
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # users
    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("email", sa.String(255), nullable=False, unique=True),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("role", sa.String(32), nullable=False, server_default="reviewer"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # projects
    op.create_table(
        "projects",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("mode", sa.String(16), nullable=False, server_default="single"),
        sa.Column("min_ratings_per_item", sa.Integer(), nullable=False, server_default="2"),
        sa.Column("disagreement_minor_fraction", sa.Float(), nullable=False, server_default="0.25"),
        sa.Column("disagreement_major_fraction", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("categorical_opposite_pairs", sa.JSON(), nullable=True),
        sa.Column("consensus_strategy", sa.String(32), nullable=False, server_default="majority"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_projects_owner_status", "projects", ["owner_id", "status"])

    # project_members
    op.create_table(
        "project_members",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role_on_project", sa.String(32), nullable=False, server_default="reviewer"),
        sa.Column("assigned_by", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "user_id", name="uq_project_member"),
    )

    # datasets
    op.create_table(
        "datasets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("source_file_name", sa.String(512), nullable=True),
        sa.Column("source_format", sa.String(16), nullable=False),
        sa.Column("import_errors_json", sa.JSON(), nullable=True),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # rubrics
    op.create_table(
        "rubrics",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("approved_by", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("change_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "version", name="uq_rubric_project_version"),
    )

    # rubric_categories
    op.create_table(
        "rubric_categories",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("rubric_id", sa.String(36), sa.ForeignKey("rubrics.id", ondelete="CASCADE"), nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("definition", sa.Text(), nullable=True),
        sa.Column("guidance", sa.Text(), nullable=True),
        sa.Column("weight", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("scale_type", sa.String(16), nullable=False),
        sa.Column("min_value", sa.Float(), nullable=True),
        sa.Column("max_value", sa.Float(), nullable=True),
        sa.Column("options_json", sa.JSON(), nullable=True),
        sa.Column("anchors_json", sa.JSON(), nullable=True),
        sa.Column("examples_json", sa.JSON(), nullable=True),
        sa.Column("item_order", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_rubric_categories_rubric_order", "rubric_categories", ["rubric_id", "item_order"])

    # evaluation_tasks
    op.create_table(
        "evaluation_tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dataset_id", sa.String(36), sa.ForeignKey("datasets.id", ondelete="SET NULL"), nullable=True),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column("mode", sa.String(16), nullable=False, server_default="single"),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("response_a", sa.Text(), nullable=False),
        sa.Column("response_b", sa.Text(), nullable=True),
        sa.Column("reference_answer", sa.Text(), nullable=True),
        sa.Column("model_name", sa.String(255), nullable=True),
        sa.Column("model_version", sa.String(128), nullable=True),
        sa.Column("language", sa.String(32), nullable=True),
        sa.Column("task_type", sa.String(64), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("gold_label_json", sa.JSON(), nullable=True),
        sa.Column("gold_approved_by", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("gold_approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("import_hash", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("project_id", "external_id", name="uq_task_project_external"),
    )
    op.create_index("ix_tasks_project_status", "evaluation_tasks", ["project_id", "status"])
    op.create_index("ix_tasks_model", "evaluation_tasks", ["project_id", "model_name"])
    op.create_index("ix_tasks_import_hash", "evaluation_tasks", ["import_hash"])

    # ratings
    op.create_table(
        "ratings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("evaluation_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reviewer_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("rubric_version_id", sa.String(36), sa.ForeignKey("rubrics.id"), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("scores_json", sa.JSON(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("abstained", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("task_id", "reviewer_id", "version", name="uq_rating_task_reviewer_version"),
    )
    op.create_index("ix_ratings_task_current", "ratings", ["task_id", "is_current"])

    # assignments
    op.create_table(
        "assignments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("evaluation_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reviewer_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="assigned"),
        sa.Column("blinded", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("workload_weight", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("task_id", "reviewer_id", name="uq_assignment_task_reviewer"),
    )

    # disagreements
    op.create_table(
        "disagreements",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("evaluation_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category_key", sa.String(128), nullable=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("severity_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("severity_class", sa.String(16), nullable=False, server_default="minor"),
        sa.Column("details_json", sa.JSON(), nullable=True),
        sa.Column("priority_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_disagreements_project_status", "disagreements", ["project_id", "status"])

    # adjudications
    op.create_table(
        "adjudications",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("disagreement_id", sa.String(36), sa.ForeignKey("disagreements.id", ondelete="SET NULL"), nullable=True),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("evaluation_tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("adjudicator_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("strategy", sa.String(32), nullable=False, server_default="expert"),
        sa.Column("decision_json", sa.JSON(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("escalated", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("escalates_to", sa.String(36), nullable=True),
        sa.Column("prior_adjudication_id", sa.String(36), sa.ForeignKey("adjudications.id"), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="proposed"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # adjudication_votes
    op.create_table(
        "adjudication_votes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("adjudication_id", sa.String(36), sa.ForeignKey("adjudications.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("decision_json", sa.JSON(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # calibration_sessions
    op.create_table(
        "calibration_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("pass_threshold_kappa", sa.Float(), nullable=False, server_default="0.7"),
        sa.Column("pass_threshold_accuracy", sa.Float(), nullable=False, server_default="0.8"),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # calibration_attempts
    op.create_table(
        "calibration_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("session_id", sa.String(36), sa.ForeignKey("calibration_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("reviewer_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("phase", sa.String(16), nullable=False),
        sa.Column("item_scores_json", sa.JSON(), nullable=True),
        sa.Column("gold_scores_json", sa.JSON(), nullable=True),
        sa.Column("kappa", sa.Float(), nullable=True),
        sa.Column("accuracy", sa.Float(), nullable=True),
        sa.Column("mae", sa.Float(), nullable=True),
        sa.Column("passed", sa.Boolean(), nullable=True),
        sa.Column("feedback_json", sa.JSON(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("session_id", "reviewer_id", "phase", name="uq_calib_session_reviewer_phase"),
    )

    # rubric_insights
    op.create_table(
        "rubric_insights",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rubric_category_id", sa.String(36), sa.ForeignKey("rubric_categories.id"), nullable=True),
        sa.Column("issue_type", sa.String(64), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False, server_default="medium"),
        sa.Column("evidence_json", sa.JSON(), nullable=True),
        sa.Column("affected_task_ids_json", sa.JSON(), nullable=True),
        sa.Column("sample_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("stat_value", sa.Float(), nullable=True),
        sa.Column("suggestion_json", sa.JSON(), nullable=True),
        sa.Column("source", sa.String(16), nullable=False, server_default="deterministic"),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # rubric_change_requests
    op.create_table(
        "rubric_change_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("rubric_id", sa.String(36), sa.ForeignKey("rubrics.id", ondelete="CASCADE"), nullable=False),
        sa.Column("rubric_category_id", sa.String(36), sa.ForeignKey("rubric_categories.id"), nullable=True),
        sa.Column("insight_id", sa.String(36), sa.ForeignKey("rubric_insights.id"), nullable=True),
        sa.Column("proposed_changes_json", sa.JSON(), nullable=True),
        sa.Column("evidence_json", sa.JSON(), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("requested_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("source", sa.String(16), nullable=False, server_default="manual"),
        sa.Column("is_ai_generated", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("reviewed_by", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("new_rubric_version_id", sa.String(36), sa.ForeignKey("rubrics.id"), nullable=True),
    )

    # audit_logs
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("action", sa.String(128), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=True),
        sa.Column("entity_id", sa.String(36), nullable=True),
        sa.Column("details_json", sa.JSON(), nullable=True),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_entity", "audit_logs", ["entity_type", "entity_id"])

    # ai_provider_settings
    op.create_table(
        "ai_provider_settings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("label", sa.String(255), nullable=True),
        sa.Column("base_url", sa.String(512), nullable=True),
        sa.Column("model", sa.String(255), nullable=True),
        sa.Column("encrypted_api_key", sa.Text(), nullable=True),
        sa.Column("extra_json", sa.JSON(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    # llm_usage_logs
    op.create_table(
        "llm_usage_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(255), nullable=True),
        sa.Column("endpoint", sa.String(128), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # jobs
    op.create_table(
        "jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("job_type", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(36), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )

    # reports
    op.create_table(
        "reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(36), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("report_format", sa.String(16), nullable=False),
        sa.Column("filters_json", sa.JSON(), nullable=True),
        sa.Column("metric_definitions_json", sa.JSON(), nullable=True),
        sa.Column("file_path", sa.String(1024), nullable=True),
        sa.Column("generated_by", sa.String(36), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    for table in (
        "reports",
        "jobs",
        "llm_usage_logs",
        "ai_provider_settings",
        "audit_logs",
        "rubric_insights",
        "rubric_change_requests",
        "calibration_attempts",
        "calibration_sessions",
        "adjudication_votes",
        "adjudications",
        "disagreements",
        "assignments",
        "ratings",
        "evaluation_tasks",
        "rubric_categories",
        "rubrics",
        "datasets",
        "project_members",
        "projects",
        "users",
    ):
        op.drop_table(table)
