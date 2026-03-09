"""Statistical tests for agent performance comparison.

Two approaches:

1. Cohen's d (baseline_compare mode) — single O(n) effect size metric.
   Replaces Cliff's delta + Mann-Whitney + Bootstrap CI for baseline
   compare mode where we compare system stats (per-second samples)
   between base (no agent) and initial (with agent) snapshots.

   Thresholds (Cohen, 1988):
     |d| < 0.2  -> negligible
     0.2 - 0.5  -> small
     0.5 - 0.8  -> medium
     >= 0.8     -> large

2. Non-parametric tests (live_compare mode) — three complementary methods:
   - Cliff's delta: effect size
   - Mann-Whitney U: significance test
   - Bootstrap CI: confidence interval on trimmed mean difference

All implementations are pure Python (no scipy/numpy dependency).
"""

import math
import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Cohen's d (baseline_compare mode)
# ---------------------------------------------------------------------------

@dataclass
class CohensDResult:
    """Cohen's d result for one metric."""
    metric: str
    cohens_d: float
    effect_size: str  # "negligible", "small", "medium", "large"
    base_mean: float
    initial_mean: float
    base_std: float
    initial_std: float
    pooled_std: float
    base_n: int
    initial_n: int


@dataclass
class PercentileDetail:
    """Percentile breakdown for base vs initial (shown on cell click)."""
    metric: str
    base_avg: float
    base_p50: float
    base_p90: float
    base_p95: float
    base_p99: float
    base_std: float
    base_n: int
    initial_avg: float
    initial_p50: float
    initial_p90: float
    initial_p95: float
    initial_p99: float
    initial_std: float
    initial_n: int
    delta_avg: float
    delta_p50: float
    delta_p90: float
    delta_p95: float
    delta_p99: float
    delta_std: float


def cohens_d(base: List[float], initial: List[float]) -> Tuple[float, str]:
    """Compute Cohen's d between two sample sets.

    Cohen's d = (mean_initial - mean_base) / pooled_std_dev

    where pooled_std_dev = sqrt(((n1-1)*s1^2 + (n2-1)*s2^2) / (n1+n2-2))

    Positive d means initial > base (agent increased the metric).

    Returns (d, effect_size_label).
    """
    n1 = len(base)
    n2 = len(initial)
    if n1 < 2 or n2 < 2:
        return 0.0, "negligible"

    mean1 = sum(base) / n1
    mean2 = sum(initial) / n2

    var1 = sum((x - mean1) ** 2 for x in base) / (n1 - 1)
    var2 = sum((x - mean2) ** 2 for x in initial) / (n2 - 1)

    pooled_var = ((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2)
    pooled_std = math.sqrt(pooled_var) if pooled_var > 0 else 0.0

    if pooled_std == 0:
        return 0.0, "negligible"

    d = (mean2 - mean1) / pooled_std

    abs_d = abs(d)
    if abs_d < 0.2:
        effect = "negligible"
    elif abs_d < 0.5:
        effect = "small"
    elif abs_d < 0.8:
        effect = "medium"
    else:
        effect = "large"

    return round(d, 4), effect


def compute_cohens_d(
    metric: str,
    base_samples: List[float],
    initial_samples: List[float],
) -> CohensDResult:
    """Compute Cohen's d with full detail for a single metric."""
    n1 = len(base_samples)
    n2 = len(initial_samples)

    mean1 = sum(base_samples) / n1 if n1 > 0 else 0.0
    mean2 = sum(initial_samples) / n2 if n2 > 0 else 0.0

    var1 = sum((x - mean1) ** 2 for x in base_samples) / (n1 - 1) if n1 > 1 else 0.0
    var2 = sum((x - mean2) ** 2 for x in initial_samples) / (n2 - 1) if n2 > 1 else 0.0

    std1 = math.sqrt(var1)
    std2 = math.sqrt(var2)

    d_val, effect = cohens_d(base_samples, initial_samples)
    pooled_var = ((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2) if (n1 + n2 - 2) > 0 else 0.0

    return CohensDResult(
        metric=metric,
        cohens_d=d_val,
        effect_size=effect,
        base_mean=round(mean1, 4),
        initial_mean=round(mean2, 4),
        base_std=round(std1, 4),
        initial_std=round(std2, 4),
        pooled_std=round(math.sqrt(pooled_var), 4) if pooled_var > 0 else 0.0,
        base_n=n1,
        initial_n=n2,
    )


def compute_percentile_detail(
    metric: str,
    base_samples: List[float],
    initial_samples: List[float],
) -> PercentileDetail:
    """Compute percentile breakdown for base vs initial (Table 2 on cell click)."""
    def stats(samples):
        if not samples:
            return 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
        n = len(samples)
        s = sorted(samples)
        avg = sum(samples) / n
        p50 = _percentile(s, 50)
        p90 = _percentile(s, 90)
        p95 = _percentile(s, 95)
        p99 = _percentile(s, 99)
        variance = sum((x - avg) ** 2 for x in samples) / (n - 1) if n > 1 else 0.0
        std = math.sqrt(variance)
        return avg, p50, p90, p95, p99, std

    b_avg, b_p50, b_p90, b_p95, b_p99, b_std = stats(base_samples)
    i_avg, i_p50, i_p90, i_p95, i_p99, i_std = stats(initial_samples)

    return PercentileDetail(
        metric=metric,
        base_avg=round(b_avg, 4), base_p50=round(b_p50, 4),
        base_p90=round(b_p90, 4), base_p95=round(b_p95, 4),
        base_p99=round(b_p99, 4), base_std=round(b_std, 4),
        base_n=len(base_samples),
        initial_avg=round(i_avg, 4), initial_p50=round(i_p50, 4),
        initial_p90=round(i_p90, 4), initial_p95=round(i_p95, 4),
        initial_p99=round(i_p99, 4), initial_std=round(i_std, 4),
        initial_n=len(initial_samples),
        delta_avg=round(i_avg - b_avg, 4), delta_p50=round(i_p50 - b_p50, 4),
        delta_p90=round(i_p90 - b_p90, 4), delta_p95=round(i_p95 - b_p95, 4),
        delta_p99=round(i_p99 - b_p99, 4), delta_std=round(i_std - b_std, 4),
    )


def _percentile(sorted_values: List[float], percentile: float) -> float:
    """Compute percentile using linear interpolation."""
    n = len(sorted_values)
    if n == 0:
        return 0.0
    if n == 1:
        return sorted_values[0]
    k = (percentile / 100.0) * (n - 1)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_values[int(k)]
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)


# ---------------------------------------------------------------------------
# Non-parametric tests (live_compare mode — kept for backward compatibility)
# ---------------------------------------------------------------------------

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
