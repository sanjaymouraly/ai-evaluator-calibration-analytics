"""Disagreement detection and prioritization engine.

Severity is a transparent, scale-relative composite (never a single
global threshold):

  ordinal/numerical categories:
    gap_norm    = (max - min) / scale_range           (0..1+)
    spread_norm = stdev / scale_range * 2             (0..1)
    severity    = 0.65 * min(gap_norm,1) + 0.35 * min(spread_norm,1)

  categorical categories:
    severity    = 0.60 baseline; 0.90 for configured
                  opposite judgments; 0.75 for multi-way split

Classification (kind) is chosen by rules, in priority order:
  opposite_categorical > expert_mismatch > major_score_gap
  > boundary_confusion > minor_score_gap > rubric_interpretation

Boundary confusion: adjacent-scale values only (gap == exactly one
step), flagged because ambiguous rubric boundaries are a distinct,
actionable problem from frank disagreement.

Priority score (for queue ordering):
    severity * (0.5 + 0.5*coverage_ratio) * category_weight
where coverage_ratio = n_ratings / max_ratings_seen.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import numpy as np
from sqlalchemy.orm import Session

from app.models import (
    Disagreement,
    EvaluationTask,
    Project,
    Rating,
    Rubric,
    RubricCategory,
)


class DetectionService:
    SEVERITY_FORMULA = (
        "severity = 0.65*min(gap_norm,1) + 0.35*min(spread_norm,1) "
        "for ordinal/numerical scales (scale-relative, adapts to each "
        "category's own range); categorical severity uses configured "
        "opposite-judgment pairs (0.90), multi-way splits (0.75), "
        "and simple splits (0.60). "
        "priority = severity * (0.5 + 0.5*coverage_ratio) * category_weight."
    )

    def __init__(self, db: Session):
        self.db = db

    # ------------------------------------------------------------------
    def scan_project(self, project_id: str) -> dict[str, int]:
        """Re-detect disagreements for all rated tasks in a project.

        Existing open disagreements are replaced (resolved/dismissed
        ones are preserved for the audit trail).
        """
        project = self.db.query(Project).filter(Project.id == project_id).first()
        if project is None:
            raise ValueError(f"Project {project_id} not found")

        # Replace previous *open* detections (keep history of resolved ones)
        self.db.query(Disagreement).filter(
            Disagreement.project_id == project_id,
            Disagreement.status.in_(["open", "in_review"]),
        ).delete(synchronize_session=False)

        tasks = self.db.query(EvaluationTask).filter(EvaluationTask.project_id == project_id).all()
        counts: dict[str, int] = defaultdict(int)
        for task in tasks:
            found = self._detect_for_task(task, project)
            for kind in found:
                counts[kind] += 1
        self.db.commit()
        return dict(counts)

    # ------------------------------------------------------------------
    def _detect_for_task(self, task: EvaluationTask, project: Project) -> list[str]:
        ratings = (
            self.db.query(Rating)
            .filter(
                Rating.task_id == task.id,
                Rating.status == "submitted",
                Rating.is_current.is_(True),
            )
            .all()
        )
        if len(ratings) < 2:
            return []

        rubric = self._active_rubric(project.id)
        if rubric is None:
            return []
        categories = {c.key: c for c in rubric.categories}

        found: list[str] = []
        # Group ratings by category
        by_cat: dict[str, list[tuple[str, Any, Rating]]] = defaultdict(list)
        for rating in ratings:
            if rating.abstained or not rating.scores_json:
                continue
            for key, value in rating.scores_json.items():
                if value is None:
                    continue
                by_cat[key].append((key, value, rating))

        max_coverage = len(ratings)
        for key, entries in by_cat.items():
            if len(entries) < 2:
                continue
            cat = categories.get(key)
            if cat is None:
                continue
            result = self._classify(key, cat, entries, task, project, max_coverage)
            if result is None:
                continue
            kind, severity, details = result
            priority = self._priority(severity, len(entries), max_coverage, cat.weight)
            existing = (
                self.db.query(Disagreement)
                .filter(
                    Disagreement.task_id == task.id,
                    Disagreement.category_key == key,
                    Disagreement.kind == kind,
                )
                .first()
            )
            if existing:
                continue
            self.db.add(
                Disagreement(
                    project_id=project.id,
                    task_id=task.id,
                    category_key=key,
                    kind=kind,
                    severity_score=round(severity, 4),
                    severity_class=self._classify_severity(severity, project),
                    details_json=details,
                    priority_score=round(priority, 4),
                )
            )
            found.append(kind)
        return found

    # ------------------------------------------------------------------
    def _classify(
        self,
        key: str,
        cat: RubricCategory,
        entries: list[tuple[str, Any, Rating]],
        task: EvaluationTask,
        project: Project,
        max_coverage: int,
    ) -> tuple[str, float, dict] | None:
        ratings = [r for _, _, r in entries]
        reviewer_ids = [r.reviewer_id for r in ratings]

        base_details = {
            "values": [
                {"reviewer_id": r.reviewer_id, "value": v, "confidence": r.confidence}
                for (_, v, r) in entries
            ],
            "n_ratings": len(entries),
            "reviewer_ids": reviewer_ids,
        }

        if cat.scale_type == "categorical":
            distinct = {str(v) for _, v, _ in entries}
            if len(distinct) < 2:
                return None
            opposite = project.categorical_opposite_pairs or {}
            pair_hit = any(
                str(a) in opposite and str(b) == str(opposite[str(a)])
                for a in distinct
                for b in distinct
                if a != b
            )
            if pair_hit:
                severity = 0.9
                kind = "opposite_categorical"
            elif len(distinct) >= 3:
                severity = 0.75
                kind = "major_score_gap"
            else:
                severity = 0.6
                kind = "minor_score_gap"
            base_details.update(
                {
                    "distinct_values": sorted(distinct),
                    "severity_basis": "categorical opposition configuration",
                }
            )
            return kind, severity, base_details

        # ordinal / numerical
        values = [float(v) for _, v, _ in entries]
        scale_lo = cat.min_value if cat.min_value is not None else min(values)
        scale_hi = cat.max_value if cat.max_value is not None else max(values)
        scale_range = float(scale_hi - scale_lo) or 1.0
        gap = max(values) - min(values)
        gap_norm = gap / scale_range
        spread = float(np.std(values, ddof=1)) if len(values) > 1 else 0.0
        spread_norm = min(1.0, (spread / scale_range) * 2)

        # gold-label mismatch (reviewer-vs-expert)
        gold = None
        if task.gold_label_json:
            gold = task.gold_label_json.get("scores", {}).get(key)
        expert_mismatch = False
        if gold is not None:
            gold = float(gold)
            devs = [abs(v - gold) for v in values]
            if any(d >= (0.5 * scale_range) for d in devs):
                expert_mismatch = True

        # adjacent-step boundary confusion
        step = self._scale_step(cat)
        adjacent_only = step is not None and abs(gap - step) < 1e-9

        severity = 0.65 * min(gap_norm, 1.0) + 0.35 * spread_norm

        # rationale conflict heuristic: strong-certainty vs hedging language
        rationale_conflict = self._rationale_conflict(ratings)

        if expert_mismatch:
            kind = "expert_mismatch"
        elif gap_norm >= project.disagreement_major_fraction:
            kind = "major_score_gap"
        elif adjacent_only:
            kind = "boundary_confusion"
            severity = max(severity, 0.35)
        elif gap_norm >= project.disagreement_minor_fraction:
            kind = "minor_score_gap"
        elif rationale_conflict:
            kind = "rubric_interpretation"
        else:
            return None

        base_details.update(
            {
                "scale_min": scale_lo,
                "scale_max": scale_hi,
                "scale_range": scale_range,
                "gap": gap,
                "gap_norm": round(gap_norm, 4),
                "spread_norm": round(spread_norm, 4),
                "severity_basis": ("0.65*gap_norm + 0.35*spread_norm (scale-relative)"),
                "gold_value": gold,
                "expert_mismatch": expert_mismatch,
                "adjacent_only": adjacent_only,
                "rationale_conflict": rationale_conflict,
            }
        )
        return kind, severity, base_details

    @staticmethod
    def _scale_step(cat: RubricCategory) -> float | None:
        """Infer the unit step of an ordinal scale from its options."""
        options = cat.options_json or []
        if len(options) >= 2:
            vals = sorted(float(o["value"]) for o in options)
            steps = {round(b - a, 6) for a, b in zip(vals, vals[1:], strict=False)}
            if len(steps) == 1:
                return steps.pop()
        return None

    @staticmethod
    def _rationale_conflict(ratings: list[Rating]) -> bool:
        """Deterministic heuristic: one reviewer expresses confidence
        while another hedges on the same item."""
        confident_terms = ("clearly", "definitely", "obviously", "exactly", "precisely")
        hedge_terms = ("unclear", "ambiguous", "uncertain", "maybe", "seems", "unclearly")
        confident = any((r.rationale or "").lower().count(t) for r in ratings for t in confident_terms)
        hedging = any((r.rationale or "").lower().count(t) for r in ratings for t in hedge_terms)
        return confident and hedging

    @staticmethod
    def _priority(severity: float, n_ratings: int, max_coverage: int, weight: float) -> float:
        coverage_ratio = n_ratings / max(max_coverage, 1)
        return round(float(severity) * (0.5 + 0.5 * coverage_ratio) * (weight or 1.0), 4)

    @staticmethod
    def _classify_severity(severity: float, project: Project) -> str:
        # severity 0..1; minor threshold fraction maps onto scale range.
        if severity >= 0.75:
            return "critical"
        if severity >= project.disagreement_major_fraction:
            return "major"
        return "minor"

    def _active_rubric(self, project_id: str) -> Rubric | None:
        return (
            self.db.query(Rubric)
            .filter(Rubric.project_id == project_id, Rubric.status == "active")
            .order_by(Rubric.version.desc())
            .first()
        )

    # ------------------------------------------------------------------
    def project_disagreement_summary(self, project_id: str) -> dict[str, Any]:
        rows = self.db.query(Disagreement).filter(Disagreement.project_id == project_id).all()
        by_class: dict[str, int] = defaultdict(int)
        by_kind: dict[str, int] = defaultdict(int)
        by_category: dict[str, int] = defaultdict(int)
        for d in rows:
            by_class[d.severity_class] += 1
            by_kind[d.kind] += 1
            by_category[d.category_key or "unknown"] += 1
        return {
            "total": len(rows),
            "open": sum(1 for d in rows if d.status == "open"),
            "by_class": dict(by_class),
            "by_kind": dict(by_kind),
            "by_category": dict(by_category),
        }
