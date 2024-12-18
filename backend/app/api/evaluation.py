"""Reviewer evaluation workflow: assignments, blinded rating
workspace, drafts, submissions, corrections, and history."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_project_access
from app.db import get_db
from app.exceptions import ForbiddenError, NotFoundError
from app.models import Assignment, EvaluationTask, Project, User
from app.schemas import (
    AssignmentOut,
    RatingDraft,
    RatingHistoryOut,
    RatingOut,
    RatingSubmit,
    RubricOut,
    TaskOut,
)
from app.services import audit_service
from app.services.project_service import ProjectService
from app.services.rating_service import RatingService
from app.services.task_service import TaskService

router = APIRouter(prefix="/api/projects/{project_id}", tags=["evaluation"])


class AssignRequest(BaseModel):
    reviewer_ids: list[str]
    task_ids: list[str] | None = None
    conflict_user_ids: list[str] | None = None


def _project(project_id: str, user: User, db: Session) -> Project:
    project = ProjectService(db).get(project_id, user)
    require_project_access(db, project, user)
    return project


@router.post("/assign", response_model=dict)
def assign_reviewers(
    project_id: str,
    data: AssignRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = _project(project_id, user, db)
    if user.role != "admin" and project.owner_id != user.id:
        from app.auth import require_project_role

        require_project_role(db, project, user, "lead", "senior_reviewer")
    result = TaskService(db).assign_reviewers(
        project, data.reviewer_ids, data.task_ids, data.conflict_user_ids
    )
    audit_service.log_action(
        db,
        user.id,
        "assignment.create",
        "project",
        project_id,
        {"reviewers": data.reviewer_ids, **result},
    )
    return result


@router.get("/assignments", response_model=list[AssignmentOut])
def my_assignments(
    project_id: str,
    status: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _project(project_id, user, db)
    assignments = TaskService(db).reviewer_queue(user.id, project_id, status)
    out = []
    for a in assignments:
        out.append(AssignmentOut.model_validate(a))
    return out


@router.get("/tasks/{task_id}/evaluate", response_model=dict)
def evaluation_workspace(
    project_id: str,
    task_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """The reviewer workspace: task + rubric + own draft/rating.

    Blinding: a reviewer who has NOT yet submitted sees no other
    ratings. After submission they see peers' ratings (standard
    independent-then-reveal design).
    """
    project = _project(project_id, user, db)
    task = TaskService(db).get_task(task_id)
    if task.project_id != project.id:
        raise NotFoundError("Task not found in this project.")

    rating_svc = RatingService(db)
    from app.models import Rubric

    rubric = (
        db.query(Rubric)
        .filter(Rubric.project_id == project.id, Rubric.status == "active")
        .order_by(Rubric.version.desc())
        .first()
    )
    if rubric is None:
        raise NotFoundError("No active rubric. Configure one first.")

    my_rating = rating_svc.my_rating(task_id, user.id)
    submitted = my_rating is not None and my_rating.status == "submitted"
    reviewer_names = {
        u.id: u.full_name
        for u in db.query(User).filter(User.id.in_([r.reviewer_id for r in task.ratings] or ["-"])).all()
    }

    if not submitted:
        # verify assignment
        assignment = (
            db.query(Assignment)
            .filter(Assignment.task_id == task_id, Assignment.reviewer_id == user.id)
            .first()
        )
        if assignment is None and user.role not in {"admin", "senior_reviewer"}:
            raise ForbiddenError("You are not assigned to this task.")
        peers: list = []
    else:
        peers = rating_svc.visible_ratings(task_id, user.id, user.role)

    draft = rating_svc._current_draft(task_id, user.id)
    privileged = user.role in {"admin", "adjudicator", "senior_reviewer"}
    my_assignment = (
        db.query(Assignment).filter(Assignment.task_id == task_id, Assignment.reviewer_id == user.id).first()
    )

    return {
        "task": TaskOut.model_validate(task).model_dump(mode="json"),
        "rubric": RubricOut.model_validate(rubric).model_dump(mode="json"),
        "my_rating": (RatingOut.model_validate(my_rating).model_dump(mode="json") if my_rating else None),
        "my_draft": (RatingOut.model_validate(draft).model_dump(mode="json") if draft else None),
        "submitted": submitted,
        "peer_ratings": [
            {
                "id": r.id,
                "reviewer_id": r.reviewer_id,
                "reviewer_name": reviewer_names.get(r.reviewer_id, r.reviewer_id),
                "scores": r.scores_json,
                "rationale": (r.rationale if privileged or submitted else None),
                "confidence": r.confidence,
                "abstained": r.abstained,
                "version": r.version,
                "submitted_at": r.submitted_at.isoformat() if r.submitted_at else None,
            }
            for r in peers
            if r.id != (my_rating.id if my_rating else None)
        ],
        "blinded": not submitted,
        "assignment_status": my_assignment.status if my_assignment else None,
    }


@router.post("/tasks/{task_id}/draft", response_model=RatingOut)
def save_draft(
    project_id: str,
    task_id: str,
    data: RatingDraft,
    rubric_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _project(project_id, user, db)
    rating = RatingService(db).save_draft(task_id, user.id, data, rubric_id)
    return rating


@router.post("/tasks/{task_id}/submit", response_model=RatingOut)
def submit_rating(
    project_id: str,
    task_id: str,
    data: RatingSubmit,
    rubric_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _project(project_id, user, db)
    rating = RatingService(db).submit_rating(task_id, user.id, data, rubric_id)
    audit_service.log_action(db, user.id, "rating.submit", "rating", rating.id, {"task_id": task_id})
    return rating


@router.post("/ratings/{rating_id}/correct", response_model=RatingOut)
def correct_rating(
    project_id: str,
    rating_id: str,
    data: RatingSubmit,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _project(project_id, user, db)
    rating = RatingService(db).correct_rating(rating_id, user.id, data)
    audit_service.log_action(db, user.id, "rating.corrected", "rating", rating.id)
    return rating


@router.get("/tasks/{task_id}/ratings", response_model=list[RatingOut])
def task_ratings(
    project_id: str,
    task_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Blinding-aware listing: reviewers see peers' ratings only
    after submitting their own; leads/adjudicators/admins always."""
    project = _project(project_id, user, db)
    task = TaskService(db).get_task(task_id)
    if task.project_id != project.id:
        raise NotFoundError("Task not found in this project.")
    return RatingService(db).visible_ratings(task_id, user.id, user.role)


