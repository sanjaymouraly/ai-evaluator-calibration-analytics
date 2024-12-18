"""Unit tests for the statistical engine using hand-computed reference values."""

import math

import pytest

from app.analytics import stats as st

# ---------------------------------------------------------------------------
# Raw agreement & MAD
# ---------------------------------------------------------------------------


def test_raw_agreement_exact():
    val, warns = st.raw_agreement([1, 2, 3], [1, 2, 4])
    assert val == pytest.approx(2 / 3)
    assert warns == []


def test_raw_agreement_missing_data():
    val, warns = st.raw_agreement([1, None, 3], [1, 2, 3])
    assert val == pytest.approx(1.0)
    assert warns == []


def test_raw_agreement_no_pairs():
    val, warns = st.raw_agreement([None], [1])
    assert val is None
    assert warns


def test_mad():
    val, _ = st.mean_absolute_difference([1, 2, 3], [2, 2, 5])
    assert val == pytest.approx((1 + 0 + 2) / 3)


def test_agreement_within_tolerance():
    val, _ = st.agreement_within_tolerance([1.0, 2.0, 3.0], [1.1, 2.4, 3.0], 0.15)
    assert val == pytest.approx(2 / 3)


# ---------------------------------------------------------------------------
# Cohen's kappa
# ---------------------------------------------------------------------------


def test_cohen_kappa_perfect():
    val, warns = st.cohen_kappa([1, 1, 2, 2], [1, 1, 2, 2])
    assert val == pytest.approx(1.0)
    assert warns == []


def test_cohen_kappa_zero_when_independent():
    # po = 0.5, pe = 0.5 -> kappa exactly 0
    val, _ = st.cohen_kappa([1, 1, 2, 2], [1, 2, 1, 2])
    assert val == pytest.approx(0.0)


def test_cohen_kappa_constant_raters_undefined():
    # Both raters always choose category 1 -> pe = 1 -> undefined
    val, warns = st.cohen_kappa([1, 1, 1], [1, 1, 1])
    assert val is None
    assert any("undefined" in w for w in warns)


def test_cohen_kappa_wikipedia_worked_example():
    # 50 grants, 2 raters, categories yes/no (classic example):
    # Both yes=20, both no=15, A yes/B no=5, A no/B yes=10
    a = ["yes"] * 25 + ["no"] * 25
    # positional alignment: 20 both-yes, 5 (A yes/B no), 15 both-no, 10 (A no/B yes)
    b = ["yes"] * 20 + ["no"] * 5 + ["no"] * 15 + ["yes"] * 10
    # po = (20+15)/50 = 0.7 ; pA(yes)=0.5 pB(yes)=0.7 -> pe = .35+.15=.5
    # kappa = (0.7-0.5)/(1-0.5) = 0.4
    val, _ = st.cohen_kappa(a, b)
    assert val == pytest.approx(0.4)


# ---------------------------------------------------------------------------
# Weighted kappa
# ---------------------------------------------------------------------------


def test_weighted_kappa_perfect():
    val, _ = st.weighted_kappa([1, 2, 3, 4], [1, 2, 3, 4])
    assert val == pytest.approx(1.0)


def test_weighted_kappa_weighted_beats_unweighted():
    # Off-by-one errors penalised less with quadratic weights
    a = [1, 1, 2, 2, 3, 3]
    b = [2, 2, 1, 1, 3, 3]
    kw, _ = st.weighted_kappa(a, b)
    ck, _ = st.cohen_kappa(a, b)
    assert kw >= ck


def test_weighted_kappa_quadratic_vs_linear():
    a = [1, 1, 2, 2, 3, 3, 4, 4]
    b = [1, 2, 2, 3, 3, 4, 4, 4]
    quad, _ = st.weighted_kappa(a, b, weighting="quadratic")
    lin, _ = st.weighted_kappa(a, b, weighting="linear")
    assert quad >= lin  # quadratic weights penalise far misses more
    assert 0 <= quad <= 1


def test_weighted_kappa_single_value_undefined():
    val, warns = st.weighted_kappa([2, 2, 2], [2, 2, 2])
    assert val is None
    assert warns


# ---------------------------------------------------------------------------
# Fleiss' kappa (hand-computed)
# ---------------------------------------------------------------------------


