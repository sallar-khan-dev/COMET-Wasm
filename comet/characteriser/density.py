"""Measured memory-density profiles for COMET-Wasm."""

import csv
import math
import statistics
from bisect import bisect_left
from pathlib import Path

LEVELS = (1, 5, 10, 20, 50, 100, 200)

ROOT = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT / "results/raw/density"


def load_density_profile(model, backend):
    path = RAW_DIR / f"{backend}_{model}_density_full.csv"

    if not path.exists():
        raise FileNotFoundError(path)

    grouped = {level: [] for level in LEVELS}

    with path.open(newline="") as f:
        for row in csv.DictReader(f):
            level = int(float(row["physical_tenants"]))
            if level in grouped:
                grouped[level].append(float(row["pss_mib"]))

    profile = {}

    for level, values in grouped.items():
        if len(values) < 20:
            raise ValueError(
                f"{model}/{backend}: N={level} has "
                f"only {len(values)} repetitions"
            )

        if not all(math.isfinite(v) and v >= 0 for v in values):
            raise ValueError(
                f"Invalid PSS observations at N={level}"
            )

        profile[level] = statistics.mean(values)

    return profile


def estimate_density_memory(model, backend, tenants):
    """Interpolate measured PSS within N=1..200 only."""
    tenants = int(tenants)

    if not LEVELS[0] <= tenants <= LEVELS[-1]:
        raise ValueError(
            "Unsupported tenant count: measured range is 1..200"
        )

    profile = load_density_profile(model, backend)

    if tenants in profile:
        return profile[tenants]

    upper = bisect_left(LEVELS, tenants)

    x0, x1 = LEVELS[upper - 1], LEVELS[upper]
    y0, y1 = profile[x0], profile[x1]

    return y0 + (tenants - x0) * (y1 - y0) / (x1 - x0)
