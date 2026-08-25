#!/usr/bin/env python3

import json
import math
from pathlib import Path

import pandas as pd
import matplotlib.pyplot as plt
from scipy.stats import t as student_t


ROOT = Path(__file__).resolve().parents[2]

RAW = {
    "wasmtime": ROOT / "results/raw/performance/wasmtime_naive_bayes_performance_full.csv",
    "docker": ROOT / "results/raw/performance/docker_naive_bayes_performance_full.csv",
}

OUT_DIR = ROOT / "results/processed/performance"
FIG_DIR = ROOT / "figures"

OUT_DIR.mkdir(parents=True, exist_ok=True)
FIG_DIR.mkdir(parents=True, exist_ok=True)

OUT_CSV = OUT_DIR / "naive_bayes_performance_final_comparison.csv"
OUT_JSON = OUT_DIR / "naive_bayes_performance_final_analysis.json"

FIG_RPS = FIG_DIR / "naive_bayes_throughput_vs_concurrency.png"
FIG_P95 = FIG_DIR / "naive_bayes_p95_vs_concurrency.png"
FIG_P99 = FIG_DIR / "naive_bayes_p99_vs_concurrency.png"
FIG_RATIO = FIG_DIR / "naive_bayes_throughput_ratio_vs_concurrency.png"

EXPECTED_LEVELS = [1, 2, 4, 8, 16, 32, 64]

CI_TARGET = 0.025
MIN_REPS = 20
MAX_REPS = 60


def ci(values):
    values = pd.Series(values, dtype=float)

    n = len(values)
    mean = float(values.mean())

    if n < 2:
        return {
            "n": n,
            "mean": mean,
            "sd": 0.0,
            "halfwidth": math.inf,
            "relative": math.inf,
        }

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

    relative = (
        halfwidth / abs(mean)
        if abs(mean) > 1e-12
        else math.inf
    )

    return {
        "n": int(n),
        "mean": mean,
        "sd": sd,
        "halfwidth": halfwidth,
        "lower": mean - halfwidth,
        "upper": mean + halfwidth,
        "relative": relative,
    }


def summarize(path, backend):

    df = pd.read_csv(path)

    assert set(df["concurrency"].unique()) == set(EXPECTED_LEVELS)
    assert (df["backend"] == backend).all()
    assert (df["model"] == "naive_bayes").all()
    assert (df["physical_units"] == 20).all()
    assert (df["requests"] == 5000).all()

    rows = []

    details = {}

    for level in EXPECTED_LEVELS:

        g = df[
            df["concurrency"] == level
        ]

        throughput = ci(
            g["throughput_rps"]
        )

        p95 = ci(
            g["p95_latency_ms"]
        )

        p99 = ci(
            g["p99_latency_ms"]
        )

        mean_latency = ci(
            g["mean_latency_ms"]
        )

        p50 = ci(
            g["p50_latency_ms"]
        )

        p90 = ci(
            g["p90_latency_ms"]
        )

        errors = float(
            g["error_rate"].max()
        )

        stable = (
            len(g) >= MIN_REPS
            and throughput["relative"] <= CI_TARGET
            and p95["relative"] <= CI_TARGET
            and p99["relative"] <= CI_TARGET
        )

        status = (
            "PASS"
            if stable
            else "MAX-REPS"
            if len(g) >= MAX_REPS
            else "INCOMPLETE"
        )

        row = {
            "backend": backend,
            "concurrency": level,
            "n": len(g),

            "throughput_rps": throughput["mean"],
            "throughput_ci95_halfwidth": throughput["halfwidth"],
            "throughput_relative_ci_pct": throughput["relative"] * 100.0,

            "mean_latency_ms": mean_latency["mean"],
            "p50_latency_ms": p50["mean"],
            "p90_latency_ms": p90["mean"],

            "p95_latency_ms": p95["mean"],
            "p95_ci95_halfwidth": p95["halfwidth"],
            "p95_relative_ci_pct": p95["relative"] * 100.0,

            "p99_latency_ms": p99["mean"],
            "p99_ci95_halfwidth": p99["halfwidth"],
            "p99_relative_ci_pct": p99["relative"] * 100.0,

            "max_error_rate": errors,
            "status": status,
        }

        rows.append(row)

        details[str(level)] = row.copy()

    return pd.DataFrame(rows), details


