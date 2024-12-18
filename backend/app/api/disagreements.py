"""Disagreement detection, queue, drill-down, and prioritization."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_project_access
from app.db import get_db
from app.models import Project, User
from app.schemas import DisagreementOut, TaskOut
from app.services import audit_service
from app.services.detection_service import DetectionService
from app.services.project_service import ProjectService

router = APIRouter(prefix="/api/projects/{project_id}", tags=["disagreements"])


def _project(project_id: str, user: User, db: Session) -> Project:
    project = ProjectService(db).get(project_id, user)
    require_project_access(db, project, user)
    return project


@router.post("/disagreements/scan")
def scan_disagreements(
    project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    project = _project(project_id, user, db)
    counts = DetectionService(db).scan_project(project.id)
    audit_service.log_action(db, user.id, "disagreement.scan", "project", project_id, counts)
    return {"scanned": True, "detected_by_kind": counts}


@router.get("/disagreements", response_model=list[DisagreementOut])
def list_disagreements(
    project_id: str,
    status: str | None = None,
    kind: str | None = None,
    category_key: str | None = None,
    min_severity: float | None = None,
    severity_class: str | None = None,
    limit: int = Query(100, le=500),
    offset: int = 0,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _project(project_id, user, db)
    from app.models import Disagreement

    q = db.query(Disagreement).filter(Disagreement.project_id == project_id)
    if status:
        q = q.filter(Disagreement.status == status)
    if kind:
        q = q.filter(Disagreement.kind == kind)
    if category_key:
        q = q.filter(Disagreement.category_key == category_key)
    if min_severity is not None:
        q = q.filter(Disagreement.severity_score >= min_severity)
    if severity_class:
        q = q.filter(Disagreement.severity_class == severity_class)
    return q.order_by(Disagreement.priority_score.desc()).offset(offset).limit(limit).all()


@router.get("/disagreements/summary")
def disagreement_summary(
    project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    _project(project_id, user, db)
    return DetectionService(db).project_disagreement_summary(project_id)


@router.get("/disagreements/{disagreement_id}")
def disagreement_detail(
    disagreement_id: str,
    project_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _project(project_id, user, db)
    from app.models import Disagreement, EvaluationTask, Rating

    dg = db.query(Disagreement).filter(Disagreement.id == disagreement_id).first()
    if dg is None or dg.project_id != project_id:
        from app.exceptions import NotFoundError

        raise NotFoundError("Disagreement not found.")
    task = db.query(EvaluationTask).filter(EvaluationTask.id == dg.task_id).first()
    # Only current rating versions (history is available separately).
    ratings = (
        db.query(Rating)
        .filter(
            Rating.task_id == dg.task_id,
            Rating.status == "submitted",
            Rating.is_current.is_(True),
        )
        .all()
    )
    from app.models import User

    reviewer_names = {u.id: u.full_name for u in db.query(User).all()}
    return {
        "disagreement": DisagreementOut.model_validate(dg).model_dump(mode="json"),
        "task": TaskOut.model_validate(task).model_dump(mode="json") if task else None,
        "ratings": [
            {
                "id": r.id,
                "reviewer_id": r.reviewer_id,
                "reviewer_name": reviewer_names.get(r.reviewer_id, r.reviewer_id),
                "scores": r.scores_json,
                "rationale": r.rationale,
                "evidence": r.evidence,
                "confidence": r.confidence,
                "abstained": r.abstained,
                "version": r.version,
                "submitted_at": r.submitted_at,
            }
            for r in ratings
        ],
        "severity_formula": DetectionService.SEVERITY_FORMULA,
    }


@router.post("/disagreements/{disagreement_id}/status", response_model=DisagreementOut)
def set_disagreement_status(
    project_id: str,
    disagreement_id: str,
    status: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _project(project_id, user, db)
    from app.models import Disagreement

    if status not in {"open", "in_review", "resolved", "dismissed"}:
        from app.exceptions import ValidationError

        raise ValidationError("Invalid status.")
    dg = db.query(Disagreement).filter(Disagreement.id == disagreement_id).first()
    if dg is None:
        from app.exceptions import NotFoundError

        raise NotFoundError("Disagreement not found.")
    dg.status = status
    db.commit()
    audit_service.log_action(
        db, user.id, "disagreement.status", "disagreement", disagreement_id, {"status": status}
    )
    return dg
