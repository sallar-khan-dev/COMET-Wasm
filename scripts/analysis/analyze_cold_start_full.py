#!/usr/bin/env python3

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.stats import t as student_t


ROOT = Path(__file__).resolve().parents[2]

RAW = {
    "wasmtime": ROOT / "results/raw/cold_start/wasmtime_naive_bayes_cold_start.csv",
    "docker": ROOT / "results/raw/cold_start/docker_naive_bayes_cold_start.csv",
}

OUT_DIR = ROOT / "results/processed/cold_start"
FIG_DIR = ROOT / "figures"

OUT_DIR.mkdir(parents=True, exist_ok=True)
FIG_DIR.mkdir(parents=True, exist_ok=True)

OUT_CSV = OUT_DIR / "naive_bayes_cold_start_final_comparison.csv"
OUT_JSON = OUT_DIR / "naive_bayes_cold_start_final_analysis.json"

FIG_STARTUP = FIG_DIR / "naive_bayes_cold_start_startup.png"
FIG_COLD = FIG_DIR / "naive_bayes_cold_to_first_result.png"
FIG_DIST = FIG_DIR / "naive_bayes_cold_start_distribution.png"


METRICS = [
    "startup_ms",
    "first_inference_ms",
    "cold_to_first_result_ms",
    "warm_inference_ms",
]


def stats(values):

    values = pd.Series(values, dtype=float)

    n = len(values)
    mean = float(values.mean())
    median = float(values.median())
    sd = float(values.std(ddof=1))

    critical = student_t.ppf(
        0.975,
        df=n - 1
    )

    halfwidth = float(
        critical
        * sd
        / math.sqrt(n)
    )

    return {
        "n": int(n),
        "mean": mean,
        "median": median,
        "sd": sd,
        "ci95_halfwidth": halfwidth,
        "ci95_lower": mean - halfwidth,
        "ci95_upper": mean + halfwidth,
        "relative_ci_pct": (
            halfwidth / abs(mean) * 100.0
            if abs(mean) > 1e-12
            else math.inf
        ),
        "p50": float(
            np.percentile(values, 50)
        ),
        "p95": float(
            np.percentile(values, 95)
        ),
        "p99": float(
            np.percentile(values, 99)
        ),
        "minimum": float(values.min()),
        "maximum": float(values.max()),
        "cv_pct": (
            sd / abs(mean) * 100.0
            if abs(mean) > 1e-12
            else math.inf
        ),
    }


results = {}

for backend, path in RAW.items():

    df = pd.read_csv(path)

    assert len(df) == 60
    assert (df["backend"] == backend).all()

    results[backend] = {
        metric: stats(df[metric])
        for metric in METRICS
    }


rows = []

for metric in METRICS:

    w = results["wasmtime"][metric]
    d = results["docker"][metric]

    ratio = (
        d["mean"] / w["mean"]
        if w["mean"] != 0
        else math.inf
    )

    reduction = (
        1.0
        - w["mean"] / d["mean"]
    ) * 100.0

    rows.append({
        "metric": metric,

        "wasmtime_mean": w["mean"],
        "wasmtime_median": w["median"],
        "wasmtime_ci95_halfwidth": w["ci95_halfwidth"],
        "wasmtime_p95": w["p95"],
        "wasmtime_p99": w["p99"],
        "wasmtime_cv_pct": w["cv_pct"],

        "docker_mean": d["mean"],
        "docker_median": d["median"],
        "docker_ci95_halfwidth": d["ci95_halfwidth"],
        "docker_p95": d["p95"],
        "docker_p99": d["p99"],
        "docker_cv_pct": d["cv_pct"],

        "docker_to_wasmtime_ratio": ratio,
        "wasmtime_reduction_vs_docker_pct": reduction,
    })


comparison = pd.DataFrame(rows)

comparison.to_csv(
    OUT_CSV,
    index=False
)


analysis = {
    "experiment": "naive_bayes_cold_start",
    "repetitions_per_backend": 60,
    "total_observations": 120,
    "wasmtime": results["wasmtime"],
    "docker": results["docker"],
    "comparison": comparison.to_dict(
        orient="records"
    ),
    "interpretation": (
        "Startup and cold-to-first-result are the primary cold-start metrics. "
        "First-inference latency is reported separately because sub-millisecond/"
        "few-millisecond HTTP measurements are relatively noisy and can exhibit "
        "large relative variance."
    ),
}


OUT_JSON.write_text(
    json.dumps(
        analysis,
        indent=2
    )
)


# ------------------------------------------------------------
# Figure 1 — mean startup
# ------------------------------------------------------------

labels = ["Wasmtime", "Docker"]

