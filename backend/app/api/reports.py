"""Report generation & export endpoints (CSV/JSON/PDF).

Report generation is a background job; the client polls status
and downloads the produced file.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_project_access
from app.db import get_db
from app.models import Project, Report, User
from app.schemas import JobOut, ReportOut, ReportRequest
from app.services import audit_service
from app.services.job_service import enqueue
from app.services.project_service import ProjectService
from app.services.report_service import (
    ReportService,
    register_report,
    save_report_file,
)

router = APIRouter(prefix="/api/projects/{project_id}", tags=["reports"])


def _check(project_id: str, user: User, db: Session) -> Project:
    project = ProjectService(db).get(project_id, user)
    require_project_access(db, project, user)
    return project


def _run_report_job(db: Session, payload: dict[str, Any]) -> dict:
    project_id = payload["project_id"]
    fmt = payload["format"]
    title = payload["title"]
    service = ReportService(db)
    if fmt == "csv":
        content = service.to_csv(project_id)
    elif fmt == "json":
        content = service.to_json(project_id)
    elif fmt == "pdf":
        content = service.to_pdf(project_id, title)
    else:
        raise ValueError(f"Unsupported format: {fmt}")
    path = save_report_file(project_id, fmt, content)
    report = register_report(db, project_id, title, fmt, payload.get("filters"), path, payload.get("user_id"))
    return {"report_id": report.id, "path": path}


from app.services.job_service import register_handler  # noqa: E402

register_handler("report_generation", _run_report_job)


@router.post("/reports", response_model=JobOut, status_code=202)
def generate_report(
    project_id: str,
    data: ReportRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _check(project_id, user, db)
    job = enqueue(
        db,
        "report_generation",
        {
            "project_id": project_id,
            "format": data.report_format,
            "title": data.title,
            "filters": data.filters,
            "user_id": user.id,
        },
        created_by=user.id,
    )
    audit_service.log_action(
        db,
        user.id,
        "report.generate",
        "report",
        job.id,
        {
            "format": data.report_format,
        },
    )
    return job


@router.get("/reports", response_model=list[ReportOut])
def list_reports(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    _check(project_id, user, db)
    return db.query(Report).filter(Report.project_id == project_id).order_by(Report.created_at.desc()).all()


@router.get("/reports/{report_id}/download")
def download_report(
    report_id: str, project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    _check(project_id, user, db)
    report = db.query(Report).filter(Report.id == report_id).first()
    if report is None:
        raise HTTPException(status_code=404, detail="Report not found.")
    import os

    if not report.file_path or not os.path.exists(report.file_path):
        raise HTTPException(status_code=404, detail="Report file missing.")
    media_types = {"csv": "text/csv", "json": "application/json", "pdf": "application/pdf"}
    return FileResponse(
        report.file_path,
        media_type=media_types.get(report.report_format, "application/octet-stream"),
        filename=f"{report.title.replace(' ', '_')}.{report.report_format}",
    )


@router.get("/export/ratings")
def export_ratings_csv(
    project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    """Full ratings export for interoperability."""
    _check(project_id, user, db)
    import csv
    import io

    from app.models import EvaluationTask, Rating

    rows = (
        db.query(Rating, EvaluationTask)
        .join(EvaluationTask, Rating.task_id == EvaluationTask.id)
        .filter(EvaluationTask.project_id == project_id)
        .all()
    )
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "task_external_id",
            "reviewer_id",
            "version",
            "status",
            "scores_json",
            "rationale",
            "confidence",
            "abstained",
            "submitted_at",
            "rubric_version_id",
        ]
    )
    for rating, task in rows:
        import json

        writer.writerow(
            [
                task.external_id,
                rating.reviewer_id,
                rating.version,
                rating.status,
                json.dumps(rating.scores_json or {}),
                (rating.rationale or "")[:1000],
                rating.confidence,
                rating.abstained,
                rating.submitted_at,
                rating.rubric_version_id,
            ]
        )
    return Response(content=buf.getvalue(), media_type="text/csv")
