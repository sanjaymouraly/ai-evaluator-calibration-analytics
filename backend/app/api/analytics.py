"""Analytics dashboard endpoints with interactive filters."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_project_access
from app.db import get_db
from app.models import Project, Rating, User
from app.services.analytics_engine import AnalyticsEngine
from app.services.project_service import ProjectService

router = APIRouter(prefix="/api/projects/{project_id}/analytics", tags=["analytics"])


def _engine(db: Session) -> AnalyticsEngine:
    return AnalyticsEngine(db)


def _check(project_id: str, user: User, db: Session) -> Project:
    project = ProjectService(db).get(project_id, user)
    require_project_access(db, project, user)
    return project


@router.get("/dashboard")
def dashboard(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _check(project_id, user, db)
    return _engine(db).dashboard(project_id)


@router.get("/metrics")
def metrics(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _check(project_id, user, db)
    return _engine(db).project_metrics(project_id)


@router.get("/item-agreement")
def item_agreement(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _check(project_id, user, db)
    return _engine(db).item_agreement(project_id)


@router.get("/pairwise-agreement")
def pairwise(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _check(project_id, user, db)
    return _engine(db).pairwise_reviewer_agreement(project_id)


@router.get("/reviewer-bias")
def reviewer_bias(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _check(project_id, user, db)
    return _engine(db).reviewer_bias(project_id)


@router.get("/accuracy-vs-gold")
def accuracy_gold(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _check(project_id, user, db)
    return _engine(db).accuracy_vs_gold(project_id)


@router.get("/distributions")
def distributions(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _check(project_id, user, db)
    return _engine(db).score_distributions(project_id)


@router.get("/confusion-matrix")
def confusion(
    project_id: str,
    category_key: str = Query(...),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _check(project_id, user, db)
    return _engine(db).confusion_matrix(project_id, category_key)


@router.get("/reviewer-trend/{reviewer_id}")
def reviewer_trend(
    project_id: str,
    reviewer_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _check(project_id, user, db)
    return _engine(db).reviewer_reliability_trend(project_id, reviewer_id)


@router.get("/activity-trend")
def activity_trend(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Rating submission volume over time (for trend charts)."""
    _check(project_id, user, db)
    from sqlalchemy import func

    from app.models import EvaluationTask

    rows = (
        db.query(
            func.strftime("%Y-%m-%d", Rating.submitted_at).label("day"),
            func.count(Rating.id).label("count"),
        )
        .join(EvaluationTask, Rating.task_id == EvaluationTask.id)
        .filter(
            EvaluationTask.project_id == project_id,
            Rating.submitted_at.isnot(None),
        )
        .group_by("day")
        .order_by("day")
        .all()
    )
    return [{"date": r.day, "ratings": r.count} for r in rows]


@router.get("/filters")
def filter_options(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    """Available filter dimensions for the dashboard."""
    _check(project_id, user, db)
    from app.models import (
        EvaluationTask,
        ProjectMember,
        Rubric,
        RubricCategory,
    )

    reviewers = (
        db.query(ProjectMember.user_id).filter(ProjectMember.project_id == project_id).distinct().all()
    )
    models = (
        db.query(EvaluationTask.model_name).filter(EvaluationTask.project_id == project_id).distinct().all()
    )
    rubric = db.query(Rubric).filter(Rubric.project_id == project_id, Rubric.status == "active").first()
    cats = []
    if rubric:
        cats = (
            db.query(RubricCategory)
            .filter(RubricCategory.rubric_id == rubric.id)
            .order_by(RubricCategory.item_order)
            .all()
        )
    return {
        "reviewers": [r[0] for r in reviewers],
        "models": [m[0] for m in models if m[0]],
        "categories": [{"key": c.key, "name": c.name} for c in cats],
    }
