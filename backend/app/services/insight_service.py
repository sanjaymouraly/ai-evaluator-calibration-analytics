"""Rubric ambiguity & improvement engine.

Deterministic, evidence-backed detection of rubric weaknesses:
  - categories with high disagreement frequency
  - categories with low inter-rater reliability
  - recurring boundary-score confusion (adjacent scores)
  - contradictory reviewer rationales
  - weak/overlapping criterion definitions
  - missing scoring anchors or examples
  - scoring drift across time
  - differences across language / task type / model

Every insight carries: supporting evidence, affected cases,
sample size, statistical measurement, and a proposed
improvement. AI-generated suggestions (optional) are always
flagged `is_ai_generated` and require human approval.
"""

from __future__ import annotations

import contextlib
from collections import defaultdict
from typing import Any

import numpy as np
from sqlalchemy.orm import Session

from app.analytics import stats as st
from app.exceptions import NotFoundError, ValidationError
from app.models import (
    Disagreement,
    EvaluationTask,
    Project,
    Rating,
    Rubric,
    RubricCategory,
    RubricInsight,
)

BOUNDARY_TERMS_POS = {"good", "great", "excellent", "clear", "strong", "meets"}
BOUNDARY_TERMS_NEG = {"poor", "bad", "weak", "unclear", "fails", "missing"}


