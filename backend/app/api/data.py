"""Dataset import and task management endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_project_access
from app.config import settings
from app.db import get_db
from app.exceptions import ValidationError
from app.models import Project, User
from app.schemas import (
    GoldLabelSet,
    ImportRequest,
    ImportResult,
    TaskCreate,
    TaskOut,
)
from app.services import audit_service
from app.services.import_service import ImportService
from app.services.project_service import ProjectService
from app.services.task_service import TaskService

router = APIRouter(prefix="/api/projects/{project_id}", tags=["data"])


def _project(project_id: str, user: User, db: Session) -> Project:
    project = ProjectService(db).get(project_id, user)
    require_project_access(db, project, user)
    return project


@router.post("/import", response_model=ImportResult)
def import_dataset(
    project_id: str,
    data: ImportRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = _project(project_id, user, db)
    if len(data.content.encode("utf-8")) > settings.max_upload_mb * 1024 * 1024:
        raise ValidationError(f"Upload exceeds {settings.max_upload_mb} MB.")
    service = ImportService(db)
    result = service.import_dataset(
        project=project,
        name=data.filename.rsplit(".", 1)[0],
        filename=data.filename,
        file_format=data.file_format,
        content=data.content,
        mapping=data.mapping,
        dry_run=data.dry_run,
        created_by=user.id,
    )
    if not data.dry_run:
        audit_service.log_action(
            db,
            user.id,
            "dataset.import",
            "dataset",
            result.dataset_id,
            {"valid_rows": result.valid_rows, "errors": result.error_rows},
        )
    return result


@router.post("/import/mapping")
def infer_mapping(
    project_id: str,
    data: ImportRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _project(project_id, user, db)
    service = ImportService(db)
    rows = service.parse(data.filename, data.file_format, data.content)
    columns = list(rows[0].keys()) if rows else []
    return {"columns": columns, "inferred": service.infer_mapping(columns)}


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks(
    project_id: str,
    status: str | None = None,
    model_name: str | None = None,
    q: str | None = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _project(project_id, user, db)
    return TaskService(db).list_tasks(
        project_id, status=status, model_name=model_name, q=q, limit=limit, offset=offset
    )


@router.get("/tasks/{task_id}", response_model=TaskOut)
def get_task(
    project_id: str, task_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    _project(project_id, user, db)
    task = TaskService(db).get_task(task_id)
    if task.project_id != project_id:
        raise ValidationError("Task does not belong to this project.")
    return task


@router.post("/tasks", response_model=TaskOut, status_code=201)
def create_task(
    project_id: str, data: TaskCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    _project(project_id, user, db)
    task = TaskService(db).create_task(project_id, data, user.id)
    audit_service.log_action(db, user.id, "task.create", "task", task.id)
    return task


@router.post("/tasks/{task_id}/gold-label")
def set_gold_label(
    project_id: str,
    task_id: str,
    data: GoldLabelSet,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = _project(project_id, user, db)
    if user.role != "admin" and project.owner_id != user.id:
        from app.auth import require_project_role

        require_project_role(db, project, user, "lead", "senior_reviewer")
    task = TaskService(db).set_gold_label(task_id, data.scores, data.rationale, user.id)
    audit_service.log_action(db, user.id, "gold_label.set", "task", task_id)
    return {"ok": True, "task_id": task.id, "gold_approved_by": user.id}
