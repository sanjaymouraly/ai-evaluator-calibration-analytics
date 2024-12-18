"""Calibration session endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_project_access
from app.db import get_db
from app.models import Project, User
from app.schemas import (
    CalibrationAttemptOut,
    CalibrationSessionCreate,
    CalibrationSessionOut,
)
from app.services.calibration_service import CalibrationService
from app.services.project_service import ProjectService

router = APIRouter(prefix="/api/projects/{project_id}/calibration", tags=["calibration"])


class AssessmentPayload(BaseModel):
    session_id: str
    phase: str
    item_scores: dict[str, dict[str, Any]]


def _project(project_id: str, user: User, db: Session) -> Project:
    project = ProjectService(db).get(project_id, user)
    require_project_access(db, project, user)
    return project


@router.post("/sessions", response_model=CalibrationSessionOut)
def create_session(
    project_id: str,
    data: CalibrationSessionCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = _project(project_id, user, db)
    session = CalibrationService(db).create_session(
        project.id,
        data.name,
        data.description,
        data.task_ids,
        data.pass_threshold_kappa,
        data.pass_threshold_accuracy,
        user.id,
    )
    return session


@router.get("/sessions", response_model=list[CalibrationSessionOut])
def list_sessions(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _project(project_id, user, db)
    return CalibrationService(db).list_sessions(project_id)


@router.post("/assess", response_model=CalibrationAttemptOut)
def run_assessment(
    project_id: str,
    data: AssessmentPayload,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _project(project_id, user, db)
    return CalibrationService(db).run_assessment(data.session_id, user.id, data.phase, data.item_scores)


@router.get("/sessions/{session_id}/progress")
def calibration_progress(
    project_id: str, session_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    _project(project_id, user, db)
    from app.models import CalibrationAttempt, CalibrationSession

    session = db.query(CalibrationSession).filter(CalibrationSession.id == session_id).first()
    if session is None:
        from app.exceptions import NotFoundError

        raise NotFoundError("Session not found.")
    summary = CalibrationService(db).reviewer_progress(session_id, user.id)
    all_attempts = db.query(CalibrationAttempt).filter(CalibrationAttempt.session_id == session_id).all()
    return {
        "session": CalibrationSessionOut.model_validate(session).model_dump(mode="json"),
        "mine": summary,
        "all": [CalibrationAttemptOut.model_validate(a).model_dump(mode="json") for a in all_attempts],
    }


@router.get("/sessions/{session_id}/summary")
def calibration_summary(
    project_id: str, session_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    _project(project_id, user, db)
    from app.services.analytics_engine import AnalyticsEngine

    return AnalyticsEngine(db).calibration_summary(session_id)
