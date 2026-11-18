"""Statistics students implement (M2 judge calibration, M4 paired bootstrap).

Rules: a judge is a classifier -- measure it like one. A higher mean is not
"better" until the paired CI of the difference excludes 0.
Reference values to self-check are in tests/test_lab9_stats.py.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from operator import index

POS = "FAIL"   # the judge's job is to FIND failures, so FAIL is the positive class


def confusion(human: Sequence[str], judge: Sequence[str]) -> dict[str, int]:
    """tp/fp/fn/tn with FAIL as positive."""
    if len(human) != len(judge):
        raise ValueError("human and judge labels must have equal lengths")
    if any(label not in {"PASS", POS} for label in (*human, *judge)):
        raise ValueError("labels must be 'PASS' or 'FAIL'")

    tp = sum(h == POS and j == POS for h, j in zip(human, judge))
    fp = sum(h != POS and j == POS for h, j in zip(human, judge))
    fn = sum(h == POS and j != POS for h, j in zip(human, judge))
    tn = sum(h != POS and j != POS for h, j in zip(human, judge))
    return {"tp": tp, "fp": fp, "fn": fn, "tn": tn}


def precision_recall(human: Sequence[str], judge: Sequence[str]) -> tuple[float, float]:
    counts = confusion(human, judge)
    precision_denominator = counts["tp"] + counts["fp"]
    recall_denominator = counts["tp"] + counts["fn"]
    precision = counts["tp"] / precision_denominator if precision_denominator else 0.0
    recall = counts["tp"] / recall_denominator if recall_denominator else 0.0
    return precision, recall


def cohen_kappa(human: Sequence[str], judge: Sequence[str]) -> float:
    """kappa = (p_o - p_e) / (1 - p_e). Raise ValueError when undefined (p_e == 1):
    a constant judge has no signal and must FAIL calibration, not pass on a technicality."""
    counts = confusion(human, judge)
    total = sum(counts.values())
    if total == 0:
        raise ValueError("kappa is undefined for empty label sequences")

    observed_agreement = (counts["tp"] + counts["tn"]) / total
    human_fail_rate = (counts["tp"] + counts["fn"]) / total
    judge_fail_rate = (counts["tp"] + counts["fp"]) / total
    expected_agreement = (
        human_fail_rate * judge_fail_rate
        + (1 - human_fail_rate) * (1 - judge_fail_rate)
    )
    if expected_agreement == 1:
        raise ValueError("kappa is undefined when expected agreement is 1")
    return (observed_agreement - expected_agreement) / (1 - expected_agreement)


def rogan_gladen(observed_rate: float, sensitivity: float, specificity: float) -> float:
    """Correct an observed failure rate for judge error; clip to [0, 1]."""
    rates = (observed_rate, sensitivity, specificity)
    if any(not math.isfinite(rate) or not 0 <= rate <= 1 for rate in rates):
        raise ValueError("observed rate, sensitivity, and specificity must be in [0, 1]")
    denominator = sensitivity + specificity - 1
    if denominator == 0:
        raise ValueError("true rate is undefined when sensitivity + specificity equals 1")
    corrected = (observed_rate + specificity - 1) / denominator
    return min(1.0, max(0.0, corrected))


def paired_bootstrap(a: Sequence[float], b: Sequence[float], *, n_resamples: int = 1000,
                     rng: int = 2027, confidence: float = 0.95) -> tuple[float, float, float]:
    """a[i], b[i] = per-item mean over seeds, SAME items, SAME order.
    Return (mean(a)-mean(b), lo, hi) with scipy.stats.bootstrap(paired=True, method="percentile",
    rng=numpy.random.default_rng(rng)). If a == b everywhere return (0.0, 0.0, 0.0)."""
    import numpy as np
    from scipy import stats

    a_values = np.asarray(a, dtype=float)
    b_values = np.asarray(b, dtype=float)
    if a_values.ndim != 1 or b_values.ndim != 1:
        raise ValueError("paired bootstrap inputs must be one-dimensional")
    if a_values.size == 0 or a_values.size != b_values.size:
        raise ValueError("paired bootstrap inputs must have equal, non-zero lengths")
    if not np.isfinite(a_values).all() or not np.isfinite(b_values).all():
        raise ValueError("paired bootstrap inputs must contain only finite values")
    if n_resamples <= 0:
        raise ValueError("n_resamples must be positive")
    if not math.isfinite(confidence) or not 0 < confidence < 1:
        raise ValueError("confidence must be between 0 and 1")
    if np.array_equal(a_values, b_values):
        return 0.0, 0.0, 0.0

    def mean_difference(left, right):
        return np.mean(left) - np.mean(right)

    result = stats.bootstrap(
        (a_values, b_values),
        mean_difference,
        paired=True,
        vectorized=False,
        n_resamples=n_resamples,
        confidence_level=confidence,
        method="percentile",
        rng=np.random.default_rng(rng),
    )
    difference = float(np.mean(a_values) - np.mean(b_values))
    return (
        difference,
        float(result.confidence_interval.low),
        float(result.confidence_interval.high),
    )


def _validated_pass_k_args(n: int, c: int, k: int) -> tuple[int, int, int]:
    try:
        n, c, k = index(n), index(c), index(k)
    except TypeError as exc:
        raise ValueError("n, c, and k must be integers") from exc
    if n < 1 or c < 0 or c > n or k < 1 or k > n:
        raise ValueError("require n >= 1, 0 <= c <= n, and 1 <= k <= n")
    return n, c, k


def pass_at_k(n: int, c: int, k: int) -> float:
    """Probability that AT LEAST ONE of k trials drawn from n (c of them passing) passes.
    Unbiased estimator (Chen et al. 2021): 1 - C(n-c, k) / C(n, k). Raise ValueError if k > n."""
    n, c, k = _validated_pass_k_args(n, c, k)
    return 1 - math.comb(n - c, k) / math.comb(n, k)


def pass_hat_k(n: int, c: int, k: int) -> float:
    """pass^k (tau-bench, Yao et al. 2024): probability that ALL k trials drawn from n pass.
    Unbiased estimator: C(c, k) / C(n, k). Raise ValueError if k > n.
    pass^k <= pass@1 <= pass@k; a reliable agent keeps pass^k close to pass@1."""
    n, c, k = _validated_pass_k_args(n, c, k)
    return math.comb(c, k) / math.comb(n, k)
