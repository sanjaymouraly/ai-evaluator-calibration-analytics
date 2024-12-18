"""Rubric CRUD, versioning, human-approved change workflow, and insights.

ROUTE ORDERING NOTE: literal paths (``/insights``, ``/change-requests``)
must be declared BEFORE the parameterised ``/{rubric_id}`` routes,
otherwise FastAPI matches them as a rubric id.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_project_role
from app.db import get_db
from app.exceptions import ValidationError
from app.models import Rubric, RubricCategory, User
from app.schemas import (
    RubricChangeRequestCreate,
    RubricChangeRequestOut,
    RubricCreate,
    RubricInsightOut,
    RubricOut,
)
from app.services import audit_service
from app.services.insight_service import InsightService
from app.services.project_service import ProjectService
from app.services.rubric_service import RubricService

router = APIRouter(prefix="/api/projects/{project_id}/rubrics", tags=["rubrics"])


def _svc(db: Session) -> RubricService:
    return RubricService(db)


def _active_rubric_id(db: Session, project_id: str) -> str:
    rubric = (
        db.query(Rubric)
        .filter(Rubric.project_id == project_id, Rubric.status == "active")
        .order_by(Rubric.version.desc())
        .first()
    )
    if rubric is None:
        raise ValidationError("No active rubric in this project.")
    return rubric.id


class ActivateRequest(BaseModel):
    change_note: str | None = None


class ResolveRequest(BaseModel):
    decision: str
    change_request_id: str | None = None


# ---------------------------------------------------------------------------
# Collection routes (literal paths first)
# ---------------------------------------------------------------------------


@router.get("", response_model=list[RubricOut])
def list_rubrics(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ProjectService(db).get(project_id, user)
    return _svc(db).list_rubrics(project_id)


@router.post("", response_model=RubricOut, status_code=201)
def create_rubric(
    project_id: str,
    data: RubricCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = ProjectService(db).get(project_id, user)
    require_project_role(db, project, user, "lead", "senior_reviewer")
    rubric = _svc(db).create(project_id, data, user.id)
    audit_service.log_action(db, user.id, "rubric.create", "rubric", rubric.id)
    return rubric


@router.get("/versions", response_model=list[RubricOut])
def rubric_versions(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ProjectService(db).get(project_id, user)
    return _svc(db).versions(project_id)


# ---------------------------------------------------------------------------
# Rubric insights
# ---------------------------------------------------------------------------


@router.get("/insights", response_model=list[RubricInsightOut])
def list_insights(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ProjectService(db).get(project_id, user)
    return InsightService(db).list_insights(project_id)


@router.post("/insights/analyze")
def analyze_rubric(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    ProjectService(db).get(project_id, user)
    insights = InsightService(db).analyze_project(project_id)
    return {
        "analyzed": len(insights),
        "insights": [RubricInsightOut.model_validate(i).model_dump(mode="json") for i in insights],
    }


@router.post("/insights/{insight_id}/resolve", response_model=RubricInsightOut)
def resolve_insight(
    project_id: str,
    insight_id: str,
    data: ResolveRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = ProjectService(db).get(project_id, user)
    require_project_role(db, project, user, "lead", "senior_reviewer")
    insight = InsightService(db).resolve_insight(insight_id, data.decision, data.change_request_id)
    audit_service.log_action(
        db, user.id, "rubric.insight_resolved", "rubric_insight", insight_id, {"decision": data.decision}
    )
    return insight


# ---------------------------------------------------------------------------
# Change requests (human approval gate)
# ---------------------------------------------------------------------------


@router.get("/change-requests", response_model=list[RubricChangeRequestOut])
def list_change_requests(
    project_id: str,
    status: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    from app.models import RubricChangeRequest

    ProjectService(db).get(project_id, user)
    q = (
        db.query(RubricChangeRequest)
        .join(Rubric, RubricChangeRequest.rubric_id == Rubric.id)
        .filter(Rubric.project_id == project_id)
    )
    if status:
        q = q.filter(RubricChangeRequest.status == status)
    return q.order_by(RubricChangeRequest.created_at.desc()).all()


@router.post("/change-requests", response_model=RubricChangeRequestOut, status_code=201)
def create_change_request(
    project_id: str,
    data: RubricChangeRequestCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ProjectService(db).get(project_id, user)
    req = _svc(db).create_change_request(
        rubric_id=_active_rubric_id(db, project_id),
        category_id=data.rubric_category_id,
        proposed_changes=data.proposed_changes,
        evidence=None,
        rationale=data.rationale,
        requested_by=user.id,
        source="manual",
        is_ai_generated=False,
    )
    audit_service.log_action(db, user.id, "rubric.change_request", "rubric_change_request", req.id)
    return req


@router.post("/change-requests/from-insight", response_model=RubricChangeRequestOut, status_code=201)
def create_change_request_from_insight(
    project_id: str,
    insight_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Turn a rubric insight into a change request, carrying its evidence."""
    from app.models import RubricInsight

    ProjectService(db).get(project_id, user)
    insight = db.query(RubricInsight).filter(RubricInsight.id == insight_id).first()
    if insight is None:
        from app.exceptions import NotFoundError

        raise NotFoundError("Insight not found.")
    suggestion = insight.suggestion_json or {}
    req = _svc(db).create_change_request(
        rubric_id=_active_rubric_id(db, project_id),
        category_id=insight.rubric_category_id,
        proposed_changes={
            "definition": suggestion.get("recommendation"),
            "guidance": "; ".join(suggestion.get("proposed_improvements") or []),
        },
        evidence=insight.evidence_json,
        rationale=(
            f"{insight.issue_type.replace('_', ' ')} detected on this category "
            f"(sample size {insight.sample_size}). {suggestion.get('recommendation', '')}"
        ),
        requested_by=user.id,
        source="ai_suggested" if insight.source == "ai_assisted" else "insight",
        is_ai_generated=insight.source == "ai_assisted",
    )
    # link insight -> request
    insight.status = "approved"
    db.commit()
    audit_service.log_action(
        db, user.id, "rubric.change_request", "rubric_change_request", req.id, {"from_insight": insight_id}
    )
    return req