wasm, wasm_details = summarize(
    RAW["wasmtime"],
    "wasmtime"
)

docker, docker_details = summarize(
    RAW["docker"],
    "docker"
)


comparison = pd.merge(
    wasm,
    docker,
    on="concurrency",
    suffixes=("_wasmtime", "_docker")
)


comparison[
    "throughput_ratio_wasmtime_to_docker"
] = (
    comparison["throughput_rps_wasmtime"]
    /
    comparison["throughput_rps_docker"]
)


comparison[
    "throughput_improvement_pct"
] = (
    comparison[
        "throughput_ratio_wasmtime_to_docker"
    ] - 1.0
) * 100.0


comparison[
    "p95_reduction_pct"
] = (
    1.0
    -
    comparison["p95_latency_ms_wasmtime"]
    /
    comparison["p95_latency_ms_docker"]
) * 100.0


comparison[
    "p99_reduction_pct"
] = (
    1.0
    -
    comparison["p99_latency_ms_wasmtime"]
    /
    comparison["p99_latency_ms_docker"]
) * 100.0


comparison.to_csv(
    OUT_CSV,
    index=False
)


# ------------------------------------------------------------
# Peak/saturation analysis
# ------------------------------------------------------------

wasm_peak_row = wasm.loc[
    wasm["throughput_rps"].idxmax()
]

docker_peak_row = docker.loc[
    docker["throughput_rps"].idxmax()
]

analysis = {
    "experiment": "naive_bayes_multitenant_performance",
    "physical_units": 20,
    "requests_per_repetition": 5000,
    "concurrency_levels": EXPECTED_LEVELS,

    "raw_observations": {
        "wasmtime": int(
            sum(wasm["n"])
        ),
        "docker": int(
            sum(docker["n"])
        ),
        "total": int(
            sum(wasm["n"])
            + sum(docker["n"])
        ),
    },

    "wasmtime_peak": {
        "concurrency": int(
            wasm_peak_row["concurrency"]
        ),
        "throughput_rps": float(
            wasm_peak_row["throughput_rps"]
        ),
    },

    "docker_peak": {
        "concurrency": int(
            docker_peak_row["concurrency"]
        ),
        "throughput_rps": float(
            docker_peak_row["throughput_rps"]
        ),
    },

    "wasmtime": wasm_details,
    "docker": docker_details,

    "comparison": comparison.to_dict(
        orient="records"
    ),

    "interpretation_note": (
        "MAX-REPS does not imply invalid data. It indicates that "
        "the predefined 2.5% relative 95% CI target was not reached "
        "for all primary metrics within 60 repetitions. Such points "
        "are retained and explicitly marked rather than removed."
    ),
}

OUT_JSON.write_text(
    json.dumps(
        analysis,
        indent=2
    )
)


# ------------------------------------------------------------
# Figure 1 — Throughput
# ------------------------------------------------------------

plt.figure(figsize=(8, 5.2))

plt.errorbar(
    wasm["concurrency"],
    wasm["throughput_rps"],
    yerr=wasm["throughput_ci95_halfwidth"],
    marker="o",
    capsize=4,
    label="Wasmtime"
)

plt.errorbar(
    docker["concurrency"],
    docker["throughput_rps"],
    yerr=docker["throughput_ci95_halfwidth"],
    marker="s",
    capsize=4,
    label="Docker"
)

plt.xlabel("Client concurrency")
plt.ylabel("Throughput (requests/s)")
plt.title("Naive Bayes Multi-Tenant Throughput")
plt.xticks(EXPECTED_LEVELS)
plt.grid(alpha=0.25)
plt.legend()
plt.tight_layout()
plt.savefig(FIG_RPS, dpi=300, bbox_inches="tight")
plt.close()


# ------------------------------------------------------------
# Figure 2 — P95
# ------------------------------------------------------------

plt.figure(figsize=(8, 5.2))

plt.errorbar(
    wasm["concurrency"],
    wasm["p95_latency_ms"],
    yerr=wasm["p95_ci95_halfwidth"],
    marker="o",
    capsize=4,
    label="Wasmtime"
)

plt.errorbar(
    docker["concurrency"],
    docker["p95_latency_ms"],
    yerr=docker["p95_ci95_halfwidth"],
    marker="s",
    capsize=4,
    label="Docker"
)