startup_means = [
    results["wasmtime"]["startup_ms"]["mean"],
    results["docker"]["startup_ms"]["mean"],
]

startup_ci = [
    results["wasmtime"]["startup_ms"]["ci95_halfwidth"],
    results["docker"]["startup_ms"]["ci95_halfwidth"],
]

plt.figure(figsize=(6.2, 4.8))

plt.bar(
    labels,
    startup_means,
    yerr=startup_ci,
    capsize=6,
)

plt.ylabel("Startup to readiness (ms)")
plt.title("Naive Bayes Cold-Start Readiness")
plt.grid(axis="y", alpha=0.25)
plt.tight_layout()

plt.savefig(
    FIG_STARTUP,
    dpi=300,
    bbox_inches="tight"
)

plt.close()


# ------------------------------------------------------------
# Figure 2 — cold-to-first result
# ------------------------------------------------------------

cold_means = [
    results["wasmtime"][
        "cold_to_first_result_ms"
    ]["mean"],

    results["docker"][
        "cold_to_first_result_ms"
    ]["mean"],
]

cold_ci = [
    results["wasmtime"][
        "cold_to_first_result_ms"
    ]["ci95_halfwidth"],

    results["docker"][
        "cold_to_first_result_ms"
    ]["ci95_halfwidth"],
]

plt.figure(figsize=(6.2, 4.8))

plt.bar(
    labels,
    cold_means,
    yerr=cold_ci,
    capsize=6,
)

plt.ylabel("Cold start to first result (ms)")
plt.title("Time to First Inference Result")
plt.grid(axis="y", alpha=0.25)
plt.tight_layout()

plt.savefig(
    FIG_COLD,
    dpi=300,
    bbox_inches="tight"
)

plt.close()


# ------------------------------------------------------------
# Figure 3 — startup distributions
# ------------------------------------------------------------

wasm_df = pd.read_csv(
    RAW["wasmtime"]
)

docker_df = pd.read_csv(
    RAW["docker"]
)

plt.figure(figsize=(7.0, 5.0))

plt.boxplot(
    [
        wasm_df["startup_ms"],
        docker_df["startup_ms"],
    ],
    tick_labels=[
        "Wasmtime",
        "Docker",
    ],
    showfliers=True,
)

plt.ylabel("Startup to readiness (ms)")
plt.title("Cold-Start Distribution Across 60 Fresh Launches")
plt.grid(axis="y", alpha=0.25)
plt.tight_layout()

plt.savefig(
    FIG_DIST,
    dpi=300,
    bbox_inches="tight"
)

plt.close()


# ------------------------------------------------------------
# Terminal report
# ------------------------------------------------------------

print()
print("=" * 84)
print("COMET-Wasm FULL NAIVE BAYES COLD-START ANALYSIS")
print("=" * 84)

for metric in METRICS:

    w = results["wasmtime"][metric]
    d = results["docker"][metric]

    ratio = d["mean"] / w["mean"]

    print()
    print(metric)

    print(
        f"  Wasmtime: "
        f"mean={w['mean']:.3f} ms | "
        f"median={w['median']:.3f} | "
        f"95% CI ±{w['ci95_halfwidth']:.3f} | "
        f"P95={w['p95']:.3f} | "
        f"P99={w['p99']:.3f} | "
        f"CV={w['cv_pct']:.2f}%"
    )

    print(
        f"  Docker:   "
        f"mean={d['mean']:.3f} ms | "
        f"median={d['median']:.3f} | "
        f"95% CI ±{d['ci95_halfwidth']:.3f} | "
        f"P95={d['p95']:.3f} | "
        f"P99={d['p99']:.3f} | "
        f"CV={d['cv_pct']:.2f}%"
    )

    print(
        f"  Docker/Wasmtime = "
        f"{ratio:.2f}x"
    )


print()
print(
    "Primary cold-start result:"
)

startup_ratio = (
    results["docker"]["startup_ms"]["mean"]
    /
    results["wasmtime"]["startup_ms"]["mean"]
)

cold_ratio = (
    results["docker"]["cold_to_first_result_ms"]["mean"]
    /
    results["wasmtime"]["cold_to_first_result_ms"]["mean"]
)

print(
    f"  Startup readiness ratio = "
    f"{startup_ratio:.2f}x"
)

print(
    f"  Cold-to-first-result ratio = "
    f"{cold_ratio:.2f}x"
)

print()
print("Comparison CSV:", OUT_CSV)
print("Analysis JSON:", OUT_JSON)
print("Startup figure:", FIG_STARTUP)
print("Cold-to-first figure:", FIG_COLD)
print("Distribution figure:", FIG_DIST)

print()
print("FULL COLD-START ANALYSIS: PASS")
