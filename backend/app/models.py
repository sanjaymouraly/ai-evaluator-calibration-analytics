"""SQLAlchemy ORM models for the evaluation platform.

Schema supports: project ownership, dataset provenance, immutable rating
history (versioned rows), rubric versioning with human approval, adjudication
chains, calibration sessions, audit logs, and analytics-friendly indexes.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _newid() -> str:
    return uuid.uuid4().hex


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_newid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(
        String(32), default="reviewer"
    )  # admin|adjudicator|senior_reviewer|reviewer
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_login_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    ratings = relationship("Rating", back_populates="reviewer")
    memberships = relationship(
        "ProjectMember",
        back_populates="user",
        foreign_keys="ProjectMember.user_id",
    )
    audit_actor = relationship("AuditLog", back_populates="user")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_newid)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft|active|completed|archived
    mode: Mapped[str] = mapped_column(String(16), default="single")  # single|pairwise
    min_ratings_per_item: Mapped[int] = mapped_column(Integer, default=2)
    # Scale-aware disagreement thresholds (fraction of scale range for ordinal/numerical).
    disagreement_minor_fraction: Mapped[float] = mapped_column(Float, default=0.25)
    disagreement_major_fraction: Mapped[float] = mapped_column(Float, default=0.5)
    categorical_opposite_pairs: Mapped[Any] = mapped_column(
        JSON, nullable=True
    )  # e.g. {"acceptable": "rejected"}
    consensus_strategy: Mapped[str] = mapped_column(String(32), default="majority")  # majority|median|expert
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    members = relationship("ProjectMember", back_populates="project", cascade="all, delete-orphan")
    datasets = relationship("Dataset", back_populates="project", cascade="all, delete-orphan")
    tasks = relationship("EvaluationTask", back_populates="project")
    rubrics = relationship("Rubric", back_populates="project")

    __table_args__ = (Index("ix_projects_owner_status", "owner_id", "status"),)


class ProjectMember(Base):
    __tablename__ = "project_members"
    __table_args__ = (UniqueConstraint("project_id", "user_id", name="uq_project_member"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_newid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role_on_project: Mapped[str] = mapped_column(String(32), default="reviewer")  # lead|reviewer|adjudicator
    assigned_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    assigned_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    project = relationship("Project", back_populates="members")
    user = relationship(
        "User",
        back_populates="memberships",
        foreign_keys=[user_id],
    )


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_newid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    source_file_name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    source_format: Mapped[str] = mapped_column(String(16))  # csv|json|jsonl
    import_errors_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    created_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    project = relationship("Project", back_populates="datasets")
    tasks = relationship("EvaluationTask", back_populates="dataset")


class Rubric(Base):
    __tablename__ = "rubrics"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_newid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft|active|superseded|archived
    created_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    approved_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    approved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    effective_from: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    change_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    project = relationship("Project", back_populates="rubrics")
    categories = relationship("RubricCategory", back_populates="rubric", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("project_id", "version", name="uq_rubric_project_version"),)


class RubricCategory(Base):
    __tablename__ = "rubric_categories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_newid)
    rubric_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("rubrics.id", ondelete="CASCADE"), index=True
    )
    key: Mapped[str] = mapped_column(String(128))  # stable machine key
    name: Mapped[str] = mapped_column(String(255))
    definition: Mapped[str | None] = mapped_column(Text, nullable=True)
    guidance: Mapped[str | None] = mapped_column(Text, nullable=True)
    weight: Mapped[float] = mapped_column(Float, default=1.0)
    scale_type: Mapped[str] = mapped_column(String(16))  # categorical|ordinal|numerical
    min_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Ordinal/categorical options: [{"value":1,"label":"Poor","description":"..."}, ...]
    options_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    # Anchors: [{"value":3,"label":"Adequate","example":"..."}]
    anchors_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    examples_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    item_order: Mapped[int] = mapped_column(Integer, default=0)

    rubric = relationship("Rubric", back_populates="categories")

    __table_args__ = (Index("ix_rubric_categories_rubric_order", "rubric_id", "item_order"),)


class EvaluationTask(Base):
    __tablename__ = "evaluation_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_newid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    dataset_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("datasets.id", ondelete="SET NULL"), nullable=True, index=True
    )
    external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    mode: Mapped[str] = mapped_column(String(16), default="single")  # single|pairwise
    prompt: Mapped[str] = mapped_column(Text)
    response_a: Mapped[str] = mapped_column(Text)
    response_b: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model_version: Mapped[str | None] = mapped_column(String(128), nullable=True)
    language: Mapped[str | None] = mapped_column(String(32), nullable=True)
    task_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    metadata_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(
        String(16), default="pending"
    )  # pending|in_progress|completed|adjudicated
    # Expert-approved reference (gold) labels.
    gold_label_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    gold_approved_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    gold_approved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    import_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    project = relationship("Project", back_populates="tasks")
    dataset = relationship("Dataset", back_populates="tasks")
    ratings = relationship("Rating", back_populates="task", cascade="all, delete-orphan")
    assignments = relationship("Assignment", back_populates="task", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("project_id", "external_id", name="uq_task_project_external"),
        Index("ix_tasks_project_status", "project_id", "status"),
        Index("ix_tasks_model", "project_id", "model_name"),
    )


class Rating(Base):
    """Immutable rating records.

    Corrections never UPDATE a submitted rating; they append a new version row
    and the service flips `is_current`. Submitted ratings are auditable forever.
    """

    __tablename__ = "ratings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_newid)
    task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("evaluation_tasks.id", ondelete="CASCADE"), index=True
    )
    reviewer_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    rubric_version_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("rubrics.id"), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft|submitted
    # Scores: {"clarity": 4, "correctness": "correct"} — scale-appropriate values
    scores_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)  # 0..1
    abstained: Mapped[bool] = mapped_column(Boolean, default=False)
    submitted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    task = relationship("EvaluationTask", back_populates="ratings")
    reviewer = relationship("User", back_populates="ratings")

    __table_args__ = (
        UniqueConstraint("task_id", "reviewer_id", "version", name="uq_rating_task_reviewer_version"),
        Index("ix_ratings_task_current", "task_id", "is_current"),
    )


class Assignment(Base):
    __tablename__ = "assignments"
    __table_args__ = (UniqueConstraint("task_id", "reviewer_id", name="uq_assignment_task_reviewer"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_newid)
    task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("evaluation_tasks.id", ondelete="CASCADE"), index=True
    )
    reviewer_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(
        String(16), default="assigned"
    )  # assigned|in_progress|completed|skipped
    blinded: Mapped[bool] = mapped_column(Boolean, default=True)
    workload_weight: Mapped[float] = mapped_column(Float, default=1.0)
    assigned_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    task = relationship("EvaluationTask", back_populates="assignments")


class Disagreement(Base):
    __tablename__ = "disagreements"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_newid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("evaluation_tasks.id", ondelete="CASCADE"), index=True
    )
    category_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    kind: Mapped[str] = mapped_column(String(32))  # see detection engine
    severity_score: Mapped[float] = mapped_column(Float, default=0.0)  # 0..1 transparent composite
    severity_class: Mapped[str] = mapped_column(String(16), default="minor")  # minor|major|critical
    details_json: Mapped[Any] = mapped_column(JSON, nullable=True)  # gaps, reviewers, evidence
    priority_score: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(16), default="open")  # open|in_review|resolved|dismissed
    detected_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    adjudications = relationship("Adjudication", back_populates="disagreement")

    __table_args__ = (Index("ix_disagreements_project_status", "project_id", "status"),)


class Adjudication(Base):
    __tablename__ = "adjudications"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_newid)
    disagreement_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("disagreements.id", ondelete="SET NULL"), nullable=True, index=True
    )
    task_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("evaluation_tasks.id", ondelete="CASCADE"), index=True
    )
    adjudicator_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    strategy: Mapped[str] = mapped_column(String(32), default="expert")  # majority|median|expert
    decision_json: Mapped[Any] = mapped_column(JSON, nullable=True)  # authoritative final label
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    escalated: Mapped[bool] = mapped_column(Boolean, default=False)
    escalates_to: Mapped[str | None] = mapped_column(String(36), nullable=True)  # adjudication body/role
    prior_adjudication_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("adjudications.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), default="proposed")  # proposed|final|reopened
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    disagreement = relationship("Disagreement", back_populates="adjudications")
    votes = relationship("AdjudicationVote", back_populates="adjudication", cascade="all, delete-orphan")


class AdjudicationVote(Base):
    __tablename__ = "adjudication_votes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_newid)
    adjudication_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("adjudications.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    decision_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    adjudication = relationship("Adjudication", back_populates="votes")


class CalibrationSession(Base):
    __tablename__ = "calibration_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_newid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    pass_threshold_kappa: Mapped[float] = mapped_column(Float, default=0.7)
    pass_threshold_accuracy: Mapped[float] = mapped_column(Float, default=0.8)
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft|active|completed
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    attempts = relationship("CalibrationAttempt", back_populates="session", cascade="all, delete-orphan")


class CalibrationAttempt(Base):
    __tablename__ = "calibration_attempts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_newid)
    session_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("calibration_sessions.id", ondelete="CASCADE"), index=True
    )
    reviewer_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    phase: Mapped[str] = mapped_column(String(16))  # pre|post
    item_scores_json: Mapped[Any] = mapped_column(JSON, nullable=True)  # reviewer answers
    gold_scores_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    kappa: Mapped[float | None] = mapped_column(Float, nullable=True)
    accuracy: Mapped[float | None] = mapped_column(Float, nullable=True)
    mae: Mapped[float | None] = mapped_column(Float, nullable=True)
    passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    feedback_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    completed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    session = relationship("CalibrationSession", back_populates="attempts")
    __table_args__ = (
        UniqueConstraint("session_id", "reviewer_id", "phase", name="uq_calib_session_reviewer_phase"),
    )


class RubricChangeRequest(Base):
    """Every rubric change requires explicit human approval. Scores are never altered."""

    __tablename__ = "rubric_change_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_newid)
    rubric_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("rubrics.id", ondelete="CASCADE"), index=True
    )
    rubric_category_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("rubric_categories.id"), nullable=True
    )
    insight_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("rubric_insights.id"), nullable=True
    )
    proposed_changes_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    evidence_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    source: Mapped[str] = mapped_column(String(16), default="manual")  # manual|ai_suggested
    is_ai_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending|approved|rejected
    reviewed_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    new_rubric_version_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("rubrics.id"), nullable=True
    )


class RubricInsight(Base):
    __tablename__ = "rubric_insights"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_newid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    rubric_category_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("rubric_categories.id"), nullable=True
    )
    issue_type: Mapped[str] = mapped_column(
        String(64)
    )  # high_disagreement|low_reliability|boundary_confusion|missing_anchors|drift|...
    severity: Mapped[str] = mapped_column(String(16), default="medium")  # low|medium|high|critical
    evidence_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    affected_task_ids_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    sample_size: Mapped[int] = mapped_column(Integer, default=0)
    stat_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    suggestion_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    source: Mapped[str] = mapped_column(String(16), default="deterministic")  # deterministic|ai_assisted
    status: Mapped[str] = mapped_column(String(16), default="open")  # open|approved|rejected|resolved
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_newid)
    user_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(128))
    entity_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    entity_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    details_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    user = relationship("User", back_populates="audit_actor")
    __table_args__ = (Index("ix_audit_entity", "entity_type", "entity_id"),)


class AIProviderSetting(Base):
    __tablename__ = "ai_provider_settings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_newid)
    owner_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(32))  # openai|anthropic|openrouter|openai_compatible|ollama
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    base_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    encrypted_api_key: Mapped[str | None] = mapped_column(Text, nullable=True)  # Fernet-encrypted
    extra_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class LLMUsageLog(Base):
    __tablename__ = "llm_usage_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_newid)
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    endpoint: Mapped[str] = mapped_column(String(128))
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    estimated_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(16))  # ok|error|skipped_offline
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_newid)
    job_type: Mapped[str] = mapped_column(String(64))  # report_generation|disagreement_scan|analytics_refresh
    payload_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued|running|succeeded|failed
    result_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id"), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_newid)
    project_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(255))
    report_format: Mapped[str] = mapped_column(String(16))  # csv|json|pdf
    filters_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    metric_definitions_json: Mapped[Any] = mapped_column(JSON, nullable=True)
    file_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    generated_by: Mapped[str] = mapped_column(String(36), ForeignKey("users.id"))
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