plt.xlabel("Client concurrency")
plt.ylabel("P95 latency (ms)")
plt.title("Naive Bayes P95 Tail Latency")
plt.xticks(EXPECTED_LEVELS)
plt.grid(alpha=0.25)
plt.legend()
plt.tight_layout()
plt.savefig(FIG_P95, dpi=300, bbox_inches="tight")
plt.close()


# ------------------------------------------------------------
# Figure 3 — P99
# ------------------------------------------------------------

plt.figure(figsize=(8, 5.2))

plt.errorbar(
    wasm["concurrency"],
    wasm["p99_latency_ms"],
    yerr=wasm["p99_ci95_halfwidth"],
    marker="o",
    capsize=4,
    label="Wasmtime"
)

plt.errorbar(
    docker["concurrency"],
    docker["p99_latency_ms"],
    yerr=docker["p99_ci95_halfwidth"],
    marker="s",
    capsize=4,
    label="Docker"
)

plt.xlabel("Client concurrency")
plt.ylabel("P99 latency (ms)")
plt.title("Naive Bayes P99 Tail Latency")
plt.xticks(EXPECTED_LEVELS)
plt.grid(alpha=0.25)
plt.legend()
plt.tight_layout()
plt.savefig(FIG_P99, dpi=300, bbox_inches="tight")
plt.close()


# ------------------------------------------------------------
# Figure 4 — throughput ratio
# ------------------------------------------------------------

plt.figure(figsize=(8, 5.2))

plt.plot(
    comparison["concurrency"],
    comparison[
        "throughput_ratio_wasmtime_to_docker"
    ],
    marker="o",
)

plt.axhline(
    1.0,
    linestyle="--"
)

plt.xlabel("Client concurrency")
plt.ylabel("Wasmtime / Docker throughput ratio")
plt.title("Relative Throughput Advantage")
plt.xticks(EXPECTED_LEVELS)
plt.grid(alpha=0.25)
plt.tight_layout()
plt.savefig(FIG_RATIO, dpi=300, bbox_inches="tight")
plt.close()


# ------------------------------------------------------------
# Terminal report
# ------------------------------------------------------------

print()
print("=" * 88)
print("COMET-Wasm FULL NAIVE BAYES PERFORMANCE ANALYSIS")
print("=" * 88)

print()
print(
    f"Wasmtime raw observations: {int(sum(wasm['n']))}"
)
print(
    f"Docker raw observations:   {int(sum(docker['n']))}"
)
print(
    f"Total observations:        "
    f"{int(sum(wasm['n']) + sum(docker['n']))}"
)

print()
print(
    f"Wasmtime peak throughput: "
    f"{wasm_peak_row['throughput_rps']:.1f} req/s "
    f"at C={int(wasm_peak_row['concurrency'])}"
)

print(
    f"Docker peak throughput:   "
    f"{docker_peak_row['throughput_rps']:.1f} req/s "
    f"at C={int(docker_peak_row['concurrency'])}"
)

print()
print(
    " C | Wasm RPS | Docker RPS | Ratio | "
    "Wasm P95 | Docker P95 | Wasm P99 | Docker P99 | Status"
)

print("-" * 115)

for _, r in comparison.iterrows():

    print(
        f"{int(r['concurrency']):>2} | "
        f"{r['throughput_rps_wasmtime']:>8.1f} | "
        f"{r['throughput_rps_docker']:>10.1f} | "
        f"{r['throughput_ratio_wasmtime_to_docker']:>5.2f}x | "
        f"{r['p95_latency_ms_wasmtime']:>8.3f} | "
        f"{r['p95_latency_ms_docker']:>10.3f} | "
        f"{r['p99_latency_ms_wasmtime']:>8.3f} | "
        f"{r['p99_latency_ms_docker']:>10.3f} | "
        f"{r['status_wasmtime']}/{r['status_docker']}"
    )

print()
print("Comparison CSV:", OUT_CSV)
print("Analysis JSON:", OUT_JSON)
print("Throughput figure:", FIG_RPS)
print("P95 figure:", FIG_P95)
print("P99 figure:", FIG_P99)
print("Ratio figure:", FIG_RATIO)

print()
print("FULL PERFORMANCE ANALYSIS: PASS")
