"""Non-parametric statistical tests for agent performance comparison.

Three complementary methods:
  1. Cliff's delta  — effect size (how much did the distribution shift?)
  2. Mann-Whitney U — significance (is the shift real or noise?)
  3. Bootstrap CI   — confidence interval on trimmed mean difference

All implementations are pure Python (no scipy/numpy dependency).
Mann-Whitney uses normal approximation, which is accurate for n > 20.
"""

import math
import random
from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class StatisticalTestResult:
    """Result of running all three tests on one metric."""
    metric: str
    base_n: int
    initial_n: int
    # Cliff's delta
    cliff_delta: float
    cliff_delta_interpretation: str  # "negligible", "small", "medium", "large"
    # Mann-Whitney U
    mann_whitney_u: float
    mann_whitney_p: float
    mann_whitney_significant: bool
    # Bootstrap CI on trimmed mean difference
    bootstrap_mean_diff: float
    bootstrap_ci_low: float
    bootstrap_ci_high: float


def cliff_delta(base: List[float], initial: List[float]) -> Tuple[float, str]:
    """Compute Cliff's delta between two sample sets.

    Cliff's delta = (count(initial > base) - count(initial < base)) / (n1 * n2)

    Interpretation thresholds (Romano et al., 2006):
      |delta| < 0.147  -> negligible
      0.147 - 0.33     -> small
      0.33 - 0.474     -> medium
      >= 0.474          -> large

    Returns (delta, interpretation).
    """
    n1 = len(base)
    n2 = len(initial)
    if n1 == 0 or n2 == 0:
        return 0.0, "negligible"

    # Sort base for binary search to avoid O(n1*n2) comparison
    sorted_base = sorted(base)
    greater = 0
    less = 0

    for val in initial:
        # Count how many base values are less than val (using bisect)
        lo, hi = 0, n1
        while lo < hi:
            mid = (lo + hi) // 2
            if sorted_base[mid] < val:
                lo = mid + 1
            else:
                hi = mid
        count_less = lo  # number of base values < val

        lo2, hi2 = 0, n1
        while lo2 < hi2:
            mid = (lo2 + hi2) // 2
            if sorted_base[mid] <= val:
                lo2 = mid + 1
            else:
                hi2 = mid
        count_le = lo2  # number of base values <= val
        count_equal = count_le - count_less

        greater += count_less
        less += (n1 - count_le)

    delta = (greater - less) / (n1 * n2)

    abs_d = abs(delta)
    if abs_d < 0.147:
        interp = "negligible"
    elif abs_d < 0.33:
        interp = "small"
    elif abs_d < 0.474:
        interp = "medium"
    else:
        interp = "large"

    return round(delta, 6), interp


def mann_whitney_u(base: List[float], initial: List[float]) -> Tuple[float, float]:
    """Mann-Whitney U test (two-sided) using normal approximation.

    Accurate for n > 20 (we typically have 260-780 samples).

    Returns (U_statistic, p_value).
    """
    n1 = len(base)
    n2 = len(initial)
    if n1 == 0 or n2 == 0:
        return 0.0, 1.0

    # Combine and rank
    combined = [(v, 0) for v in base] + [(v, 1) for v in initial]
    combined.sort(key=lambda x: x[0])

    # Assign ranks with tie handling (average rank for ties)
    ranks = [0.0] * len(combined)
    i = 0
    while i < len(combined):
        j = i
        while j < len(combined) and combined[j][0] == combined[i][0]:
            j += 1
        avg_rank = (i + j + 1) / 2.0  # 1-based average rank
        for k in range(i, j):
            ranks[k] = avg_rank
        i = j

    # Sum ranks for the initial group
    r2 = sum(ranks[k] for k in range(len(combined)) if combined[k][1] == 1)

    # U statistic for initial group
    u2 = r2 - n2 * (n2 + 1) / 2
    u1 = n1 * n2 - u2

    # Use the smaller U for two-sided test
    u = min(u1, u2)

    # Normal approximation
    mu = n1 * n2 / 2.0
    n = n1 + n2

    # Tie correction
    # Count tie groups
    tie_sum = 0.0
    i = 0
    while i < len(combined):
        j = i
        while j < len(combined) and combined[j][0] == combined[i][0]:
            j += 1
        t = j - i
        if t > 1:
            tie_sum += t ** 3 - t
        i = j

    sigma = math.sqrt(
        (n1 * n2 / 12.0) * ((n + 1) - tie_sum / (n * (n - 1)))
    ) if n > 1 else 1.0

    if sigma == 0:
        return u, 1.0

    # Z-score with continuity correction
    z = (abs(u - mu) - 0.5) / sigma

    # Two-sided p-value from standard normal (using error function)
    p = 2.0 * _normal_cdf(-abs(z))

    return round(u, 2), round(p, 8)


