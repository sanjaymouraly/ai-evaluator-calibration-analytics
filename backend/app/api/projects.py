"""Project CRUD, membership, and progress endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.auth import get_current_user
from app.db import get_db
from app.models import EvaluationTask, User
from app.schemas import (
    MemberAdd,
    ProjectCreate,
    ProjectMemberOut,
    ProjectOut,
    ProjectUpdate,
    UserOut,
)
from app.services import audit_service
from app.services.project_service import ProjectService

router = APIRouter(prefix="/api/projects", tags=["projects"])


def svc(db: Session) -> ProjectService:
    return ProjectService(db)


@router.get("", response_model=list[ProjectOut])
def list_projects(
    include_archived: bool = False,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return svc(db).list_projects(user, include_archived=include_archived)


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(
    data: ProjectCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = svc(db).create(data, user)
    audit_service.log_action(db, user.id, "project.create", "project", project.id)
    return project


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return svc(db).get(project_id, user)


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: str,
    data: ProjectUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = svc(db).update(project_id, data, user)
    audit_service.log_action(db, user.id, "project.update", "project", project_id)
    return project


@router.post("/{project_id}/archive", response_model=ProjectOut)
def archive_project(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return svc(db).archive(project_id, user)


@router.get("/{project_id}/progress")
def project_progress(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = svc(db).get(project_id, user)
    return svc(db).project_progress(project)


@router.get("/{project_id}/members", response_model=list[ProjectMemberOut])
def list_members(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return svc(db).list_members(project_id, user)


@router.post("/{project_id}/members", response_model=ProjectMemberOut, status_code=201)
def add_member(
    project_id: str,
    data: MemberAdd,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    member = svc(db).add_member(project_id, data.user_id, data.role_on_project, user)
    audit_service.log_action(
        db, user.id, "membership.grant", "project_member", member.id, {"user_id": data.user_id}
    )
    return member


@router.delete("/{project_id}/members/{user_id}", status_code=204)
def remove_member(
    project_id: str, user_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    svc(db).remove_member(project_id, user_id, user)
    audit_service.log_action(db, user.id, "membership.revoke", "project_member", user_id)


@router.get("/{project_id}/potential-reviewers", response_model=list[UserOut])
def potential_reviewers(
    project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    svc(db).get(project_id, user)  # permission check
    return db.query(User).filter(User.is_active.is_(True)).all()


@router.get("/{project_id}/datasets-summary")
def datasets_summary(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    project = svc(db).get(project_id, user)
    from app.models import Dataset, EvaluationTask

    datasets = db.query(Dataset).filter(Dataset.project_id == project.id).all()
    out = []
    for d in datasets:
        out.append(
            {
                "id": d.id,
                "name": d.name,
                "source_file_name": d.source_file_name,
                "source_format": d.source_format,
                "created_at": d.created_at,
                "item_count": db.query(EvaluationTask).filter(EvaluationTask.dataset_id == d.id).count(),
            }
        )
    return out


@router.get("/{project_id}/models")
def models_in_project(project_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    svc(db).get(project_id, user)
    from sqlalchemy import distinct

    rows = (
        db.query(distinct(EvaluationTask.model_name))
        .filter(EvaluationTask.project_id == project_id)
        .filter(EvaluationTask.model_name.isnot(None))
        .all()
    )
    return [r[0] for r in rows]
