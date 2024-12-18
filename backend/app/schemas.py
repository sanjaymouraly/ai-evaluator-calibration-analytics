"""Pydantic request/response schemas (typed API contracts)."""

from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, EmailStr, Field, field_validator


# ---------- Auth ----------
class UserRegister(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    role: str = Field(default="reviewer")

    @field_validator("role")
    @classmethod
    def valid_role(cls, v: str) -> str:
        allowed = {"admin", "adjudicator", "senior_reviewer", "reviewer"}
        if v not in allowed:
            raise ValueError(f"role must be one of {sorted(allowed)}")
        return v


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    email: str
    full_name: str
    role: str
    is_active: bool
    created_at: dt.datetime


class UserRoleUpdate(BaseModel):
    role: str


# ---------- Projects ----------
class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    mode: str = Field(default="single")
    min_ratings_per_item: int = Field(default=2, ge=1, le=20)
    disagreement_minor_fraction: float = Field(default=0.25, ge=0.01, le=1.0)
    disagreement_major_fraction: float = Field(default=0.5, ge=0.01, le=1.0)
    categorical_opposite_pairs: dict[str, str] | None = None
    consensus_strategy: str = Field(default="majority")

    @field_validator("mode")
    @classmethod
    def valid_mode(cls, v: str) -> str:
        if v not in {"single", "pairwise"}:
            raise ValueError("mode must be 'single' or 'pairwise'")
        return v

    @field_validator("consensus_strategy")
    @classmethod
    def valid_strategy(cls, v: str) -> str:
        if v not in {"majority", "median", "expert"}:
            raise ValueError("consensus_strategy must be majority|median|expert")
        return v


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    status: str | None = None
    min_ratings_per_item: int | None = Field(default=None, ge=1, le=20)
    disagreement_minor_fraction: float | None = Field(default=None, ge=0.01, le=1.0)
    disagreement_major_fraction: float | None = Field(default=None, ge=0.01, le=1.0)
    consensus_strategy: str | None = None


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    name: str
    description: str | None
    owner_id: str
    status: str
    mode: str
    min_ratings_per_item: int
    disagreement_minor_fraction: float
    disagreement_major_fraction: float
    consensus_strategy: str
    created_at: dt.datetime
    updated_at: dt.datetime


class ProjectMemberOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    project_id: str
    user_id: str
    role_on_project: str
    user: UserOut


class MemberAdd(BaseModel):
    user_id: str
    role_on_project: str = Field(default="reviewer")


# ---------- Datasets / import ----------
class ImportPreviewRow(BaseModel):
    row_number: int
    valid: bool
    errors: list[str] = Field(default_factory=list)
    data: dict[str, Any]


class ImportResult(BaseModel):
    session_id: str
    dataset_id: str | None
    total_rows: int
    valid_rows: int
    error_rows: int
    duplicates_skipped: int
    preview: list[ImportPreviewRow]
    errors: list[dict[str, Any]]
    dry_run: bool


class ImportRequest(BaseModel):
    filename: str
    file_format: str = Field(pattern="^(csv|json|jsonl)$")
    content: str  # raw file text (base64 not needed; bounded by max_upload_mb check upstream)
    mapping: dict[str, str] | None = None  # source column -> canonical field
    dry_run: bool = False


# ---------- Rubrics ----------
class RubricAnchor(BaseModel):
    """One scale point / category option.

    ``value`` is numeric for ordinal and numerical scales and may be a
    string for categorical scales (e.g. "safe" / "borderline" / "unsafe").
    """

    value: float | str
    label: str
    description: str | None = None
    example: str | None = None


class RubricCategoryBase(BaseModel):
    key: str = Field(min_length=1, max_length=128, pattern=r"^[a-z0-9_]+$")
    name: str = Field(min_length=1, max_length=255)
    definition: str | None = None
    guidance: str | None = None
    weight: float = Field(default=1.0, ge=0.0, le=100.0)
    scale_type: str
    min_value: float | None = None
    max_value: float | None = None
    options: list[RubricAnchor] | None = None  # categorical/ordinal choices
    anchors: list[RubricAnchor] | None = None
    examples: list[dict[str, Any]] | None = None
    item_order: int = 0

    @field_validator("scale_type")
    @classmethod
    def valid_scale(cls, v: str) -> str:
        if v not in {"categorical", "ordinal", "numerical"}:
            raise ValueError("scale_type must be categorical|ordinal|numerical")
        return v


class RubricCategoryOut(BaseModel):
    """DB-shaped category (JSON columns exposed under clean names)."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    rubric_id: str
    key: str
    name: str
    definition: str | None
    guidance: str | None
    weight: float
    scale_type: str
    min_value: float | None
    max_value: float | None
    options: Any = Field(default=None, validation_alias=AliasChoices("options", "options_json"))
    anchors: Any = Field(default=None, validation_alias=AliasChoices("anchors", "anchors_json"))
    examples: Any = Field(default=None, validation_alias=AliasChoices("examples", "examples_json"))
    item_order: int


class RubricCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    categories: list[RubricCategoryBase] = Field(min_length=1, max_length=50)


class RubricOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    project_id: str
    name: str
    description: str | None
    version: int
    status: str
    approved_by: str | None
    approved_at: dt.datetime | None
    effective_from: dt.datetime | None
    change_note: str | None
    created_at: dt.datetime
    categories: list[RubricCategoryOut] = Field(default_factory=list)


class RubricVersionOut(BaseModel):
    id: str
    version: int
    status: str
    change_note: str | None
    created_at: dt.datetime
    approved_at: dt.datetime | None


class RubricChangeRequestCreate(BaseModel):
    rubric_category_id: str | None = None
    proposed_changes: dict[str, Any]
    rationale: str = Field(min_length=10, max_length=4000)


class RubricChangeRequestOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    rubric_id: str
    rubric_category_id: str | None
    proposed_changes: Any = Field(
        default=None, validation_alias=AliasChoices("proposed_changes", "proposed_changes_json")
    )
    evidence: Any = Field(default=None, validation_alias=AliasChoices("evidence", "evidence_json"))
    rationale: str
    requested_by: str
    source: str
    is_ai_generated: bool
    status: str
    review_note: str | None
    created_at: dt.datetime
    reviewed_at: dt.datetime | None


# ---------- Tasks ----------
class TaskImportItem(BaseModel):
    external_id: str | None = None
    prompt: str
    response_a: str
    response_b: str | None = None
    reference_answer: str | None = None
    model_name: str | None = None
    model_version: str | None = None
    language: str | None = None
    task_type: str | None = None
    metadata: dict[str, Any] | None = None


class TaskCreate(BaseModel):
    external_id: str | None = None
    prompt: str = Field(min_length=1)
    response_a: str = Field(min_length=1)
    response_b: str | None = None
    reference_answer: str | None = None
    model_name: str | None = None
    model_version: str | None = None
    language: str | None = None
    task_type: str | None = None
    metadata: dict[str, Any] | None = None


class TaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    project_id: str
    dataset_id: str | None
    external_id: str | None
    mode: str
    prompt: str
    response_a: str
    response_b: str | None
    reference_answer: str | None
    model_name: str | None
    model_version: str | None
    language: str | None
    task_type: str | None
    # NOTE: must read `metadata_json` only — `metadata` on an ORM class
    # resolves to SQLAlchemy's declarative MetaData object.
    metadata: Any = Field(default=None, validation_alias="metadata_json")
    status: str
    gold_label: Any = Field(default=None, validation_alias=AliasChoices("gold_label", "gold_label_json"))
    created_at: dt.datetime


class GoldLabelSet(BaseModel):
    scores: dict[str, Any]
    rationale: str | None = None


# ---------- Ratings ----------
class RatingSubmit(BaseModel):
    scores: dict[str, Any]
    rationale: str | None = None
    evidence: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    abstained: bool = False


class RatingDraft(RatingSubmit):
    pass


class RatingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    task_id: str
    reviewer_id: str
    reviewer_name: str | None = None
    rubric_version_id: str | None
    version: int
    status: str
    scores: Any = Field(default=None, validation_alias=AliasChoices("scores", "scores_json"))
    rationale: str | None
    evidence: str | None
    confidence: float | None
    abstained: bool
    submitted_at: dt.datetime | None
    created_at: dt.datetime


class AssignmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    task_id: str
    reviewer_id: str
    status: str
    blinded: bool
    assigned_at: dt.datetime
    completed_at: dt.datetime | None
    task: TaskOut | None = None


# ---------- Disagreements ----------
class DisagreementOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    project_id: str
    task_id: str
    category_key: str | None
    kind: str
    severity_score: float
    severity_class: str
    details: Any = Field(default=None, validation_alias=AliasChoices("details", "details_json"))
    priority_score: float
    status: str
    detected_at: dt.datetime


class DisagreementFilter(BaseModel):
    status: str | None = None
    kind: str | None = None
    category_key: str | None = None
    min_severity: float | None = None
    reviewer_id: str | None = None
    model_name: str | None = None


# ---------- Adjudication ----------
class AdjudicationCreate(BaseModel):
    decision: dict[str, Any]
    rationale: str = Field(min_length=10, max_length=8000)
    strategy: str | None = None


class AdjudicationVoteCreate(BaseModel):
    decision: dict[str, Any]
    rationale: str | None = None


class AdjudicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    disagreement_id: str | None
    task_id: str
    adjudicator_id: str
    strategy: str
    decision: Any = Field(default=None, validation_alias=AliasChoices("decision", "decision_json"))
    rationale: str | None
    escalated: bool
    status: str
    created_at: dt.datetime


# ---------- Calibration ----------
class CalibrationSessionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    task_ids: list[str] = Field(min_length=1)
    pass_threshold_kappa: float = Field(default=0.7, ge=0.0, le=1.0)
    pass_threshold_accuracy: float = Field(default=0.8, ge=0.0, le=1.0)


class CalibrationAttemptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    session_id: str
    reviewer_id: str
    phase: str
    kappa: float | None
    accuracy: float | None
    mae: float | None
    passed: bool | None
    feedback: Any = Field(default=None, validation_alias=AliasChoices("feedback", "feedback_json"))
    completed_at: dt.datetime


# ---------- Rubric insights ----------
class RubricInsightOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    project_id: str
    rubric_category_id: str | None
    issue_type: str
    severity: str
    evidence: Any = Field(default=None, validation_alias=AliasChoices("evidence", "evidence_json"))
    affected_task_ids: Any = Field(
        default=None, validation_alias=AliasChoices("affected_task_ids", "affected_task_ids_json")
    )
    sample_size: int
    stat_value: float | None
    suggestion: Any = Field(default=None, validation_alias=AliasChoices("suggestion", "suggestion_json"))
    source: str
    status: str
    created_at: dt.datetime


# ---------- Reports / jobs ----------
class ReportRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    report_format: str = Field(pattern="^(csv|json|pdf)$")
    filters: dict[str, Any] | None = None
    include_sections: list[str] | None = None


class ReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    project_id: str
    title: str
    report_format: str
    filters: Any = Field(default=None, validation_alias=AliasChoices("filters", "filters_json"))
    metric_definitions: Any = Field(
        default=None,
        validation_alias=AliasChoices("metric_definitions", "metric_definitions_json"),
    )
    file_path: str | None
    generated_by: str
    created_at: dt.datetime


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    job_type: str
    status: str
    result: Any = Field(default=None, validation_alias=AliasChoices("result", "result_json"))
    error_message: str | None
    created_at: dt.datetime
    started_at: dt.datetime | None
    finished_at: dt.datetime | None


# ---------- Analytics ----------
class AnalyticsFilters(BaseModel):
    reviewer_ids: list[str] | None = None
    model_names: list[str] | None = None
    dataset_ids: list[str] | None = None
    rubric_category_keys: list[str] | None = None
    date_from: dt.date | None = None
    date_to: dt.date | None = None


# ---------- Additional output schemas ----------
class AuditLogOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    user_id: str | None
    action: str
    entity_type: str | None
    entity_id: str | None
    details: Any = Field(default=None, validation_alias=AliasChoices("details", "details_json"))
    ip_address: str | None
    created_at: dt.datetime


class LLMUsageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    provider: str
    model: str | None
    endpoint: str
    prompt_tokens: int
    completion_tokens: int
    estimated_cost_usd: float
    status: str
    created_at: dt.datetime


class CalibrationSessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    project_id: str
    name: str
    description: str | None
    created_by: str
    pass_threshold_kappa: float
    pass_threshold_accuracy: float
    status: str
    created_at: dt.datetime


class RatingHistoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: str
    task_id: str
    reviewer_id: str
    version: int
    is_current: bool
    status: str
    scores: Any = Field(default=None, validation_alias=AliasChoices("scores", "scores_json"))
    rationale: str | None
    confidence: float | None
    abstained: bool
    rubric_version_id: str | None
    submitted_at: dt.datetime | None
    created_at: dt.datetime
