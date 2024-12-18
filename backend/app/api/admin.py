"""Admin endpoints: health, demo data seed/reset, audit log,
jobs, and system info."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.config import settings
from app.db import get_db
from app.models import User
from app.schemas import AuditLogOut, JobOut
from app.seed.synthetic import build_demo_data, reset_demo_data
from app.services import audit_service
from app.services.job_service import list_jobs

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/health")
def health():
    return {"status": "ok", "version": settings.app_version}


@router.get("/ready")
def ready(db: Session = Depends(get_db)):
    try:
        db.execute(__import__("sqlalchemy").text("SELECT 1"))
        return {"status": "ready"}
    except Exception as exc:  # noqa: BLE001
        from fastapi.responses import JSONResponse

        return JSONResponse({"status": "error", "detail": str(exc)}, status_code=503)


@router.post("/seed-demo")
def seed_demo(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    result = build_demo_data(db, admin_id=user.id)
    audit_service.log_action(db, user.id, "demo.seed", "project", result["project_id"])
    return result


@router.post("/reset-demo")
def reset_demo(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    removed = reset_demo_data(db)
    return {"removed_demo_users": removed}


@router.get("/audit-log", response_model=list[AuditLogOut])
def audit_log(
    limit: int = Query(100, le=500),
    user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    from app.models import AuditLog

    return db.query(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit).all()


@router.get("/jobs", response_model=list[JobOut])
def jobs(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    return list_jobs(db)


@router.get("/stats")
def system_stats(user: User = Depends(require_admin), db: Session = Depends(get_db)):
    from app.models import (
        CalibrationSession,
        Disagreement,
        EvaluationTask,
        Project,
        Rating,
        Rubric,
        User,
    )

    return {
        "users": db.query(User).count(),
        "projects": db.query(Project).count(),
        "tasks": db.query(EvaluationTask).count(),
        "ratings": db.query(Rating).count(),
        "disagreements": db.query(Disagreement).count(),
        "calibration_sessions": db.query(CalibrationSession).count(),
        "rubric_versions": db.query(Rubric).count(),
        "database_url_kind": "sqlite" if settings.sqlite_mode else "postgresql",
    }
