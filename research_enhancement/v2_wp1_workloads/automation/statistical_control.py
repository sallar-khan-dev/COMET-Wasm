#!/usr/bin/env python3
"""COMET-Wasm V2: adaptive statistical stopping controller."""

import math
from dataclasses import dataclass

import numpy as np
from scipy.stats import t


MIN_RUNS = 20
MAX_RUNS = 60
CONFIDENCE = 0.95
TARGET_RELATIVE_HALF_WIDTH = 0.025


@dataclass(frozen=True)
class PrecisionResult:
    n: int
    mean: float
    standard_deviation: float
    ci_lower: float
    ci_upper: float
    relative_half_width: float
    target_met: bool
    stop: bool
    reason: str


def evaluate(values):
    """Evaluate independent, positive, finite outer-run observations."""
    samples = np.asarray(values, dtype=float)

    if samples.ndim != 1:
        raise ValueError("Expected a one-dimensional sample")

    n = len(samples)

    if n < 2 or n > MAX_RUNS:
        raise ValueError("Number of observations must be between 2 and 60")

    if not np.all(np.isfinite(samples)):
        raise ValueError("Non-finite observations are prohibited")

    if np.any(samples <= 0):
        raise ValueError("Observations must be positive")

    mean = float(np.mean(samples))
    sd = float(np.std(samples, ddof=1))

    critical = float(t.ppf((1 + CONFIDENCE) / 2, n - 1))
    half_width = critical * sd / math.sqrt(n)
    relative = half_width / abs(mean)

    target_met = n >= MIN_RUNS and relative <= TARGET_RELATIVE_HALF_WIDTH
    stop = target_met or n >= MAX_RUNS

    if target_met:
        reason = "precision_target_met"
    elif n >= MAX_RUNS:
        reason = "maximum_repetitions_reached"
    elif n < MIN_RUNS:
        reason = "minimum_repetitions_not_reached"
    else:
        reason = "continue_sampling"

    return PrecisionResult(
        n=n,
        mean=mean,
        standard_deviation=sd,
        ci_lower=mean - half_width,
        ci_upper=mean + half_width,
        relative_half_width=relative,
        target_met=target_met,
        stop=stop,
        reason=reason,
    )


if __name__ == "__main__":
    stable = [3.0 + 0.001 * (i % 5) for i in range(20)]
    result = evaluate(stable)

    assert result.n == 20
    assert result.target_met
    assert result.stop
    assert result.reason == "precision_target_met"

    early = evaluate(stable[:19])
    assert not early.stop
    assert early.reason == "minimum_repetitions_not_reached"

    variable = [1.0 if i % 2 else 10.0 for i in range(60)]
    result = evaluate(variable)

    assert result.n == 60
    assert result.stop
    assert not result.target_met
    assert result.reason == "maximum_repetitions_reached"

    print("PASS: 95% Student's t confidence interval")
    print("PASS: Minimum 20 repetitions enforced")
    print("PASS: Maximum 60 repetitions enforced")
    print("PASS: Automatic 2.5% precision stopping")
    print("PASS: Maximum-run stopping without false precision claim")
    print("STATISTICAL CONTROLLER FOUNDATION VERIFIED")
