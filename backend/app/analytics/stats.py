"""Transparent, unit-tested statistical agreement engine.

All functions are pure Python (numpy only for bootstrap vectorization) and
operate on plain lists/matrices so they can be validated independently of
the database. Missing values are ``None`` and are handled pairwise.

Measurement levels follow Krippendorff (2011):
  nominal   — category labels, no order
  ordinal   — ordered categories
  interval  — numeric, equal spacing, no true zero
  ratio     — numeric with true zero

Every function returns ``(value_or_None, warnings)`` so callers can surface
assumption violations instead of printing misleading numbers.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from typing import Any

import numpy as np

Warning = str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pairs(xs: Sequence, ys: Sequence) -> list[tuple[Any, Any]]:
    """Complete-case pairs (drop rows where either value is missing)."""
    out = []
    for a, b in zip(xs, ys, strict=False):
        if a is None or b is None:
            continue
        out.append((a, b))
    return out


def _is_constant(values: Sequence) -> bool:
    vals = [v for v in values if v is not None]
    return len(vals) > 0 and all(v == vals[0] for v in vals)


def _category_counts(values: Sequence) -> dict[Any, int]:
    counts: dict[Any, int] = {}
    for v in values:
        if v is None:
            continue
        counts[v] = counts.get(v, 0) + 1
    return counts


# ---------------------------------------------------------------------------
# Basic agreement
# ---------------------------------------------------------------------------


def raw_agreement(xs: Sequence, ys: Sequence) -> tuple[float | None, list[Warning]]:
    """Proportion of complete-case pairs with identical values."""
    pairs = _pairs(xs, ys)
    if len(pairs) < 1:
        return None, ["No complete rating pairs; raw agreement undefined."]
    agree = sum(1 for a, b in pairs if a == b)
    return agree / len(pairs), []


def agreement_within_tolerance(
    xs: Sequence, ys: Sequence, tolerance: float
) -> tuple[float | None, list[Warning]]:
    """Agreement allowing numeric difference <= tolerance."""
    pairs = _pairs(xs, ys)
    if len(pairs) < 1:
        return None, ["No complete rating pairs."]
    agree = sum(1 for a, b in pairs if abs(float(a) - float(b)) <= tolerance)
    return agree / len(pairs), []


def mean_absolute_difference(xs: Sequence, ys: Sequence) -> tuple[float | None, list[Warning]]:
    """Mean absolute difference for interval/ratio scores."""
    pairs = _pairs(xs, ys)
    if len(pairs) < 1:
        return None, ["No complete rating pairs; MAD undefined."]
    mad = sum(abs(float(a) - float(b)) for a, b in pairs) / len(pairs)
    return mad, []


# ---------------------------------------------------------------------------
# Cohen's kappa (2 raters, categorical)
# ---------------------------------------------------------------------------


def cohen_kappa(xs: Sequence, ys: Sequence) -> tuple[float | None, list[Warning]]:
    warnings: list[Warning] = []
    pairs = _pairs(xs, ys)
    n = len(pairs)
    if n < 1:
        return None, ["No complete rating pairs; Cohen's kappa undefined."]
    if n < 2:
        warnings.append("Only 1 paired rating; kappa is not meaningful for a single item.")
    cx = _category_counts([a for a, _ in pairs])
    cy = _category_counts([b for _, b in pairs])
    categories = sorted(set(cx) | set(cy), key=str)
    po = sum(1 for a, b in pairs if a == b) / n
    pe = sum((cx.get(c, 0) / n) * (cy.get(c, 0) / n) for c in categories)
    if pe >= 1.0 - 1e-12:
        warnings.append(
            "Expected agreement pe=1 (raters constant and identical); "
            "Cohen's kappa is undefined. Raw agreement is reported instead."
        )
        return None, warnings
    kappa = (po - pe) / (1 - pe)
    return float(np.clip(kappa, -1.0, 1.0)), warnings


# ---------------------------------------------------------------------------
# Weighted Cohen's kappa (ordinal)
# ---------------------------------------------------------------------------


def weighted_kappa(
    xs: Sequence, ys: Sequence, weighting: str = "quadratic"
) -> tuple[float | None, list[Warning]]:
    """Linear or quadratic weighted kappa for ordinal scales."""
    warnings: list[Warning] = []
    pairs = _pairs(xs, ys)
    n = len(pairs)
    if n < 1:
        return None, ["No complete rating pairs; weighted kappa undefined."]
    # Ordered categories
    try:
        all_vals = sorted({v for pair in pairs for v in pair}, key=lambda v: float(v))
    except (TypeError, ValueError):
        return None, ["Weighted kappa requires ordered numeric categories."]
    k = len(all_vals)
    if k < 2:
        return None, ["Only one distinct value present; weighted kappa undefined."]
    idx = {v: i for i, v in enumerate(all_vals)}

    def w(i: int, j: int) -> float:
        if weighting == "linear":
            return abs(i - j) / (k - 1)
        return ((i - j) / (k - 1)) ** 2

    obs = np.zeros((k, k))
    for a, b in pairs:
        obs[idx[a]][idx[b]] += 1
    obs /= n
    px = obs.sum(axis=1)
    py = obs.sum(axis=0)
    exp = np.outer(px, py)
    W = np.array([[w(i, j) for j in range(k)] for i in range(k)])
    num = float((W * obs).sum())
    den = float((W * exp).sum())
    if den <= 1e-12:
        return None, ["Weighted kappa undefined: expected weighted disagreement is zero."]
    kw = 1.0 - num / den
    return float(np.clip(kw, -1.0, 1.0)), warnings


# ---------------------------------------------------------------------------
# Fleiss' kappa (n items, k raters each, categorical)
# ---------------------------------------------------------------------------


def fleiss_kappa(
    item_category_counts: Sequence[Sequence[int]],
) -> tuple[float | None, list[Warning]]:
    """Fleiss' kappa for a fixed number of raters per item.

    ``item_category_counts[i][j]`` = number of raters who assigned item i
    to category j. Assumes every item is rated by the same number of raters;
    a warning is emitted otherwise.
    """
    warnings: list[Warning] = []
    if not item_category_counts:
        return None, ["No items provided; Fleiss' kappa undefined."]
    n_items = len(item_category_counts)
    k = sum(item_category_counts[0])
    if k < 2:
        return None, ["Fewer than 2 raters per item; Fleiss' kappa undefined."]
    counts = [list(row) for row in item_category_counts]
    n_raters = [sum(row) for row in counts]
    if len(set(n_raters)) != 1:
        warnings.append(
            "Unequal rater coverage across items: Fleiss' kappa assumes a "
            "constant number of raters per item; treat the result as approximate."
        )
    n_cat = len(counts[0])
    # P_i per item
    p_is = []
    for row in counts:
        p_is.append((sum(c * c for c in row) - k) / (k * (k - 1)))
    p_bar = sum(p_is) / n_items
    # p_j category proportions
    p_js = [sum(row[j] for row in counts) / (n_items * k) for j in range(n_cat)]
    pe = sum(pj * pj for pj in p_js)
    if pe >= 1.0 - 1e-12:
        warnings.append("Expected agreement pe=1 (single category dominates); Fleiss' kappa undefined.")
        return None, warnings
    kappa = (p_bar - pe) / (1 - pe)
    return float(np.clip(kappa, -1.0, 1.0)), warnings


# ---------------------------------------------------------------------------
# Krippendorff's alpha (nominal/ordinal/interval/ratio, missing-data safe)
# ---------------------------------------------------------------------------


def _nominal_delta(a: Any, b: Any) -> float:
    return 0.0 if a == b else 1.0


def _interval_delta(a: Any, b: Any) -> float:
    return float(a - b) ** 2


def _ratio_delta(a: Any, b: Any) -> float:
    denom = float(a) + float(b)
    return 0.0 if denom == 0 else ((float(a) - float(b)) / denom) ** 2


def krippendorff_alpha(
    values: Sequence[Sequence[Any | None]], level: str = "nominal"
) -> tuple[float | None, list[Warning]]:
    """Krippendorff's alpha with support for missing ratings.

    ``values`` is a list of items; each item is a list of ratings (one per
    rater, ``None`` when that rater did not rate the item).

    Ordinal delta uses the normalized rank-difference form
    delta^2 = (rank(a)-rank(b))^2 / (V-1)^2 where V is the number of distinct
    observed values — a bounded, transparent approximation appropriate for
    Likert-style scales.
    """
    warnings: list[Warning] = []
    if len(values) < 2:
        return None, ["Krippendorff's alpha needs at least 2 units."]

    metric: Callable[[Any, Any], float]
    if level == "nominal":
        metric = _nominal_delta
    elif level == "interval":
        metric = _interval_delta
    elif level == "ratio":
        metric = _ratio_delta
    elif level == "ordinal":
        metric = _ordinal_metric_factory(values)
    else:
        raise ValueError(f"Unknown measurement level: {level}")

    # Observed disagreement over all rater pairs within each unit
    do_sum = 0.0
    do_pairs = 0
    for unit in values:
        present = [v for v in unit if v is not None]
        m = len(present)
        if m < 2:
            continue
        for i in range(m):
            for j in range(i + 1, m):
                do_sum += metric(present[i], present[j])
                do_pairs += 1
    if do_pairs == 0:
        return None, ["No item has two or more ratings; alpha undefined."]
    do = do_sum / do_pairs

    # Expected disagreement over all value pairs in the sample
    flat = [v for unit in values for v in unit if v is not None]
    n_vals = len(flat)
    if n_vals < 2:
        return None, ["Fewer than two non-missing values; alpha undefined."]
    counts = _category_counts(flat)
    distinct = list(counts.keys())
    if len(distinct) < 2:
        warnings.append(
            "All observed ratings are identical (no variance); alpha is undefined "
            "because expected disagreement is zero. Agreement is perfect by raw measure."
        )
        return None, warnings
    de_sum = 0.0
    for v1 in distinct:
        for v2 in distinct:
            de_sum += counts[v1] * counts[v2] * metric(v1, v2)
    de = de_sum / (n_vals * (n_vals - 1))
    if de <= 1e-12:
        return None, ["Expected disagreement is zero; alpha undefined."]

    alpha = 1.0 - do / de
    if do == 0.0:
        alpha = 1.0
    coverage = do_pairs / max(1, sum(1 for u in values for _ in u))
    if coverage < 0.9:
        warnings.append(
            f"Substantial missing data (pair coverage {coverage:.0%}); interpret alpha with caution."
        )
    return float(alpha), warnings


def _ordinal_metric_factory(values: Sequence[Sequence[Any | None]]) -> Callable[[Any, Any], float]:
    distinct = sorted({v for unit in values for v in unit if v is not None}, key=lambda v: float(v))
    v = max(len(distinct) - 1, 1)
    rank = {val: i for i, val in enumerate(distinct)}

    def delta(a: Any, b: Any) -> float:
        return ((rank[a] - rank[b]) / v) ** 2

    return delta


# ---------------------------------------------------------------------------
# Intraclass correlation (ICC 2,1) — two-way random, absolute agreement,
# single rater, for interval/ratio numeric ratings.
# ---------------------------------------------------------------------------


def icc_2_1(matrix: Sequence[Sequence[float | None]]) -> tuple[float | None, list[Warning]]:
    """ICC(2,1) via one-way/repeated-measures ANOVA decomposition.

    Requires a complete n x k matrix; rows with any missing value are excluded
    and a caveat is emitted. Negative ICC values indicate reliability worse
    than chance and are returned as-is (not clipped to 0).
    """
    warnings: list[Warning] = []
    complete = [row for row in matrix if all(v is not None for v in row) and len(row) >= 2]
    if len(complete) != len(matrix):
        warnings.append(f"Excluded {len(matrix) - len(complete)} item(s) with missing ratings from ICC.")
    if len(complete) < 3:
        return None, ["ICC requires at least 3 items with complete rater coverage."]
    data = np.array(complete, dtype=float)
    n, k = data.shape
    if n < 2 or k < 2:
        return None, ["ICC requires at least 2 items and 2 raters."]
    grand = data.mean()
    ss_total = ((data - grand) ** 2).sum()
    if ss_total == 0:
        return None, ["All ratings identical; ICC undefined (no variance)."]
    row_means = data.mean(axis=1)
    col_means = data.mean(axis=0)
    ss_rows = k * ((row_means - grand) ** 2).sum()
    ss_cols = n * ((col_means - grand) ** 2).sum()
    ss_error = ss_total - ss_rows - ss_cols
    ms_rows = ss_rows / (n - 1)
    ms_cols = ss_cols / (k - 1)
    ms_error = ss_error / ((n - 1) * (k - 1))
    denom = ms_rows + (k - 1) * ms_error + k * (ms_cols - ms_error) / n
    if denom == 0:
        return None, ["ICC denominator is zero; metric undefined for this data."]
    icc = (ms_rows - ms_error) / denom
    return float(np.clip(icc, -1.0, 1.0)), warnings


# ---------------------------------------------------------------------------
# Confusion matrix & accuracy vs reference labels
# ---------------------------------------------------------------------------


def confusion_matrix(
    actual: Sequence, predicted: Sequence, labels: Sequence | None = None
) -> tuple[list[list[int]], list[str]]:
    if labels is None:
        labels = sorted(set(list(actual) + list(predicted)), key=str)  # type: ignore[arg-type]
    labels = list(labels)
    idx = {lab: i for i, lab in enumerate(labels)}
    mat = [[0] * len(labels) for _ in labels]
    for a, p in _pairs(actual, predicted):
        mat[idx[a]][idx[p]] += 1
    return mat, labels


def accuracy(actual: Sequence, predicted: Sequence) -> tuple[float | None, list[Warning]]:
    pairs = _pairs(actual, predicted)
    if not pairs:
        return None, ["No paired reference/rating values; accuracy undefined."]
    return sum(1 for a, p in pairs if a == p) / len(pairs), []


# ---------------------------------------------------------------------------
# Bootstrap confidence intervals (percentile method)
# ---------------------------------------------------------------------------


def bootstrap_ci(
    xs: Sequence,
    ys: Sequence,
    statistic: Callable[[Sequence, Sequence], tuple[float | None, list]],
    n_boot: int = 1000,
    confidence: float = 0.95,
    seed: int = 42,
) -> tuple[float | None, float | None, float | None, list[Warning]]:
    """Bootstrap percentile CI for a paired statistic (point, lo, hi)."""
    warnings: list[Warning] = []
    pairs = _pairs(xs, ys)
    point, _ = statistic(xs, ys)
    if point is None or len(pairs) < 2:
        return point, None, None, ["Too few pairs for a bootstrap interval."]
    rng = np.random.default_rng(seed)
    arr = np.array(pairs, dtype=object)
    n = len(arr)
    stats: list[float] = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, size=n)
        sample_x = arr[idx, 0].tolist()
        sample_y = arr[idx, 1].tolist()
        val, _ = statistic(sample_x, sample_y)
        if val is not None and math.isfinite(val):
            stats.append(val)
    if len(stats) < n_boot * 0.5:
        warnings.append("Bootstrap produced many undefined resamples; interval may be unstable.")
    if not stats:
        return point, None, None, warnings
    lo = float(np.percentile(stats, (1 - confidence) / 2 * 100))
    hi = float(np.percentile(stats, (1 + confidence) / 2 * 100))
    return point, lo, hi, warnings


# ---------------------------------------------------------------------------
# Distribution helpers
# ---------------------------------------------------------------------------


def score_distribution(values: Sequence) -> dict[str, Any]:
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return {"n": 0, "mean": None, "median": None, "std": None, "min": None, "max": None}
    arr = np.array(vals)
    return {
        "n": len(vals),
        "mean": float(arr.mean()),
        "median": float(np.median(arr)),
        "std": float(arr.std(ddof=1)) if len(vals) > 1 else 0.0,
        "min": float(arr.min()),
        "max": float(arr.max()),
        "histogram": {str(v): int((arr == v).sum()) for v in sorted(set(vals))},
    }


def reviewer_bias(
    reviewer_scores: Sequence[float], consensus_scores: Sequence[float]
) -> tuple[float | None, float | None, list[Warning]]:
    """Mean signed deviation (severity/leniency bias) and its std."""
    pairs = _pairs(reviewer_scores, consensus_scores)
    if len(pairs) < 3:
        return None, None, ["Fewer than 3 paired scores; bias estimate unreliable."]
    dev = [float(a) - float(b) for a, b in pairs]
    arr = np.array(dev)
    return float(arr.mean()), float(arr.std(ddof=1)), []