def test_fleiss_kappa_all_agree():
    # 3 items, 3 raters, 2 categories; every item unanimous
    matrix = [[3, 0], [3, 0], [0, 3]]
    val, _ = st.fleiss_kappa(matrix)
    assert val == pytest.approx(1.0)


def test_fleiss_kappa_zero_case():
    # Hand-computed: P_bar = 5/9, pe = 5/9 -> kappa = 0
    matrix = [[3, 0], [2, 1], [1, 2]]
    val, _ = st.fleiss_kappa(matrix)
    assert val == pytest.approx(0.0)


def test_fleiss_kappa_negative_case():
    # Hand-computed: P_bar = 7/9, pe = 65/81 -> kappa = -1/8
    matrix = [[3, 0], [3, 0], [2, 1]]
    val, _ = st.fleiss_kappa(matrix)
    assert val == pytest.approx(-0.125)


def test_fleiss_kappa_unequal_coverage_warns():
    matrix = [[3, 0], [2, 1], [1, 1]]  # last item rated by only 2 raters
    val, warns = st.fleiss_kappa(matrix)
    assert val is not None
    assert any("Unequal rater coverage" in w for w in warns)


def test_fleiss_kappa_empty():
    val, warns = st.fleiss_kappa([])
    assert val is None
    assert warns


# ---------------------------------------------------------------------------
# Krippendorff's alpha
# ---------------------------------------------------------------------------


def test_krippendorff_nominal_hand_computed():
    # 4 units x 2 raters; A/A, A/A, B/B, A/B
    # Do = 1/4 ; values: A=5, B=3 -> De = 30/56
    # alpha = 1 - 0.25 / (30/56) = 16/30 = 0.5333
    values = [["A", "A"], ["A", "A"], ["B", "B"], ["A", "B"]]
    val, _ = st.krippendorff_alpha(values, level="nominal")
    assert val == pytest.approx(16 / 30)


def test_krippendorff_perfect():
    values = [[1, 1, 1], [2, 2, 2], [3, 3, 3]]
    val, _ = st.krippendorff_alpha(values, level="nominal")
    assert val == pytest.approx(1.0)


def test_krippendorff_missing_data():
    values = [[1, 1, None], [2, None, 2], [3, 3, 3], [4, 4, 4]]
    val, warns = st.krippendorff_alpha(values, level="nominal")
    assert val == pytest.approx(1.0)
    assert any("missing data" in w for w in warns)  # coverage caveat emitted


def test_krippendorff_constant_undefined():
    values = [[1, 1], [1, 1]]
    val, warns = st.krippendorff_alpha(values, level="nominal")
    assert val is None
    assert any("identical" in w for w in warns)


def test_krippendorff_interval_hand_computed():
    # Interval metric: unit disagreements: |1-2|^2=1, |2-4|^2=4, |3-3|^2=0 -> Do=5/3
    # Values: 1,2,2,3,3,4 -> De = mean over ordered distinct pairs of squared diffs
    values = [[1, 2], [2, 3], [3, 4]]
    flat = [1, 2, 2, 3, 3, 4]
    pairs = [(a, b) for a in flat for b in flat if a is not b]
    de = sum((a - b) ** 2 for a, b in pairs) / (len(flat) * (len(flat) - 1))
    do = (1.0 + 1.0 + 1.0) / 3.0  # |1-2|^2, |2-3|^2, |3-4|^2
    expected = 1 - do / de
    val, _ = st.krippendorff_alpha(values, level="interval")
    assert val == pytest.approx(expected)


def test_krippendorff_ratio_metric():
    values = [[10, 20], [30, 30]]
    # do = ((10-20)/(30))^2 / 2 pairs... only one disagreeing pair: ((10-20)/(10+20))^2 = 1/9
    val, _ = st.krippendorff_alpha(values, level="ratio")
    assert val is not None
    assert 0 <= val <= 1


def test_krippendorff_ordinal():
    values = [[1, 2], [2, 3], [3, 4], [5, 5]]
    val, _ = st.krippendorff_alpha(values, level="ordinal")
    assert val is not None
    assert 0 <= val <= 1


# ---------------------------------------------------------------------------
# ICC(2,1)
# ---------------------------------------------------------------------------


def test_icc_perfect_agreement():
    matrix = [[1, 1], [2, 2], [3, 3]]
    val, warns = st.icc_2_1(matrix)
    assert val == pytest.approx(1.0)
    assert warns == []


