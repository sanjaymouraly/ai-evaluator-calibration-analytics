"""Rubric management with immutable versioning.

Rubrics are versioned; activating a new version supersedes the previous
one. Existing ratings are NEVER altered — they keep referencing the
rubric version they were scored against. Changes go through a human
approval workflow (RubricChangeRequest).
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.exceptions import ConflictError, NotFoundError, ValidationError
from app.models import (
    Rubric,
    RubricCategory,
    RubricChangeRequest,
    RubricInsight,
)
from app.schemas import RubricCategoryBase, RubricCreate


class RubricService:
    def __init__(self, db: Session):
        self.db = db

    def list_rubrics(self, project_id: str) -> list[Rubric]:
        return (
            self.db.query(Rubric)
            .filter(Rubric.project_id == project_id)
            .order_by(Rubric.created_at.desc())
            .all()
        )

    def get(self, rubric_id: str) -> Rubric:
        rubric = self.db.query(Rubric).filter(Rubric.id == rubric_id).first()
        if rubric is None:
            raise NotFoundError("Rubric not found.")
        return rubric

    def create(self, project_id: str, data: RubricCreate, user_id: str) -> Rubric:
        rubric = Rubric(
            project_id=project_id,
            name=data.name,
            description=data.description,
            version=self._next_version(project_id),
            status="draft",
            created_by=user_id,
            change_note="Initial version",
        )
        self.db.add(rubric)
        self.db.flush()
        self._save_categories(rubric, data.categories)
        self.db.commit()
        self.db.refresh(rubric)
        return rubric

    def _save_categories(self, rubric: Rubric, categories: list[RubricCategoryBase]) -> None:
        seen_keys: set[str] = set()
        for cat in categories:
            if cat.key in seen_keys:
                raise ValidationError(f"Duplicate category key: '{cat.key}'.")
            seen_keys.add(cat.key)
            if cat.scale_type == "categorical" and not cat.options:
                raise ValidationError(f"Category '{cat.key}' is categorical and requires options.")
            if cat.scale_type == "ordinal" and not cat.options:
                raise ValidationError(f"Category '{cat.key}' is ordinal and requires ordered options.")
            if cat.scale_type in ("ordinal", "numerical") and (
                cat.min_value is None or cat.max_value is None
            ):
                raise ValidationError(f"Category '{cat.key}' requires min_value and max_value.")

            # Option value types must match the scale
            for opt in cat.options or []:
                if cat.scale_type in ("ordinal", "numerical") and isinstance(opt.value, str):
                    raise ValidationError(
                        f"Category '{cat.key}' is {cat.scale_type}; option value "
                        f"'{opt.value}' must be numeric."
                    )
                if cat.scale_type == "categorical" and not isinstance(opt.value, str):
                    raise ValidationError(
                        f"Category '{cat.key}' is categorical; option value "
                        f"'{opt.value}' must be a string label."
                    )

            if cat.scale_type == "ordinal" and cat.options:
                numeric = [float(o.value) for o in cat.options]
                if len(set(numeric)) != len(numeric):
                    raise ValidationError(f"Category '{cat.key}' has duplicate option values.")
                if min(numeric) < float(cat.min_value) or max(numeric) > float(cat.max_value):
                    raise ValidationError(
                        f"Category '{cat.key}' options must fall within "
                        f"[{cat.min_value}, {cat.max_value}]."
                    )
            if cat.weight <= 0:
                raise ValidationError(f"Category '{cat.key}' weight must be positive.")
            self.db.add(
                RubricCategory(
                    rubric_id=rubric.id,
                    key=cat.key,
                    name=cat.name,
                    definition=cat.definition,
                    guidance=cat.guidance,
                    weight=cat.weight,
                    scale_type=cat.scale_type,
                    min_value=cat.min_value,
                    max_value=cat.max_value,
                    options_json=[o.model_dump() for o in cat.options] if cat.options else None,
                    anchors_json=[a.model_dump() for a in cat.anchors] if cat.anchors else None,
                    examples_json=cat.examples,
                    item_order=cat.item_order,
                )
            )

    def _next_version(self, project_id: str) -> int:
        latest = self.db.query(func.max(Rubric.version)).filter(Rubric.project_id == project_id).scalar()
        return (latest or 0) + 1

    def activate(self, rubric_id: str, user_id: str, change_note: str | None = None) -> Rubric:
        """Activate a draft rubric, superseding the previous active version."""
        rubric = self.get(rubric_id)
        if rubric.status == "active":
            raise ConflictError("This rubric version is already active.")
        prev = (
            self.db.query(Rubric)
            .filter(Rubric.project_id == rubric.project_id, Rubric.status == "active")
            .first()
        )
        if prev:
            prev.status = "superseded"
        rubric.status = "active"
        rubric.effective_from = dt.datetime.now(dt.UTC)
        if change_note:
            rubric.change_note = change_note
        self.db.commit()
        self.db.refresh(rubric)
        return rubric

    def archive(self, rubric_id: str) -> Rubric:
        rubric = self.get(rubric_id)
        if rubric.status == "active":
            raise ConflictError("Cannot archive the active rubric; activate another version first.")
        rubric.status = "archived"
        self.db.commit()
        self.db.refresh(rubric)
        return rubric

    def versions(self, project_id: str) -> list[Rubric]:
        return (
            self.db.query(Rubric).filter(Rubric.project_id == project_id).order_by(Rubric.version.asc()).all()
        )

    # ---------------- change requests (human approval gate) ----------------
    def create_change_request(
        self,
        rubric_id: str,
        category_id: str | None,
        proposed_changes: dict[str, Any],
        evidence: dict[str, Any] | None,
        rationale: str,
        requested_by: str,
        source: str = "manual",
        is_ai_generated: bool = False,
    ) -> RubricChangeRequest:
        req = RubricChangeRequest(
            rubric_id=rubric_id,
            rubric_category_id=category_id,
            proposed_changes_json=proposed_changes,
            evidence_json=evidence,
            rationale=rationale,
            requested_by=requested_by,
            source=source,
            is_ai_generated=is_ai_generated,
        )
        self.db.add(req)
        self.db.commit()
        self.db.refresh(req)
        return req

    def review_change_request(
        self, request_id: str, decision: str, reviewer_id: str, note: str | None = None
    ) -> RubricChangeRequest:
        req = self.db.query(RubricChangeRequest).filter(RubricChangeRequest.id == request_id).first()
        if req is None:
            raise NotFoundError("Change request not found.")
        if req.status != "pending":
            raise ConflictError("This request has already been reviewed.")
        if decision not in {"approved", "rejected"}:
            raise ValidationError("decision must be 'approved' or 'rejected'.")
        req.status = decision
        req.reviewed_by = reviewer_id
        req.reviewed_at = dt.datetime.now(dt.UTC)
        req.review_note = note
        self.db.commit()
        self.db.refresh(req)
        return req

    def apply_change_request(self, request_id: str, actor_id: str) -> Rubric:
        """Materialize an approved change request as a NEW rubric version.

        The old version is superseded but never deleted; historical
        ratings keep their original rubric_version_id reference.
        """
        req = self.db.query(RubricChangeRequest).filter(RubricChangeRequest.id == request_id).first()
        if req is None:
            raise NotFoundError("Change request not found.")
        if req.status != "approved":
            raise ConflictError("Only approved change requests can be applied.")
        if req.new_rubric_version_id:
            raise ConflictError("Change request already applied to a rubric version.")

        old = self.get(req.rubric_id)
        new = Rubric(
            project_id=old.project_id,
            name=old.name,
            description=old.description,
            version=self._next_version(old.project_id),
            status="active",
            created_by=actor_id,
            approved_by=req.reviewed_by,
            approved_at=dt.datetime.now(dt.UTC),
            effective_from=dt.datetime.now(dt.UTC),
            change_note=req.rationale,
        )
        # supersede old
        active = (
            self.db.query(Rubric)
            .filter(Rubric.project_id == old.project_id, Rubric.status == "active")
            .first()
        )
        if active:
            active.status = "superseded"
        self.db.add(new)
        self.db.flush()

        # Clone categories, applying proposed changes to the target category
        cats = (
            self.db.query(RubricCategory)
            .filter(RubricCategory.rubric_id == old.id)
            .order_by(RubricCategory.item_order)
            .all()
        )
        changes = req.proposed_changes_json or {}
        for cat in cats:
            payload = {
                "key": cat.key,
                "name": cat.name,
                "definition": cat.definition,
                "guidance": cat.guidance,
                "weight": cat.weight,
                "scale_type": cat.scale_type,
                "min_value": cat.min_value,
                "max_value": cat.max_value,
                "options": cat.options_json,
                "anchors": cat.anchors_json,
                "examples": cat.examples_json,
                "item_order": cat.item_order,
            }
            if str(cat.id) == str(req.rubric_category_id):
                payload.update(changes)
                payload.pop("id", None)
            self._save_categories(new, [RubricCategoryBase(**payload)])
        req.new_rubric_version_id = new.id
        self.db.commit()
        self.db.refresh(new)
        return new


def insight_summary(insights: list[RubricInsight]) -> dict[str, Any]:
    by_type: dict[str, int] = {}
    for i in insights:
        by_type[i.issue_type] = by_type.get(i.issue_type, 0) + 1
    return {"total": len(insights), "by_type": by_type}
