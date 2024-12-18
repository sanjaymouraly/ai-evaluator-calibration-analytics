"""Adjudication & consensus workflow endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import get_current_user, require_project_access
from app.db import get_db
from app.models import Project, User
from app.schemas import (
    AdjudicationCreate,
    AdjudicationOut,
    AdjudicationVoteCreate,
    TaskOut,
)
from app.services import audit_service
from app.services.adjudication_service import AdjudicationService
from app.services.project_service import ProjectService

router = APIRouter(prefix="/api/projects/{project_id}", tags=["adjudication"])


def _project(project_id: str, user: User, db: Session) -> Project:
    project = ProjectService(db).get(project_id, user)
    require_project_access(db, project, user)
    return project


@router.post("/adjudications", response_model=AdjudicationOut, status_code=201)
def create_adjudication(
    project_id: str,
    data: AdjudicationCreate | None = None,
    disagreement_id: str | None = None,
    task_id: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    project = _project(project_id, user, db)
    if user.role != "admin" and project.owner_id != user.id:
        from app.auth import require_project_role

        require_project_role(db, project, user, "lead", "adjudicator")
    svc = AdjudicationService(db)
    adj = svc.create_adjudication(
        disagreement_id=disagreement_id,
        task_id=task_id or "",
        adjudicator_id=user.id,
        strategy=None,
    )
    audit_service.log_action(db, user.id, "adjudication.create", "adjudication", adj.id)
    return adj


@router.get("/adjudications", response_model=list[AdjudicationOut])
def list_adjudications(
    project_id: str,
    status: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _project(project_id, user, db)
    return AdjudicationService(db).list_for_project(project_id, status)


@router.get("/adjudications/{adjudication_id}", response_model=dict)
def adjudication_detail(
    project_id: str,
    adjudication_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _project(project_id, user, db)
    from app.models import Adjudication

    adj = db.query(Adjudication).filter(Adjudication.id == adjudication_id).first()
    if adj is None:
        from app.exceptions import NotFoundError

        raise NotFoundError("Adjudication not found.")
    svc = AdjudicationService(db)
    from app.models import EvaluationTask, Rating

    task = db.query(EvaluationTask).filter(EvaluationTask.id == adj.task_id).first()
    # Only current versions — adjudicators must not see stale/superseded
    # rating rows (the full history is available via rating-history).
    ratings = (
        db.query(Rating)
        .filter(
            Rating.task_id == adj.task_id,
            Rating.status == "submitted",
            Rating.is_current.is_(True),
        )
        .all()
    )
    reviewer_names = {u.id: u.full_name for u in db.query(User).all()}
    consensus = svc.compute_consensus(ProjectService(db).get(project_id, user), task)
    return {
        "adjudication": AdjudicationOut.model_validate(adj).model_dump(mode="json"),
        "task": TaskOut.model_validate(task).model_dump(mode="json") if task else None,
        "ratings": [
            {
                "id": r.id,
                "reviewer_name": reviewer_names.get(r.reviewer_id, r.reviewer_id),
                "scores": r.scores_json,
                "rationale": r.rationale,
                "confidence": r.confidence,
                "abstained": r.abstained,
            }
            for r in ratings
        ],
        "consensus": consensus,
        "votes": [
            {"user_id": v.user_id, "decision": v.decision_json, "rationale": v.rationale} for v in adj.votes
        ],
    }


@router.post("/adjudications/{adjudication_id}/vote", response_model=dict)
def adjudicate_vote(
    project_id: str,
    adjudication_id: str,
    data: AdjudicationVoteCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _project(project_id, user, db)
    vote = AdjudicationService(db).record_vote(adjudication_id, user.id, data.decision, data.rationale)
    return {"vote_id": vote.id}


class FinalizeRequest(BaseModel):
    decision: dict
    rationale: str


@router.post("/adjudications/{adjudication_id}/finalize", response_model=AdjudicationOut)
def finalize_adjudication(
    project_id: str,
    adjudication_id: str,
    data: FinalizeRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _project(project_id, user, db)
    adj = AdjudicationService(db).finalize(adjudication_id, user.id, data.decision, data.rationale)
    audit_service.log_action(db, user.id, "adjudication.decide", "adjudication", adjudication_id)
    return adj


@router.post("/adjudications/{adjudication_id}/escalate", response_model=AdjudicationOut)
def escalate_adjudication(
    project_id: str,
    adjudication_id: str,
    reason: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _project(project_id, user, db)
    return AdjudicationService(db).escalate(adjudication_id, reason)


@router.post("/adjudications/{adjudication_id}/reopen", response_model=AdjudicationOut)
def reopen_adjudication(
    project_id: str,
    adjudication_id: str,
    reason: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _project(project_id, user, db)
    adj = AdjudicationService(db).reopen(adjudication_id, reason)
    audit_service.log_action(db, user.id, "adjudication.reopen", "adjudication", adjudication_id)
    return adj


@router.get("/tasks/{task_id}/consensus")
def task_consensus(
    project_id: str, task_id: str, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    _project(project_id, user, db)
    from app.models import EvaluationTask

    task = db.query(EvaluationTask).filter(EvaluationTask.id == task_id).first()
    if task is None:
        from app.exceptions import NotFoundError

        raise NotFoundError("Task not found.")
    return AdjudicationService(db).compute_consensus(ProjectService(db).get(project_id, user), task)