def bootstrap_ci_trimmed_mean(
    base: List[float],
    initial: List[float],
    n_bootstrap: int = 10000,
    trim_pct: float = 0.05,
    ci: float = 0.95,
    seed: int = 42,
) -> Tuple[float, float, float]:
    """Bootstrap confidence interval on trimmed mean difference.

    Returns (mean_diff, ci_low, ci_high).
    """
    if not base or not initial:
        return 0.0, 0.0, 0.0

    rng = random.Random(seed)
    n1 = len(base)
    n2 = len(initial)

    diffs = []
    for _ in range(n_bootstrap):
        # Resample with replacement
        sample_base = [base[rng.randint(0, n1 - 1)] for _ in range(n1)]
        sample_init = [initial[rng.randint(0, n2 - 1)] for _ in range(n2)]

        # Trimmed means
        tm_base = _trimmed_mean(sample_base, trim_pct)
        tm_init = _trimmed_mean(sample_init, trim_pct)
        diffs.append(tm_init - tm_base)

    diffs.sort()
    alpha = 1.0 - ci
    lo_idx = int(math.floor(alpha / 2.0 * n_bootstrap))
    hi_idx = int(math.ceil((1.0 - alpha / 2.0) * n_bootstrap)) - 1
    lo_idx = max(0, min(lo_idx, n_bootstrap - 1))
    hi_idx = max(0, min(hi_idx, n_bootstrap - 1))

    mean_diff = sum(diffs) / len(diffs)

    return round(mean_diff, 4), round(diffs[lo_idx], 4), round(diffs[hi_idx], 4)


def run_statistical_tests(
    metric: str,
    base_samples: List[float],
    initial_samples: List[float],
    p_threshold: float = 0.05,
) -> StatisticalTestResult:
    """Run all three statistical tests for a single metric.

    Args:
        metric: Metric name (e.g., "cpu_percent")
        base_samples: Raw per-second values from base phase
        initial_samples: Raw per-second values from initial phase
        p_threshold: Significance threshold for Mann-Whitney

    Returns:
        StatisticalTestResult with all test outcomes
    """
    cd, cd_interp = cliff_delta(base_samples, initial_samples)
    u_stat, p_val = mann_whitney_u(base_samples, initial_samples)
    mean_diff, ci_lo, ci_hi = bootstrap_ci_trimmed_mean(base_samples, initial_samples)

    return StatisticalTestResult(
        metric=metric,
        base_n=len(base_samples),
        initial_n=len(initial_samples),
        cliff_delta=cd,
        cliff_delta_interpretation=cd_interp,
        mann_whitney_u=u_stat,
        mann_whitney_p=p_val,
        mann_whitney_significant=p_val < p_threshold,
        bootstrap_mean_diff=mean_diff,
        bootstrap_ci_low=ci_lo,
        bootstrap_ci_high=ci_hi,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _trimmed_mean(values: List[float], trim_pct: float) -> float:
    """Compute trimmed mean (remove trim_pct from each tail)."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    trim_count = max(1, int(n * trim_pct))
    if n > 2 * trim_count:
        trimmed = sorted_vals[trim_count:-trim_count]
        return sum(trimmed) / len(trimmed)
    return sum(sorted_vals) / n


def _normal_cdf(x: float) -> float:
    """Standard normal CDF using the error function approximation."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))