@router.post("/change-requests/{request_id}/review", response_model=RubricChangeRequestOut)
def review_change_request(
    project_id: str,
    request_id: str,
    decision: str,
    note: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = ProjectService(db).get(project_id, user)
    require_project_role(db, project, user, "lead", "senior_reviewer")
    req = _svc(db).review_change_request(request_id, decision, user.id, note)
    audit_service.log_action(
        db,
        user.id,
        "rubric.change_approved" if decision == "approved" else "rubric.change_rejected",
        "rubric_change_request",
        request_id,
        {"decision": decision},
    )
    return req


@router.post("/change-requests/{request_id}/apply", response_model=RubricOut)
def apply_change_request(
    project_id: str,
    request_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = ProjectService(db).get(project_id, user)
    require_project_role(db, project, user, "lead", "senior_reviewer")
    new_rubric = _svc(db).apply_change_request(request_id, user.id)
    audit_service.log_action(
        db, user.id, "rubric.version", "rubric", new_rubric.id, {"applied_request": request_id}
    )
    return new_rubric


# ---------------------------------------------------------------------------
# Parameterised rubric routes (declared LAST)
# ---------------------------------------------------------------------------


@router.post("/{rubric_id}/activate", response_model=RubricOut)
def activate_rubric(
    project_id: str,
    rubric_id: str,
    data: ActivateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = ProjectService(db).get(project_id, user)
    require_project_role(db, project, user, "lead", "senior_reviewer")
    rubric = _svc(db).activate(rubric_id, user.id, data.change_note)
    audit_service.log_action(db, user.id, "rubric.version", "rubric", rubric.id, {"version": rubric.version})
    return rubric


@router.post("/{rubric_id}/archive", response_model=RubricOut)
def archive_rubric(
    project_id: str,
    rubric_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = ProjectService(db).get(project_id, user)
    require_project_role(db, project, user, "lead", "senior_reviewer")
    return _svc(db).archive(rubric_id)


@router.get("/{rubric_id}", response_model=RubricOut)
def get_rubric(
    project_id: str, rubric_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    ProjectService(db).get(project_id, user)
    return _svc(db).get(rubric_id)


@router.get("/{rubric_id}/categories", response_model=list)
def rubric_categories(
    project_id: str, rubric_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    ProjectService(db).get(project_id, user)
    cats = (
        db.query(RubricCategory)
        .filter(RubricCategory.rubric_id == rubric_id)
        .order_by(RubricCategory.item_order)
        .all()
    )
    from app.schemas import RubricCategoryOut

    return [RubricCategoryOut.model_validate(c).model_dump(mode="json") for c in cats]
