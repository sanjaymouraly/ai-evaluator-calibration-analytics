"""Adjudication & consensus management.

Consensus strategies are *advisory computations only*: they never
overwrite human adjudications. An adjudicator's decision becomes
authoritative only when marked final. Original ratings always
remain attached to the task, separate from consensus/adjudicated
labels. Reopening creates a new adjudication linked to the prior
one (explicit audit chain).
"""

from __future__ import annotations

import contextlib
import statistics
from collections import Counter
from typing import Any

from sqlalchemy.orm import Session

from app.exceptions import ConflictError, NotFoundError
from app.models import (
    Adjudication,
    AdjudicationVote,
    Disagreement,
    EvaluationTask,
    Project,
)


class AdjudicationService:
    def __init__(self, db: Session):
        self.db = db

    # ---------------- consensus (advisory) ----------------
    def compute_consensus(self, project: Project, task: EvaluationTask) -> dict[str, Any]:
        """Compute advisory consensus per category.

        - majority: modal category (categorical) — ties broken by
          lower value, noted as a limitation.
        - median: median ordinal/numerical score.
        - expert: defers to gold label when present (otherwise falls
          back to majority/median and flags it).
        """
        ratings = [r for r in task.ratings if r.status == "submitted" and r.is_current and not r.abstained]
        strategy = project.consensus_strategy
        if not ratings:
            return {
                "strategy": strategy,
                "scores": {},
                "limitations": ["No submitted ratings; consensus undefined."],
            }

        rubric_cats: dict[str, dict] = {}
        if ratings and ratings[0].rubric_version_id:
            from app.models import RubricCategory

            for c in (
                self.db.query(RubricCategory)
                .filter(RubricCategory.rubric_id == ratings[0].rubric_version_id)
                .all()
            ):
                rubric_cats[c.key] = {
                    "scale_type": c.scale_type,
                    "options": c.options_json,
                }

        scores: dict[str, Any] = {}
        limitations: list[str] = []
        keys = set()
        for r in ratings:
            keys |= set((r.scores_json or {}).keys())
        for key in sorted(keys):
            vals = [r.scores_json[key] for r in ratings if key in (r.scores_json or {})]
            if not vals:
                continue
            cat = rubric_cats.get(key, {})
            scale_type = cat.get("scale_type")
            if strategy == "median" and scale_type in ("ordinal", "numerical"):
                try:
                    scores[key] = statistics.median([float(v) for v in vals])
                except (TypeError, ValueError):
                    scores[key] = Counter(vals).most_common(1)[0][0]
            elif strategy == "expert" and task.gold_label_json:
                gold_scores = task.gold_label_json.get("scores", {})
                if key in gold_scores:
                    scores[key] = gold_scores[key]
                else:
                    scores[key] = self._majority(vals)
                    limitations.append(f"expert strategy: no gold label for '{key}'; fell back to majority")
            else:
                if scale_type in ("ordinal", "numerical"):
                    scores[key] = statistics.median([float(v) for v in vals])
                else:
                    scores[key] = self._majority(vals)
        if strategy == "majority":
            limitations.append(
                "majority vote ignores margin size; for 2-rater ties it picks "
                "the lower value — review these cases manually."
            )
        elif strategy == "median":
            limitations.append("median can mask bimodal splits (e.g. 1 vs 5 averages to 3).")
        elif strategy == "expert":
            limitations.append(
                "expert strategy uses gold labels where available; items "
                "without gold labels fall back to majority/median."
            )
        return {"strategy": strategy, "scores": scores, "limitations": limitations}

    @staticmethod
    def _majority(vals: list) -> Any:
        counts = Counter(vals)
        top = counts.most_common()
        if len(top) > 1 and top[0][1] == top[1][1]:
            return min(top[0][0], top[1][0])  # deterministic tie-break
        return top[0][0]

    # ---------------- adjudication workflow ----------------
    def create_adjudication(
        self,
        disagreement_id: str | None,
        task_id: str,
        adjudicator_id: str,
        strategy: str | None = None,
    ) -> Adjudication:
        task = self.db.query(EvaluationTask).filter(EvaluationTask.id == task_id).first()
        if task is None:
            raise NotFoundError("Task not found.")
        if disagreement_id:
            dg = self.db.query(Disagreement).filter(Disagreement.id == disagreement_id).first()
            if dg is None:
                raise NotFoundError("Disagreement not found.")
            dg.status = "in_review"
            self.db.flush()
        if strategy is None:
            project = self.db.query(Project).filter(Project.id == task.project_id).first()
            strategy = project.consensus_strategy if project else "expert"
        adj = Adjudication(
            disagreement_id=disagreement_id,
            task_id=task_id,
            adjudicator_id=adjudicator_id,
            strategy=strategy,
        )
        self.db.add(adj)
        self.db.commit()
        self.db.refresh(adj)
        return adj

    def record_vote(
        self,
        adjudication_id: str,
        user_id: str,
        decision: dict[str, Any],
        rationale: str | None = None,
    ) -> AdjudicationVote:
        adj = self._adj_or_404(adjudication_id)
        if adj.status == "final":
            raise ConflictError("Adjudication is final; reopen to modify.")
        existing = (
            self.db.query(AdjudicationVote)
            .filter(AdjudicationVote.adjudication_id == adj.id)
            .filter(AdjudicationVote.user_id == user_id)
            .first()
        )
        if existing:
            raise ConflictError("You already voted on this adjudication.")
        vote = AdjudicationVote(
            adjudication_id=adj.id,
            user_id=user_id,
            decision_json=decision,
            rationale=rationale,
        )
        self.db.add(vote)
        self.db.commit()
        self.db.refresh(vote)
        return vote

    def finalize(
        self, adjudication_id: str, adjudicator_id: str, decision: dict[str, Any], rationale: str
    ) -> Adjudication:
        adj = self._adj_or_404(adjudication_id)
        if adj.status == "final":
            raise ConflictError("Adjudication already final.")
        adj.decision_json = decision
        adj.rationale = rationale
        adj.status = "final"
        # mark task adjudicated
        task = self.db.query(EvaluationTask).filter(EvaluationTask.id == adj.task_id).first()
        if task is not None:
            task.status = "adjudicated"
        if adj.disagreement_id:
            dg = self.db.query(Disagreement).filter(Disagreement.id == adj.disagreement_id).first()
            if dg is not None:
                dg.status = "resolved"
        self.db.commit()
        self.db.refresh(adj)
        return adj

    def escalate(self, adjudication_id: str, reason: str) -> Adjudication:
        adj = self._adj_or_404(adjudication_id)
        adj.escalated = True
        adj.escalates_to = "senior_adjudication_panel"
        adj.rationale = (adj.rationale or "") + f"\n[ESCALATED] {reason}"
        self.db.commit()
        self.db.refresh(adj)
        return adj

    def reopen(self, adjudication_id: str, reason: str) -> Adjudication:
        adj = self._adj_or_404(adjudication_id)
        if adj.status != "final":
            raise ConflictError("Only final adjudications can be reopened.")
        new_adj = Adjudication(
            disagreement_id=adj.disagreement_id,
            task_id=adj.task_id,
            adjudicator_id=adj.adjudicator_id,
            strategy=adj.strategy,
            escalated=False,
            prior_adjudication_id=adj.id,
            status="proposed",
            rationale=f"Reopened: {reason}",
        )
        adj.status = "reopened"
        self.db.add(new_adj)
        task = self.db.query(EvaluationTask).filter(EvaluationTask.id == adj.task_id).first()
        if task is not None:
            task.status = "in_progress"
        dg = None
        if adj.disagreement_id:
            dg = self.db.query(Disagreement).filter(Disagreement.id == adj.disagreement_id).first()
            if dg is not None:
                dg.status = "open"
        self.db.commit()
        self.db.refresh(new_adj)
        return new_adj

    def list_for_project(self, project_id: str, status: str | None = None) -> list[Adjudication]:
        q = (
            self.db.query(Adjudication)
            .join(EvaluationTask, Adjudication.task_id == EvaluationTask.id)
            .filter(EvaluationTask.project_id == project_id)
        )
        if status:
            q = q.filter(Adjudication.status == status)
        return q.order_by(Adjudication.created_at.desc()).all()

    def _adj_or_404(self, adjudication_id: str) -> Adjudication:
        adj = self.db.query(Adjudication).filter(Adjudication.id == adjudication_id).first()
        if adj is None:
            raise NotFoundError("Adjudication not found.")
        return adj


def consensus_deviation(task: EvaluationTask) -> dict[str, Any]:
    """Consensus deviation per rating (for accuracy dashboards)."""
    ratings = [r for r in task.ratings if r.status == "submitted" and not r.abstained]
    out: dict[str, Any] = {}
    if len(ratings) < 2:
        return {"ratings": []}
    keys: set[str] = set()
    for r in ratings:
        keys |= set((r.scores_json or {}).keys())
    for key in sorted(keys):
        vals = []
        for r in ratings:
            v = (r.scores_json or {}).get(key)
            with contextlib.suppress(TypeError, ValueError):
                vals.append(float(v))
        if not vals:
            continue
        med = statistics.median(vals)
        out[key] = {
            "consensus_median": med,
            "deviations": [round(v - med, 4) for v in vals],
        }
    return {"ratings": out}
