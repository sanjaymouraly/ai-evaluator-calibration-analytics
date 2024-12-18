"""Rating lifecycle: drafts, submissions, immutability, corrections,
blinding, abstentions, and controlled reopening.

Invariants:
- A submitted rating is NEVER updated in place. Corrections append a
  new version row; the previous row stays as history (is_current flips).
- Reviewers cannot see other reviewers' scores before submitting
  (blinding enforced at the API layer).
- Scores are validated against the rubric version they reference.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy.orm import Session

from app.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.models import Assignment, EvaluationTask, Rating, Rubric
from app.schemas import RatingDraft, RatingSubmit


class RatingService:
    def __init__(self, db: Session):
        self.db = db

    # ---------------- validation ----------------
    def validate_scores(self, scores: dict[str, Any], rubric: Rubric) -> tuple[bool, list[str]]:
        """Validate scores against a rubric's categories and scales."""
        errors: list[str] = []
        cats = {c.key: c for c in rubric.categories} if rubric else {}
        for key, value in scores.items():
            cat = cats.get(key)
            if cat is None:
                errors.append(f"unknown rubric category: {key}")
                continue
            if cat.scale_type == "categorical":
                valid = {o["value"] for o in (cat.options_json or [])}
                if value not in valid:
                    errors.append(f"{key}: '{value}' is not a valid category option {sorted(valid)}")
            elif cat.scale_type == "ordinal":
                valid = {o["value"] for o in (cat.options_json or [])}
                if value not in valid:
                    errors.append(f"{key}: {value} is not one of the ordered options {sorted(valid)}")
            else:  # numerical
                try:
                    num = float(value)
                except (TypeError, ValueError):
                    errors.append(f"{key}: '{value}' is not numeric")
                    continue
                if cat.min_value is not None and num < cat.min_value:
                    errors.append(f"{key}: {num} below minimum {cat.min_value}")
                if cat.max_value is not None and num > cat.max_value:
                    errors.append(f"{key}: {num} above maximum {cat.max_value}")
        missing = set(cats) - set(scores)
        if missing:
            errors.append(f"missing scores for categories: {sorted(missing)}")
        return (len(errors) == 0, errors)

    # ---------------- drafts ----------------
    def save_draft(self, task_id: str, reviewer_id: str, data: RatingDraft, rubric_id: str) -> Rating:
        self._task_or_404(task_id)
        rubric = self._rubric_or_404(rubric_id)
        if data.abstained:
            raise ValidationError("Abstentions must be submitted, not saved as drafts.")
        draft = self._current_draft(task_id, reviewer_id)
        if draft is None:
            draft = Rating(
                task_id=task_id,
                reviewer_id=reviewer_id,
                rubric_version_id=rubric.id,
                status="draft",
            )
            self.db.add(draft)
        draft.scores_json = data.scores
        draft.rationale = data.rationale
        draft.evidence = data.evidence
        draft.confidence = data.confidence
        self.db.commit()
        self.db.refresh(draft)
        return draft

    def _current_draft(self, task_id: str, reviewer_id: str) -> Rating | None:
        return (
            self.db.query(Rating)
            .filter(
                Rating.task_id == task_id,
                Rating.reviewer_id == reviewer_id,
                Rating.status == "draft",
            )
            .order_by(Rating.version.desc())
            .first()
        )

    # ---------------- submission ----------------
    def submit_rating(self, task_id: str, reviewer_id: str, data: RatingSubmit, rubric_id: str) -> Rating:
        task = self._task_or_404(task_id)
        rubric = self._rubric_or_404(rubric_id)

        if data.abstained:
            if not data.rationale:
                raise ValidationError("Abstentions require a rationale.")
            if data.scores:
                raise ValidationError("Abstained ratings must not include scores.")

        if not data.abstained:
            valid, errors = self.validate_scores(data.scores, rubric)
            if not valid:
                raise ValidationError("; ".join(errors))
            if data.confidence is not None and not (0.0 <= data.confidence <= 1.0):
                raise ValidationError("confidence must be between 0 and 1.")

        # idempotency: resubmitting identical content returns existing
        existing = self._current_submitted(task_id, reviewer_id)
        if existing is not None:
            raise ConflictError(
                "Rating already submitted. Use the correction endpoint to append a new version."
            )

        # autosave draft is superseded by the submission
        draft = self._current_draft(task_id, reviewer_id)
        if draft is not None:
            self.db.delete(draft)
            self.db.flush()  # ensure the draft is gone before numbering

        # Next version = highest existing version + 1 (history-safe:
        # never reuses a version number even if rows were deleted).
        from sqlalchemy import func

        max_version = (
            self.db.query(func.max(Rating.version))
            .filter(Rating.task_id == task_id, Rating.reviewer_id == reviewer_id)
            .scalar()
        ) or 0
        rating = Rating(
            task_id=task_id,
            reviewer_id=reviewer_id,
            rubric_version_id=rubric.id,
            version=max_version + 1,
            is_current=True,
            status="submitted",
            scores_json=None if data.abstained else data.scores,
            rationale=data.rationale,
            evidence=data.evidence,
            confidence=data.confidence,
            abstained=data.abstained,
            submitted_at=dt.datetime.now(dt.UTC),
        )
        self.db.add(rating)
        self._mark_assignment_complete(task_id, reviewer_id)
        self._update_task_status(task)
        self.db.commit()
        self.db.refresh(rating)
        return rating

    def _current_submitted(self, task_id: str, reviewer_id: str) -> Rating | None:
        return (
            self.db.query(Rating)
            .filter(
                Rating.task_id == task_id,
                Rating.reviewer_id == reviewer_id,
                Rating.status == "submitted",
                Rating.is_current.is_(True),
            )
            .first()
        )

    # ---------------- corrections (versioned, never overwritten) ----------------
    def correct_rating(self, rating_id: str, reviewer_id: str, data: RatingSubmit) -> Rating:
        original = self.db.query(Rating).filter(Rating.id == rating_id).first()
        if original is None:
            raise NotFoundError("Rating not found.")
        if original.reviewer_id != reviewer_id:
            raise ForbiddenError("You can only correct your own ratings.")
        if original.status != "submitted":
            raise ConflictError("Only submitted ratings can be corrected.")
        task = self._task_or_404(original.task_id)
        if task.status == "adjudicated":
            raise ConflictError("Task is adjudicated. Reopen it before correcting ratings.")
        original.is_current = False
        rating = Rating(
            task_id=original.task_id,
            reviewer_id=reviewer_id,
            rubric_version_id=original.rubric_version_id,
            version=original.version + 1,
            is_current=True,
            status="submitted",
            scores_json=data.scores,
            rationale=data.rationale,
            evidence=data.evidence,
            confidence=data.confidence,
            abstained=data.abstained,
            submitted_at=dt.datetime.now(dt.UTC),
        )
        self.db.add(rating)
        self._update_task_status(task)
        self.db.commit()
        self.db.refresh(rating)
        return rating

    # ---------------- queries (blinding-aware) ----------------
    def my_rating(self, task_id: str, reviewer_id: str) -> Rating | None:
        return self._current_submitted(task_id, reviewer_id) or self._current_draft(task_id, reviewer_id)

    def visible_ratings(self, task_id: str, viewer_id: str, viewer_role: str) -> list[Rating]:
        ratings = (
            self.db.query(Rating)
            .filter(
                Rating.task_id == task_id,
                Rating.status == "submitted",
                Rating.is_current.is_(True),
            )
            .order_by(Rating.created_at.asc())
            .all()
        )
        if viewer_role in {"admin", "adjudicator", "senior_reviewer"}:
            return ratings
        mine = next((r for r in ratings if r.reviewer_id == viewer_id), None)
        if mine is None:
            # Blinded: reviewer has not submitted — sees nobody's ratings.
            return []
        return ratings  # submitted → unblinded

    def rating_history(self, task_id: str, reviewer_id: str) -> list[Rating]:
        return (
            self.db.query(Rating)
            .filter(Rating.task_id == task_id, Rating.reviewer_id == reviewer_id)
            .order_by(Rating.version.asc())
            .all()
        )

    def reopen_task(self, task_id: str) -> EvaluationTask:
        task = self._task_or_404(task_id)
        task.status = "in_progress"
        self.db.commit()
        self.db.refresh(task)
        return task

    # ---------------- helpers ----------------
    def _task_or_404(self, task_id: str) -> EvaluationTask:
        task = self.db.query(EvaluationTask).filter(EvaluationTask.id == task_id).first()
        if task is None:
            raise NotFoundError("Task not found.")
        return task

    def _rubric_or_404(self, rubric_id: str) -> Rubric:
        rubric = self.db.query(Rubric).filter(Rubric.id == rubric_id).first()
        if rubric is None:
            raise NotFoundError("Rubric not found.")
        return rubric

    def _mark_assignment_complete(self, task_id: str, reviewer_id: str) -> None:
        assignment = (
            self.db.query(Assignment)
            .filter(Assignment.task_id == task_id, Assignment.reviewer_id == reviewer_id)
            .first()
        )
        if assignment is not None:
            assignment.status = "completed"
            assignment.completed_at = dt.datetime.now(dt.UTC)

    def _update_task_status(self, task: EvaluationTask) -> None:
        submitted = (
            self.db.query(Rating).filter(Rating.task_id == task.id, Rating.status == "submitted").count()
        )
        if submitted > 0:
            task.status = "in_progress" if submitted < 2 else "completed"
