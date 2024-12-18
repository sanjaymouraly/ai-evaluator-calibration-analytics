"""DB-backed analytics: agreement metrics, reviewer reliability,
bias/leniency, calibration-vs-gold accuracy, trends, and drill-down
data. Uses the pure stats module; distinguishes clearly between
inter-reviewer agreement, accuracy vs reference labels, reviewer
bias, and calibration.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import numpy as np
from sqlalchemy.orm import Session

from app.analytics import stats as st
from app.models import (
    Adjudication,
    CalibrationAttempt,
    Disagreement,
    EvaluationTask,
    Project,
    Rating,
    Rubric,
)


def _as_float(value: Any) -> float | None:
    """Best-effort numeric coercion.

    Returns ``None`` for non-numeric values (e.g. categorical labels
    like ``"safe"``) so callers can skip them instead of raising or
    silently producing NaN from empty accumulators.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if np.isfinite(result) else None


class AnalyticsEngine:
    def __init__(self, db: Session):
        self.db = db

    # ---------------- helpers ----------------
    def _active_rubric(self, project_id: str) -> Rubric | None:
        return (
            self.db.query(Rubric)
            .filter(Rubric.project_id == project_id, Rubric.status == "active")
            .order_by(Rubric.version.desc())
            .first()
        )

    def _submitted_ratings(self, project_id: str, task_ids: list[str] | None = None):
        q = (
            self.db.query(Rating)
            .join(EvaluationTask, Rating.task_id == EvaluationTask.id)
            .filter(
                EvaluationTask.project_id == project_id,
                Rating.status == "submitted",
                Rating.is_current.is_(True),
            )
        )
        if task_ids:
            q = q.filter(Rating.task_id.in_(task_ids))
        return q.all()

    # ---------------- item-level agreement ----------------
    def item_agreement(self, project_id: str) -> list[dict[str, Any]]:
        """Per-item, per-category agreement with metric selection by scale."""
        rubric = self._active_rubric(project_id)
        if rubric is None:
            return []
        cats = {c.key: c for c in rubric.categories}
        tasks = self.db.query(EvaluationTask).filter(EvaluationTask.project_id == project_id).all()
        out = []
        for task in tasks:
            ratings = [
                r for r in task.ratings if r.status == "submitted" and r.is_current and not r.abstained
            ]
            if len(ratings) < 2:
                continue
            for key, cat in cats.items():
                vals = [r.scores_json.get(key) for r in ratings if r.scores_json]
                vals = [v for v in vals if v is not None]
                if len(vals) < 2:
                    continue
                if cat.scale_type == "categorical":
                    # majority share of ratings per item
                    from collections import Counter

                    counts = Counter(map(str, vals))
                    value = max(counts.values()) / len(vals)
                    metric = "raw_majority"
                elif cat.scale_type == "ordinal":
                    value, _ = (
                        st.weighted_kappa(vals, vals[1:] + vals[:1], weighting="quadratic")
                        if len(set(map(str, vals))) == 1
                        else (None, None)
                    )
                    # proper: pairwise weighted kappa across rater pairs
                    pairs = self._all_pairs(vals)
                    if pairs:
                        xs, ys = zip(*pairs, strict=False)
                        value, _ = st.weighted_kappa(list(xs), list(ys))
                    else:
                        value = None
                    metric = "weighted_kappa_quadratic"
                else:
                    pairs = self._all_pairs(vals)
                    if pairs:
                        xs, ys = zip(*pairs, strict=False)
                        value, _ = st.mean_absolute_difference(list(xs), list(ys))
                    else:
                        value = None
                    metric = "mad"
                out.append(
                    {
                        "task_id": task.id,
                        "external_id": task.external_id,
                        "category_key": key,
                        "n_ratings": len(vals),
                        "metric": metric,
                        "value": value,
                        "values": [str(v) for v in vals],
                    }
                )
        return out

    @staticmethod
    def _all_pairs(values: list) -> list[tuple]:
        pairs = []
        for i in range(len(values)):
            for j in range(i + 1, len(values)):
                pairs.append((values[i], values[j]))
        return pairs

    # ---------------- project-level metrics ----------------
    def project_metrics(self, project_id: str) -> dict[str, Any]:
        rubric = self._active_rubric(project_id)
        cats = {c.key: c for c in rubric.categories} if rubric else {}
        ratings = self._submitted_ratings(project_id)
        if not ratings:
            return {"n_ratings": 0, "categories": {}}

        by_task: dict[str, list[Rating]] = defaultdict(list)
        for r in ratings:
            by_task[r.task_id].append(r)

        cat_results: dict[str, Any] = {}
        for key, cat in cats.items():
            per_task_vals: dict[str, list] = defaultdict(list)
            for task_id, task_ratings in by_task.items():
                for r in task_ratings:
                    if r.abstained or not r.scores_json:
                        continue
                    v = r.scores_json.get(key)
                    if v is None:
                        continue
                    per_task_vals[task_id].append(v)
            items_with_multiple = {t: v for t, v in per_task_vals.items() if len(v) >= 2}
            if not items_with_multiple:
                cat_results[key] = {"n_items": 0, "n_ratings": 0}
                continue

            if cat.scale_type == "categorical":
                # Fleiss-style: build category-count matrix
                all_labels = sorted({str(v) for vals in items_with_multiple.values() for v in vals})
                matrix = []
                for vals in items_with_multiple.values():
                    row = [sum(1 for v in vals if str(v) == lab) for lab in all_labels]
                    matrix.append(row)
                k_val, warns = st.fleiss_kappa(matrix)
                # also raw agreement per item averaged
                raw_vals = []
                for vals in items_with_multiple.values():
                    counts = defaultdict(int)
                    for v in vals:
                        counts[str(v)] += 1
                    raw_vals.append(max(counts.values()) / len(vals))
                raw = float(np.mean(raw_vals)) if raw_vals else None
                cat_results[key] = {
                    "n_items": len(items_with_multiple),
                    "n_ratings": sum(len(v) for v in items_with_multiple.values()),
                    "scale_type": cat.scale_type,
                    "metric": "fleiss_kappa",
                    "fleiss_kappa": k_val,
                    "raw_agreement": raw,
                    "warnings": warns,
                }
            elif cat.scale_type == "ordinal":
                # Item-level pairwise exact agreement + project-level
                # Krippendorff alpha (ordinal metric) across items.
                raws = []
                for vals in items_with_multiple.values():
                    for a, b in self._all_pairs(vals):
                        raws.append(1.0 if a == b else 0.0)
                matrix = [[v for v in vals] for vals in items_with_multiple.values()]
                alpha, warns = st.krippendorff_alpha(matrix, level="ordinal")
                raw = float(np.mean(raws)) if raws else None
                cat_results[key] = {
                    "n_items": len(items_with_multiple),
                    "n_ratings": sum(len(v) for v in items_with_multiple.values()),
                    "scale_type": cat.scale_type,
                    "metric": "krippendorff_alpha_ordinal",
                    "krippendorff_alpha": alpha,
                    "raw_agreement": raw,
                    "warnings": warns,
                }
            else:  # numerical
                matrix = [[float(v) for v in vals] for vals in items_with_multiple.values()]
                icc, icc_warns = st.icc_2_1(matrix)
                # MAD across all pairs
                mad_vals = []
                for vals in items_with_multiple.values():
                    for a, b in self._all_pairs(vals):
                        mad_vals.append(abs(float(a) - float(b)))
                mad = float(np.mean(mad_vals)) if mad_vals else None
                cat_results[key] = {
                    "n_items": len(items_with_multiple),
                    "n_ratings": sum(len(v) for v in items_with_multiple.values()),
                    "scale_type": cat.scale_type,
                    "metric": "icc_2_1",
                    "icc_2_1": icc,
                    "mad": mad,
                    "warnings": icc_warns,
                }

        return {
            "n_ratings": len(ratings),
            "n_rated_items": len(by_task),
            "categories": cat_results,
        }

    # ---------------- pairwise reviewer agreement ----------------
    def pairwise_reviewer_agreement(self, project_id: str) -> list[dict[str, Any]]:
        ratings = self._submitted_ratings(project_id)
        by_task_reviewer: dict[str, dict[str, Rating]] = defaultdict(dict)
        for r in ratings:
            if r.abstained or not r.scores_json:
                continue
            by_task_reviewer[r.task_id][r.reviewer_id] = r
        pair_stats: dict[tuple[str, str], dict[str, Any]] = defaultdict(
            lambda: {"items": 0, "exact": 0, "abs_diffs": []}
        )
        for _task_id, by_reviewer in by_task_reviewer.items():
            reviewers = sorted(by_reviewer)
            for i in range(len(reviewers)):
                for j in range(i + 1, len(reviewers)):
                    ra, rb = by_reviewer[reviewers[i]], by_reviewer[reviewers[j]]
                    key = (reviewers[i], reviewers[j])
                    stats = pair_stats[key]
                    stats["items"] += 1
                    exact = True
                    for cat_key in ra.scores_json or {}:
                        va, vb = ra.scores_json.get(cat_key), rb.scores_json.get(cat_key)
                        if va is None or vb is None:
                            continue
                        try:
                            if float(va) != float(vb):
                                exact = False
                                stats["abs_diffs"].append(abs(float(va) - float(vb)))
                        except (TypeError, ValueError):
                            if str(va) != str(vb):
                                exact = False
                    if exact:
                        stats["exact"] += 1
        out = []
        for (a, b), stats in pair_stats.items():
            out.append(
                {
                    "reviewer_a": a,
                    "reviewer_b": b,
                    "shared_items": stats["items"],
                    "exact_agreement": (stats["exact"] / stats["items"] if stats["items"] else None),
                    "mean_abs_diff": (float(np.mean(stats["abs_diffs"])) if stats["abs_diffs"] else 0.0),
                }
            )
        return sorted(out, key=lambda x: -x["shared_items"])

    # ---------------- reviewer bias / severity ----------------
    def reviewer_bias(self, project_id: str) -> list[dict[str, Any]]:
        """Severity/leniency: mean signed deviation from per-item consensus."""
        ratings = self._submitted_ratings(project_id)
        by_task: dict[str, list[Rating]] = defaultdict(list)
        for r in ratings:
            if r.abstained or not r.scores_json:
                continue
            by_task[r.task_id].append(r)
        per_reviewer: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
        for _task_id, task_ratings in by_task.items():
            # consensus = mean of numeric scores per category.
            # Convert first, then append, so non-numeric (categorical)
            # categories never create empty accumulator entries.
            cat_values: dict[str, list[float]] = {}
            for r in task_ratings:
                for key, v in (r.scores_json or {}).items():
                    num = _as_float(v)
                    if num is None:
                        continue
                    cat_values.setdefault(key, []).append(num)
            consensus = {k: float(np.mean(v)) for k, v in cat_values.items() if v}
            for r in task_ratings:
                for key, v in (r.scores_json or {}).items():
                    num = _as_float(v)
                    if num is None or key not in consensus:
                        continue
                    per_reviewer[r.reviewer_id][key].append(num - consensus[key])
        out = []
        for reviewer_id, cats in per_reviewer.items():
            # Only numeric categories contribute to bias; categorical
            # scales have no meaningful signed deviation.
            numeric_cats = {k: v for k, v in cats.items() if len(v) > 0}
            all_devs = [d for devs in numeric_cats.values() for d in devs]
            if len(all_devs) < 3:
                continue
            out.append(
                {
                    "reviewer_id": reviewer_id,
                    "mean_deviation": float(np.mean(all_devs)),
                    "std_deviation": float(np.std(all_devs, ddof=1)) if len(all_devs) > 1 else 0.0,
                    "n_scores": len(all_devs),
                    "tendency": (
                        "severe"
                        if np.mean(all_devs) > 0.25
                        else "lenient"
                        if np.mean(all_devs) < -0.25
                        else "neutral"
                    ),
                    "by_category": {k: round(float(np.mean(v)), 4) for k, v in numeric_cats.items()},
                }
            )
        return sorted(out, key=lambda x: -abs(x["mean_deviation"]))

    # ---------------- accuracy vs gold labels ----------------
    def accuracy_vs_gold(self, project_id: str) -> dict[str, Any]:
        tasks = (
            self.db.query(EvaluationTask)
            .filter(
                EvaluationTask.project_id == project_id,
                EvaluationTask.gold_label_json.isnot(None),
            )
            .all()
        )
        ratings = self._submitted_ratings(project_id)
        by_task: dict[str, list[Rating]] = defaultdict(list)
        for r in ratings:
            if r.abstained or not r.scores_json:
                continue
            by_task[r.task_id].append(r)

        reviewer_stats: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"exact": 0, "total": 0, "abs_diffs": []}
        )
        for task in tasks:
            gold = (task.gold_label_json or {}).get("scores", {})
            for r in by_task.get(task.id, []):
                for key, gold_v in gold.items():
                    rv = (r.scores_json or {}).get(key)
                    if rv is None:
                        continue
                    s = reviewer_stats[r.reviewer_id]
                    s["total"] += 1
                    try:
                        if float(rv) == float(gold_v):
                            s["exact"] += 1
                        s["abs_diffs"].append(abs(float(rv) - float(gold_v)))
                    except (TypeError, ValueError):
                        if str(rv) == str(gold_v):
                            s["exact"] += 1
        reviewers = {}
        for rid, s in reviewer_stats.items():
            reviewers[rid] = {
                "accuracy": s["exact"] / s["total"] if s["total"] else None,
                "mae_vs_gold": (float(np.mean(s["abs_diffs"])) if s["abs_diffs"] else None),
                "n_scores": s["total"],
            }
        total = sum(s["total"] for s in reviewer_stats.values())
        exact = sum(s["exact"] for s in reviewer_stats.values())
        return {
            "n_gold_tasks": len(tasks),
            "overall_accuracy": exact / total if total else None,
            "by_reviewer": reviewers,
        }

    # ---------------- reviewer reliability trend ----------------
    def reviewer_reliability_trend(self, project_id: str, reviewer_id: str) -> list[dict[str, Any]]:
        """Weekly agreement trend for one reviewer vs their peers."""
        ratings = (
            self._submitted_ratings(project_id)
            if reviewer_id is None
            else [r for r in self._submitted_ratings(project_id) if r.reviewer_id == reviewer_id]
        )
        by_week: dict[str, list[Rating]] = defaultdict(list)
        for r in ratings:
            week = r.submitted_at.strftime("%Y-W%U") if r.submitted_at else "unknown"
            by_week[week].append(r)
        trend = []
        for week in sorted(by_week):
            week_ratings = by_week[week]
            task_ids = {r.task_id for r in week_ratings}
            # agreement = raw exact-match rate on shared items this week
            exact, total = 0, 0
            by_task: dict[str, list[Rating]] = defaultdict(list)
            all_week = [r for r in self._submitted_ratings(project_id) if r.task_id in task_ids]
            for r in all_week:
                by_task[r.task_id].append(r)
            for _tid, rs in by_task.items():
                if len(rs) < 2:
                    continue
                for i in range(len(rs)):
                    for j in range(i + 1, len(rs)):
                        a, b = rs[i], rs[j]
                        if not (a.scores_json and b.scores_json):
                            continue
                        shared_keys = set(a.scores_json) & set(b.scores_json)
                        for k in shared_keys:
                            va, vb = a.scores_json.get(k), b.scores_json.get(k)
                            total += 1
                            try:
                                if float(va) == float(vb):
                                    exact += 1
                            except (TypeError, ValueError):
                                if str(va) == str(vb):
                                    exact += 1
            trend.append(
                {
                    "week": week,
                    "n_ratings": len(week_ratings),
                    "pairwise_agreement": exact / total if total else None,
                }
            )
        return trend

    # ---------------- score distributions & confusion ----------------
    def score_distributions(self, project_id: str) -> dict[str, Any]:
        rubric = self._active_rubric(project_id)
        if rubric is None:
            return {}
        ratings = self._submitted_ratings(project_id)
        out = {}
        for cat in rubric.categories:
            vals = []
            for r in ratings:
                if r.abstained or not r.scores_json:
                    continue
                v = r.scores_json.get(cat.key)
                if v is not None:
                    vals.append(v)
            if cat.scale_type == "categorical":
                # Frequency distribution — no numeric summary statistics
                # are meaningful for nominal labels.
                counts: dict[str, int] = defaultdict(int)
                for v in vals:
                    counts[str(v)] += 1
                out[cat.key] = {
                    "scale_type": "categorical",
                    "n": len(vals),
                    "counts": dict(sorted(counts.items(), key=lambda kv: -kv[1])),
                }
            else:
                dist = st.score_distribution(vals)
                dist["scale_type"] = cat.scale_type
                out[cat.key] = dist
        return out

    def confusion_matrix(self, project_id: str, category_key: str) -> dict[str, Any]:
        """Confusion of reviewer ratings vs gold label for a category."""
        tasks = (
            self.db.query(EvaluationTask)
            .filter(
                EvaluationTask.project_id == project_id,
                EvaluationTask.gold_label_json.isnot(None),
            )
            .all()
        )
        actual, predicted = [], []
        for task in tasks:
            gold = (task.gold_label_json or {}).get("scores", {}).get(category_key)
            if gold is None:
                continue
            for r in task.ratings:
                if r.status != "submitted" or r.abstained or not r.scores_json:
                    continue
                pv = r.scores_json.get(category_key)
                if pv is not None:
                    actual.append(gold)
                    predicted.append(pv)
        mat, labels = st.confusion_matrix(actual, predicted)
        acc, _ = st.accuracy(actual, predicted)
        return {"matrix": mat, "labels": [str(label) for label in labels], "accuracy": acc}

    # ---------------- adjudication stats ----------------
    def adjudication_stats(self, project_id: str) -> dict[str, Any]:
        adjs = (
            self.db.query(Adjudication)
            .join(EvaluationTask, Adjudication.task_id == EvaluationTask.id)
            .filter(EvaluationTask.project_id == project_id)
            .all()
        )
        final = [a for a in adjs if a.status == "final"]
        escalated = [a for a in adjs if a.escalated]
        return {
            "total": len(adjs),
            "final": len(final),
            "pending": len(adjs) - len(final),
            "escalated": len(escalated),
        }

    # ---------------- dashboard aggregate ----------------
    def dashboard(self, project_id: str) -> dict[str, Any]:
        from app.services.project_service import ProjectService

        progress = ProjectService(self.db).project_progress(
            self.db.query(Project).filter(Project.id == project_id).first()
        )
        return {
            "progress": progress,
            "metrics": self.project_metrics(project_id),
            "disagreements": self.disagreement_summary(project_id),
            "adjudication": self.adjudication_stats(project_id),
            "reviewer_bias": self.reviewer_bias(project_id)[:10],
            "accuracy_vs_gold": self.accuracy_vs_gold(project_id),
        }

    def disagreement_summary(self, project_id: str) -> dict[str, Any]:
        rows = self.db.query(Disagreement).filter(Disagreement.project_id == project_id).all()
        by_class: dict[str, int] = defaultdict(int)
        by_kind: dict[str, int] = defaultdict(int)
        by_category: dict[str, int] = defaultdict(int)
        by_status: dict[str, int] = defaultdict(int)
        for d in rows:
            by_class[d.severity_class] += 1
            by_kind[d.kind] += 1
            by_category[d.category_key or "unknown"] += 1
            by_status[d.status] += 1
        return {
            "total": len(rows),
            "by_class": dict(by_class),
            "by_kind": dict(by_kind),
            "by_category": dict(by_category),
            "by_status": dict(by_status),
        }

    # ---------------- calibration analytics ----------------
    def calibration_summary(self, session_id: str) -> dict[str, Any]:
        attempts = self.db.query(CalibrationAttempt).filter(CalibrationAttempt.session_id == session_id).all()
        by_reviewer: dict[str, dict[str, Any]] = defaultdict(dict)
        for a in attempts:
            by_reviewer[a.reviewer_id][a.phase] = {
                "kappa": a.kappa,
                "accuracy": a.accuracy,
                "mae": a.mae,
                "passed": a.passed,
            }
        pre_kappas = [
            a["pre"]["kappa"]
            for a in by_reviewer.values()
            if "pre" in a and a["pre"].get("kappa") is not None
        ]
        post_kappas = [
            a["post"]["kappa"]
            for a in by_reviewer.values()
            if "post" in a and a["post"].get("kappa") is not None
        ]
        pre_accs = [
            a["pre"]["accuracy"]
            for a in by_reviewer.values()
            if "pre" in a and a["pre"].get("accuracy") is not None
        ]
        post_accs = [
            a["post"]["accuracy"]
            for a in by_reviewer.values()
            if "post" in a and a["post"].get("accuracy") is not None
        ]
        return {
            "n_reviewers": len(by_reviewer),
            "by_reviewer": dict(by_reviewer),
            "pre_mean_kappa": float(np.mean(pre_kappas)) if pre_kappas else None,
            "post_mean_kappa": float(np.mean(post_kappas)) if post_kappas else None,
            "pre_mean_accuracy": float(np.mean(pre_accs)) if pre_accs else None,
            "post_mean_accuracy": float(np.mean(post_accs)) if post_accs else None,
            "n_pre": len(pre_accs) + len(pre_kappas),
            "n_post": len(post_accs) + len(post_kappas),
        }