def test_icc_known_value():
    # Hand-checked ANOVA: 3 items x 2 raters
    # data: [[1,2],[2,3],[3,5]]
    # grand=8/3; ss_total=1+... computed below
    import numpy as np

    data = np.array([[1.0, 2.0], [2.0, 3.0], [3.0, 5.0]])
    grand = data.mean()
    ss_total = ((data - grand) ** 2).sum()
    row_means = data.mean(axis=1)
    col_means = data.mean(axis=0)
    ss_rows = 2 * ((row_means - grand) ** 2).sum()
    ss_cols = 3 * ((col_means - grand) ** 2).sum()
    ss_error = ss_total - ss_rows - ss_cols
    ms_rows = ss_rows / 2
    ms_cols = ss_cols / 1
    ms_error = ss_error / 2
    expected = (ms_rows - ms_error) / (ms_rows + ms_error + 2 * (ms_cols - ms_error) / 3)
    val, _ = st.icc_2_1(data.tolist())
    assert val == pytest.approx(expected)


def test_icc_constant_undefined():
    val, warns = st.icc_2_1([[3, 3], [3, 3], [3, 3]])
    assert val is None
    assert warns


def test_icc_missing_excluded_with_warning():
    val, warns = st.icc_2_1([[1, 1], [2, None], [3, 3], [4, 4]])
    assert val == pytest.approx(1.0)
    assert any("Excluded" in w for w in warns)


def test_icc_negative_values_allowed():
    # Systematically inverted ratings -> ICC can be negative (worse than chance)
    val, _ = st.icc_2_1([[1, 5], [2, 4], [3, 3], [4, 2], [5, 1]])
    assert val < 0


# ---------------------------------------------------------------------------
# Confusion matrix / accuracy
# ---------------------------------------------------------------------------


def test_confusion_matrix():
    mat, labels = st.confusion_matrix(["cat", "dog", "cat"], ["cat", "cat", "cat"])
    assert labels == ["cat", "dog"]
    assert mat == [[2, 0], [1, 0]]


def test_accuracy():
    val, _ = st.accuracy([1, 0, 1, 1], [1, 0, 0, 1])
    assert val == pytest.approx(0.75)


# ---------------------------------------------------------------------------
# Bootstrap CI
# ---------------------------------------------------------------------------


def test_bootstrap_ci_contains_point():
    xs = [1, 1, 1, 2, 2, 2, 3, 3, 3]
    ys = [1, 1, 2, 2, 2, 3, 3, 3, 3]
    point, lo, hi, warns = st.bootstrap_ci(xs, ys, st.raw_agreement, n_boot=300)
    assert point is not None
    assert lo is not None and hi is not None
    assert lo <= point <= hi
    assert 0 <= lo <= hi <= 1


def test_bootstrap_ci_too_few():
    point, lo, hi, warns = st.bootstrap_ci([1], [1], st.raw_agreement)
    assert lo is None and hi is None
    assert warns


# ---------------------------------------------------------------------------
# Distributions & bias
# ---------------------------------------------------------------------------


def test_score_distribution():
    dist = st.score_distribution([1, 2, 2, 3, None])
    assert dist["n"] == 4
    assert dist["mean"] == pytest.approx(2.0)
    assert dist["median"] == 2.0
    assert dist["histogram"]["2.0"] == 2


def test_reviewer_bias():
    mean, std, warns = st.reviewer_bias([3, 4, 5], [3, 3, 3])
    assert mean == pytest.approx(1.0)
    assert std == pytest.approx(1.0)  # deviations [0,1,2] -> std 1.0
    assert warns == []


def test_reviewer_bias_insufficient():
    mean, std, warns = st.reviewer_bias([3], [3])
    assert mean is None
    assert warns


def test_all_statistics_finite_when_defined():
    rng = np.random.default_rng(7)
    xs = rng.integers(1, 6, 100).tolist()
    ys = [x + (1 if rng.random() < 0.3 else 0) for x in xs]
    for fn in (st.cohen_kappa, lambda a, b: st.weighted_kappa(a, b)):
        val, _ = fn(xs, ys)
        assert val is not None and math.isfinite(val)


import numpy as np  # noqa: E402  (used above)