@router.get("/tasks/{task_id}/rating-history", response_model=list[RatingHistoryOut])
def rating_history(
    project_id: str,
    task_id: str,
    reviewer_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _project(project_id, user, db)
    if reviewer_id:
        return RatingService(db).rating_history(task_id, reviewer_id)
    from app.models import Rating

    return (
        db.query(Rating).filter(Rating.task_id == task_id).order_by(Rating.reviewer_id, Rating.version).all()
    )


@router.post("/tasks/{task_id}/reopen")
def reopen_task(
    project_id: str, task_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    project = _project(project_id, user, db)
    if user.role != "admin" and project.owner_id != user.id:
        from app.auth import require_project_role

        require_project_role(db, project, user, "lead", "senior_reviewer")
    task = RatingService(db).reopen_task(task_id)
    audit_service.log_action(db, user.id, "rating.reopen", "task", task_id)
    return {"ok": True, "status": task.status}


@router.get("/queue")
def evaluation_queue(
    project_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """All tasks assigned to this reviewer with rating status."""
    _project(project_id, user, db)

    tasks = (
        db.query(EvaluationTask, Assignment)
        .join(Assignment, Assignment.task_id == EvaluationTask.id)
        .filter(
            EvaluationTask.project_id == project_id,
            Assignment.reviewer_id == user.id,
        )
        .order_by(Assignment.assigned_at.desc())
        .limit(500)
        .all()
    )
    out = []
    for task, _assignment in tasks:
        my = (
            db.query(Assignment)
            .filter(Assignment.task_id == task.id, Assignment.reviewer_id == user.id)
            .first()
        )
        out.append(
            {
                "task_id": task.id,
                "external_id": task.external_id,
                "prompt": task.prompt[:200],
                "model_name": task.model_name,
                "assignment_status": my.status if my else "assigned",
            }
        )
    return out
