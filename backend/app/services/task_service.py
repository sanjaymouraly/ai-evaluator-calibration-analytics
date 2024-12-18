"""Task management, reviewer assignment, workload balancing, blinding."""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from typing import Any

from sqlalchemy.orm import Session

from app.exceptions import ConflictError, NotFoundError, ValidationError
from app.models import (
    Assignment,
    EvaluationTask,
    Project,
)
from app.schemas import TaskCreate


class TaskService:
    def __init__(self, db: Session):
        self.db = db

    def list_tasks(
        self,
        project_id: str,
        status: str | None = None,
        model_name: str | None = None,
        q: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[EvaluationTask]:
        query = self.db.query(EvaluationTask).filter(EvaluationTask.project_id == project_id)
        if status:
            query = query.filter(EvaluationTask.status == status)
        if model_name:
            query = query.filter(EvaluationTask.model_name == model_name)
        if q:
            like = f"%{q}%"
            query = query.filter(EvaluationTask.prompt.ilike(like))
        return query.order_by(EvaluationTask.created_at.desc()).offset(offset).limit(limit).all()

    def get_task(self, task_id: str) -> EvaluationTask:
        task = self.db.query(EvaluationTask).filter(EvaluationTask.id == task_id).first()
        if task is None:
            raise NotFoundError("Task not found.")
        return task

    def create_task(self, project_id: str, data: TaskCreate, user_id: str) -> EvaluationTask:
        task = EvaluationTask(project_id=project_id, **data.model_dump())
        self.db.add(task)
        self.db.commit()
        self.db.refresh(task)
        return task

    def set_gold_label(
        self,
        task_id: str,
        scores: dict[str, Any],
        rationale: str | None,
        approver_id: str,
    ) -> EvaluationTask:
        task = self.get_task(task_id)
        task.gold_label_json = {"scores": scores, "rationale": rationale}
        task.gold_approved_by = approver_id
        task.gold_approved_at = dt.datetime.now(dt.UTC)
        self.db.commit()
        self.db.refresh(task)
        return task

    # ---------------- assignment ----------------
    def assign_reviewers(
        self,
        project: Project,
        reviewer_ids: list[str],
        task_ids: list[str] | None = None,
        conflict_user_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Assign tasks to reviewers with:
        - round-robin workload balancing (least-loaded first)
        - conflict-of-interest avoidance (conflict_user_ids are users
          whose own work appears in the dataset — e.g. model owners)
        - blinding (reviewers never see others' ratings)
        """
        if project.status == "archived":
            raise ConflictError("Cannot assign tasks in an archived project.")
        query = self.db.query(EvaluationTask).filter(EvaluationTask.project_id == project.id)
        if task_ids:
            query = query.filter(EvaluationTask.id.in_(task_ids))
        tasks = query.all()
        if not tasks:
            raise ValidationError("No tasks matched for assignment.")
        if not reviewer_ids:
            raise ValidationError("At least one reviewer must be specified.")

        conflict_user_ids = set(conflict_user_ids or [])
        eligible = [r for r in reviewer_ids if r not in conflict_user_ids]
        if not eligible:
            raise ValidationError("All candidate reviewers have declared conflicts of interest.")

        # current load per reviewer (open assignments)
        load: dict[str, int] = defaultdict(int)
        assignments = self.db.query(Assignment).filter(Assignment.task_id.in_([t.id for t in tasks])).all()
        assigned_pairs: set[tuple[str, str]] = set()
        for a in assignments:
            assigned_pairs.add((a.task_id, a.reviewer_id))
            if a.status in ("assigned", "in_progress"):
                load[a.reviewer_id] += 1

        created = 0
        skipped = 0
        for task in tasks:
            # order reviewers by current load then id for determinism
            order = sorted(eligible, key=lambda r: (load[r], r))
            need = project.min_ratings_per_item
            have = len([a for a in assignments if a.task_id == task.id])
            for reviewer_id in order:
                if have >= need:
                    break
                if (task.id, reviewer_id) in assigned_pairs:
                    continue
                self.db.add(
                    Assignment(
                        task_id=task.id,
                        reviewer_id=reviewer_id,
                        blinded=True,
                    )
                )
                load[reviewer_id] += 1
                have += 1
                created += 1
            skipped += max(0, need - have)
        self.db.commit()
        return {
            "tasks": len(tasks),
            "assignments_created": created,
            "unfilled_slots": skipped,
            "conflicts_excluded": len(reviewer_ids) - len(eligible),
        }

    def unassign(self, assignment_id: str) -> None:
        assignment = self.db.query(Assignment).filter(Assignment.id == assignment_id).first()
        if assignment is None:
            raise NotFoundError("Assignment not found.")
        if assignment.status not in ("assigned",):
            raise ConflictError("Only unstarted assignments can be removed.")
        self.db.delete(assignment)
        self.db.commit()

    def reviewer_queue(
        self, reviewer_id: str, project_id: str | None = None, status: str | None = None
    ) -> list[Assignment]:
        query = (
            self.db.query(Assignment)
            .filter(Assignment.reviewer_id == reviewer_id)
            .join(EvaluationTask, Assignment.task_id == EvaluationTask.id)
        )
        if project_id:
            query = query.filter(EvaluationTask.project_id == project_id)
        if status:
            query = query.filter(Assignment.status == status)
        return query.order_by(Assignment.assigned_at.desc()).all()