class InsightService:
    def __init__(self, db: Session):
        self.db = db

    def analyze_project(self, project_id: str) -> list[RubricInsight]:
        project = self.db.query(Project).filter(Project.id == project_id).first()
        rubric = self._active_rubric(project_id)
        if rubric is None or project is None:
            return []
        cats = rubric.categories
        ratings = (
            self.db.query(Rating)
            .join(EvaluationTask, Rating.task_id == EvaluationTask.id)
            .filter(
                EvaluationTask.project_id == project_id,
                Rating.status == "submitted",
                Rating.is_current.is_(True),
            )
            .all()
        )
        disagreements = self.db.query(Disagreement).filter(Disagreement.project_id == project_id).all()

        insights: list[RubricInsight] = []
        # clear stale deterministic insights, keep AI/human-reviewed
        self.db.query(RubricInsight).filter(
            RubricInsight.project_id == project_id,
            RubricInsight.source == "deterministic",
            RubricInsight.status == "open",
        ).delete(synchronize_session=False)

        for cat in cats:
            insight = self._analyze_category(cat, project, ratings, disagreements)
            if insight is not None:
                self.db.add(insight)
                insights.append(insight)
        self.db.commit()
        return insights

    # ------------------------------------------------------------------
    def _analyze_category(
        self,
        cat: RubricCategory,
        project: Project,
        ratings: list[Rating],
        disagreements: list[Disagreement],
    ) -> RubricInsight | None:
        cat_disagreements = [
            d for d in disagreements if d.category_key == cat.key and d.status in ("open", "in_review")
        ]
        by_task: dict[str, list[Rating]] = defaultdict(list)
        for r in ratings:
            if r.scores_json and cat.key in (r.scores_json or {}):
                by_task[r.task_id].append(r)

        n_items = len(by_task)
        if n_items < 3:
            return None  # insufficient evidence — do not speculate

        # 1. disagreement frequency
        n_disagree = len(cat_disagreements)
        disagreement_rate = n_disagree / max(n_items, 1)

        # 2. reliability (krippendorff alpha by scale level)
        matrix = []
        for vals in by_task.values():
            row = []
            for r in vals:
                v = r.scores_json.get(cat.key)
                if v is None or r.abstained:
                    continue
                row.append(v)
            if len(row) >= 2:
                matrix.append(row)
        level = (
            "nominal"
            if cat.scale_type == "categorical"
            else ("ordinal" if cat.scale_type == "ordinal" else "interval")
        )
        alpha, _ = st.krippendorff_alpha(matrix, level=level)

        # 3. boundary confusion: adjacent-value pairs dominate
        boundary_pairs = 0
        total_pairs = 0
        if cat.scale_type in ("ordinal", "numerical"):
            for vals in by_task.values():
                nums = []
                for r in vals:
                    with contextlib.suppress(TypeError, ValueError, KeyError):
                        nums.append(float(r.scores_json[cat.key]))
                for i in range(len(nums)):
                    for j in range(i + 1, len(nums)):
                        total_pairs += 1
                        if abs(nums[i] - nums[j]) == 1.0:
                            boundary_pairs += 1
        boundary_confusion_rate = boundary_pairs / total_pairs if total_pairs else 0.0

        # 4. contradictory rationales
        conflict_count = 0
        for vals in by_task.values():
            rat_items = [(r.rationale or "").lower() for r in vals if r.rationale]
            for i in range(len(rat_items)):
                for j in range(i + 1, len(rat_items)):
                    if _contradictory(rat_items[i], rat_items[j]):
                        conflict_count += 1

        # 5. definition weakness heuristics
        weak_definition = (
            cat.definition is not None and len(cat.definition.strip()) < 40
        ) or cat.definition is None
        overlapping = self._definition_overlap(cat, project)

        # 6. missing anchors
        has_anchors = bool(cat.anchors_json)

        # 7. drift: correlation between submission order and score
        drift = None
        all_vals = []
        for r in ratings:
            if r.scores_json and cat.key in r.scores_json:
                with contextlib.suppress(TypeError, ValueError, KeyError):
                    all_vals.append((r.submitted_at, float(r.scores_json[cat.key])))
        if len(all_vals) >= 10:
            all_vals.sort(key=lambda t: t[0])
            idx = list(range(len(all_vals)))
            vals = [v for _, v in all_vals]
            corr = np.corrcoef(idx, vals)[0, 1]
            if not np.isnan(corr):
                drift = float(corr)

        # 8. segment differences (language / model / task_type)
        segments = self._segment_variation(cat, by_task, ratings)

        # Decide the primary issue & severity
        issue_type = None
        severity = "low"
        evidence: dict[str, Any] = {
            "n_items": n_items,
            "n_disagreements": n_disagree,
            "disagreement_rate": round(disagreement_rate, 4),
            "krippendorff_alpha": alpha,
            "boundary_confusion_rate": round(boundary_confusion_rate, 4),
            "rationale_conflicts": conflict_count,
            "drift_correlation": drift,
            "has_examples": bool(cat.examples_json),
            "segments": segments,
        }
        affected = [d.task_id for d in cat_disagreements][:100]

        if alpha is not None and alpha < 0.4:
            issue_type = "low_reliability"
            severity = "high"
        if disagreement_rate >= 0.3:
            issue_type = issue_type or "high_disagreement"
            severity = "high" if disagreement_rate >= 0.5 else "medium"
        if boundary_confusion_rate >= 0.5 and total_pairs >= 6:
            issue_type = issue_type or "boundary_confusion"
            severity = max_severity(severity, "medium")
        if conflict_count >= 3:
            issue_type = issue_type or "contradictory_rationales"
            severity = max_severity(severity, "medium")
        if weak_definition or overlapping:
            issue_type = issue_type or "weak_definition"
            severity = max_severity(severity, "low")
        if not has_anchors:
            issue_type = issue_type or "missing_anchors"
            severity = max_severity(severity, "low")
        if drift is not None and abs(drift) >= 0.3:
            issue_type = issue_type or "scoring_drift"
            severity = max_severity(severity, "medium")
        if segments.get("max_gap") is not None and segments["max_gap"] >= 1.0:
            issue_type = issue_type or "segment_variation"
            severity = max_severity(severity, "medium")

        if issue_type is None:
            return None

        suggestion = self._suggestion(issue_type, cat, boundary_confusion_rate, alpha)
        return RubricInsight(
            project_id=project.id,
            rubric_category_id=cat.id,
            issue_type=issue_type,
            severity=severity,
            evidence_json=evidence,
            affected_task_ids_json=affected,
            sample_size=n_items,
            stat_value=alpha if alpha is not None else disagreement_rate,
            suggestion_json=suggestion,
            source="deterministic",
        )

    # ------------------------------------------------------------------
    def _definition_overlap(self, cat: RubricCategory, project: Project) -> bool:
        """Detect potentially overlapping criterion definitions via
        keyword Jaccard similarity between category definitions."""
        rubric = self._active_rubric(project.id)
        if rubric is None:
            return False
        words = set(_keywords(cat.definition or ""))
        if not words:
            return False
        for other in rubric.categories:
            if other.id == cat.id:
                continue
            other_words = set(_keywords(other.definition or ""))
            if not other_words:
                continue
            jaccard = len(words & other_words) / len(words | other_words)
            if jaccard >= 0.55:
                return True
        return False

    def _segment_variation(
        self, cat: RubricCategory, by_task: dict[str, list[Rating]], ratings: list[Rating]
    ) -> dict[str, Any]:
        """Compare mean scores across language / task_type / model."""
        task_info = {t.id: t for t in self.db.query(EvaluationTask).all()}
        segments: dict[str, dict[str, list[float]]] = {
            "language": defaultdict(list),
            "task_type": defaultdict(list),
            "model": defaultdict(list),
        }
        for r in ratings:
            task = task_info.get(r.task_id)
            if task is None or not r.scores_json:
                continue
            try:
                v = float(r.scores_json[cat.key])
            except (TypeError, ValueError, KeyError):
                continue
            if task.language:
                segments["language"][task.language].append(v)
            if task.task_type:
                segments["task_type"][task.task_type].append(v)
            if task.model_name:
                segments["model"][task.model_name].append(v)
        result: dict[str, Any] = {}
        max_gap = 0.0
        for name, groups in segments.items():
            means = {k: round(float(np.mean(v)), 3) for k, v in groups.items() if len(v) >= 3}
            result[name] = means
            if means:
                gap = max(means.values()) - min(means.values())
                max_gap = max(max_gap, gap)
        result["max_gap"] = round(max_gap, 3)
        return result

    @staticmethod
    def _suggestion(
        issue_type: str, cat: RubricCategory, boundary_rate: float, alpha: float | None
    ) -> dict[str, Any]:
        suggestions = {
            "low_reliability": (
                "Reliability is low (alpha below 0.40). Tighten the "
                "operational definition, add level-specific examples, and "
                "introduce intermediate anchors so reviewers can "
                "distinguish adjacent levels."
            ),
            "high_disagreement": (
                "This category disagrees frequently. Add explicit "
                "boundary cases and a decision tree for common "
                "ambiguities, then re-anchor the scale."
            ),
            "boundary_confusion": (
                "Adjacent scores dominate disagreements — the boundary "
                "between levels is ambiguous. Define observable "
                "behaviors for each level and add 2–3 worked examples "
                "at the boundary."
            ),
            "contradictory_rationales": (
                "Reviewers cite the same evidence with opposite "
                "conclusions. Clarify which signals are decisive and "
                "add a 'what good looks like' example."
            ),
            "weak_definition": (
                "The criterion definition is missing or too short. "
                "Write a 2–3 sentence operational definition with "
                "observable indicators."
            ),
            "missing_anchors": (
                "Scoring anchors are missing. Provide a labelled "
                "example for each scale point so reviewers calibrate "
                "against a shared standard."
            ),
            "scoring_drift": (
                "Mean scores drift over time. Run a calibration "
                "session to re-align reviewers and re-check for "
                "fatigue effects."
            ),
            "segment_variation": (
                "Scores differ systematically by language, task type, "
                "or model. Verify the criterion is applicable across "
                "segments or document segment-specific guidance."
            ),
        }
        return {
            "issue_type": issue_type,
            "recommendation": suggestions.get(issue_type, "Review this category."),
            "proposed_improvements": [
                "Expand the operational definition with observable indicators",
                "Add boundary-case examples between adjacent scale points",
                "Specify scoring anchors for every scale value",
            ],
            "requires_human_approval": True,
        }

    def _active_rubric(self, project_id: str) -> Rubric | None:
        return (
            self.db.query(Rubric)
            .filter(Rubric.project_id == project_id, Rubric.status == "active")
            .order_by(Rubric.version.desc())
            .first()
        )

    def list_insights(self, project_id: str) -> list[RubricInsight]:
        return (
            self.db.query(RubricInsight)
            .filter(RubricInsight.project_id == project_id)
            .order_by(RubricInsight.severity.desc())
            .all()
        )

    def resolve_insight(
        self, insight_id: str, decision: str, change_request_id: str | None = None
    ) -> RubricInsight:
        insight = self.db.query(RubricInsight).filter(RubricInsight.id == insight_id).first()
        if insight is None:
            raise NotFoundError("Insight not found.")
        if decision not in {"approved", "rejected", "resolved"}:
            raise ValidationError("decision must be approved|rejected|resolved")
        insight.status = decision
        self.db.commit()
        self.db.refresh(insight)
        return insight


def max_severity(a: str, b: str) -> str:
    order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    return a if order.get(a, 0) >= order.get(b, 0) else b


def _keywords(text: str) -> set[str]:
    stop = {
        "the",
        "a",
        "an",
        "and",
        "or",
        "of",
        "to",
        "in",
        "for",
        "with",
        "is",
        "are",
        "be",
        "on",
        "at",
        "by",
        "it",
        "its",
        "that",
        "this",
        "should",
        "must",
        "not",
        "no",
        "if",
        "when",
        "than",
        "as",
        "from",
    }
    return {w for w in text.lower().split() if w.isalpha() and len(w) > 2} - stop


def _contradictory(a: str, b: str) -> bool:
    """Heuristic: one rationale is strongly positive while the other
    is strongly negative, or they use opposing certainty markers."""
    a_pos = len(BOUNDARY_TERMS_POS & set(a.split()))
    a_neg = len(BOUNDARY_TERMS_NEG & set(a.split()))
    b_pos = len(BOUNDARY_TERMS_POS & set(b.split()))
    b_neg = len(BOUNDARY_TERMS_NEG & set(b.split()))
    return bool((a_pos > a_neg and b_neg > b_pos) or (a_neg > a_pos and b_pos > b_neg))
