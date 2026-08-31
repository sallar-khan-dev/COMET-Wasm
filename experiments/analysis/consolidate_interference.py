#!/usr/bin/env python3

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]

IN_DIR = ROOT / "results/processed/interference"
OUT_DIR = IN_DIR
FIG_DIR = ROOT / "figures/interference"

FIG_DIR.mkdir(parents=True, exist_ok=True)


PAIRS = [
    "nb_nb",
    "lr_lr",
    "lr_svm",
    "kmeans_rf",
    "dt_mlp",
    "svm_mlp",
]

PAIR_LABELS = {
    "nb_nb": "NB + NB",
    "lr_lr": "LR + LR",
    "lr_svm": "LR + SVM",
    "kmeans_rf": "K-Means + RF",
    "dt_mlp": "DT + MLP",
    "svm_mlp": "SVM + MLP",
}


rows = []

for pair in PAIRS:

    for backend in [
        "wasmtime",
        "docker",
    ]:

        path = (
            IN_DIR
            / f"{backend}_{pair}_interference_full_summary.json"
        )

        if not path.exists():
            raise FileNotFoundError(path)

        data = json.loads(
            path.read_text()
        )

        for stream_name in [
            "stream_a",
            "stream_b",
        ]:

            stream = data[
                stream_name
            ]

            model = (
                data["model_a"]
                if stream_name == "stream_a"
                else data["model_b"]
            )

            rows.append({
                "backend":
                    backend,

                "pair":
                    pair,

                "pair_label":
                    PAIR_LABELS[pair],

                "stream":
                    stream_name,

                "model":
                    model,

                "repetitions":
                    int(
                        data["repetitions"]
                    ),

                "ci_pass":
                    bool(
                        data["ci_pass"]
                    ),

                "solo_p95_ms":
                    float(
                        stream[
                            "solo_p95_latency_ms"
                        ]
                    ),

                "mixed_p95_ms":
                    float(
                        stream[
                            "mixed_p95_latency_ms"
                        ]["mean"]
                    ),

                "p95_ci_pct":
                    float(
                        stream[
                            "mixed_p95_latency_ms"
                        ]["relative"]
                    ) * 100.0,

                "solo_throughput_rps":
                    float(
                        stream[
                            "solo_throughput_rps"
                        ]
                    ),

                "mixed_throughput_rps":
                    float(
                        stream[
                            "mixed_throughput_rps"
                        ]["mean"]
                    ),

                "throughput_ci_pct":
                    float(
                        stream[
                            "mixed_throughput_rps"
                        ]["relative"]
                    ) * 100.0,

                "p95_degradation_pct":
                    float(
                        stream[
                            "p95_degradation_pct"
                        ]
                    ),

                "throughput_degradation_pct":
                    float(
                        stream[
                            "throughput_degradation_pct"
                        ]
                    ),

                "mixed_p99_ms":
                    float(
                        stream[
                            "mixed_p99_latency_ms_mean"
                        ]
                    ),

                "error_rate":
                    float(
                        stream[
                            "mixed_error_rate_mean"
                        ]
                    ),
            })


df = pd.DataFrame(
    rows
)


# ============================================================
# Save full per-stream comparison
# ============================================================

comparison_csv = (
    OUT_DIR
    / "interference_final_comparison.csv"
)

df.to_csv(
    comparison_csv,
    index=False,
)


# ============================================================
# Pair-level means
# ============================================================

pair_df = (
    df.groupby(
        [
            "backend",
            "pair",
            "pair_label",
        ],
        as_index=False,
    )
    .agg(
        mean_p95_degradation_pct=(
            "p95_degradation_pct",
            "mean",
        ),

        mean_throughput_degradation_pct=(
            "throughput_degradation_pct",
            "mean",
        ),

        mean_mixed_p99_ms=(
            "mixed_p99_ms",
            "mean",
        ),

        mean_error_rate=(
            "error_rate",
            "mean",
        ),

        repetitions=(
            "repetitions",
            "max",
        ),

        ci_pass=(
            "ci_pass",
            "all",
        ),
    )
)


pair_csv = (
    OUT_DIR
    / "interference_pair_summary.csv"
)

pair_df.to_csv(
    pair_csv,
    index=False,
)


# ============================================================
# Publication table
# ============================================================

publication = pair_df[
    [
        "pair_label",
        "backend",
        "mean_p95_degradation_pct",
        "mean_throughput_degradation_pct",
        "mean_mixed_p99_ms",
        "repetitions",
        "ci_pass",
    ]
].copy()

publication.columns = [
    "Pair",
    "Backend",
    "Mean P95 Degradation (%)",
    "Mean Throughput Degradation (%)",
    "Mean Mixed P99 (ms)",
    "Repetitions",
    "CI Pass",
]

publication[
    "Mean P95 Degradation (%)"
] = publication[
    "Mean P95 Degradation (%)"
].round(2)

publication[
    "Mean Throughput Degradation (%)"
] = publication[
    "Mean Throughput Degradation (%)"
].round(2)

publication[
    "Mean Mixed P99 (ms)"
] = publication[
    "Mean Mixed P99 (ms)"
].round(3)

publication_csv = (
    OUT_DIR
    / "interference_publication_table.csv"
)

publication.to_csv(
    publication_csv,
    index=False,
)


# ============================================================
# Overall backend summary
# ============================================================

backend_summary = (
    df.groupby(
        "backend",
        as_index=False,
    )
    .agg(
        mean_p95_degradation_pct=(
            "p95_degradation_pct",
            "mean",
        ),

        mean_throughput_degradation_pct=(
            "throughput_degradation_pct",
            "mean",
        ),

        max_p95_degradation_pct=(
            "p95_degradation_pct",
            "max",
        ),

        max_throughput_degradation_pct=(
            "throughput_degradation_pct",
            "max",
        ),

        mean_error_rate=(
            "error_rate",
            "mean",
        ),
    )
)


w = backend_summary[
    backend_summary["backend"]
    == "wasmtime"
].iloc[0]

d = backend_summary[
    backend_summary["backend"]
    == "docker"
].iloc[0]


analysis = {
    "experiment":
        "mixed_tenant_interference",

    "pairs":
        6,

    "backends":
        2,

    "pair_configurations":
        12,

    "stream_observations":
        len(df),

    "frozen_protocol": {
        "physical_units_per_model":
            20,

        "concurrency_per_model":
            32,

        "requests_per_model_per_repetition":
            5000,

        "total_mixed_concurrency":
            64,

        "total_mixed_requests_per_repetition":
            10000,

        "minimum_repetitions":
            20,

        "maximum_repetitions":
            60,

        "relative_ci_target":
            0.025,
    },

    "wasmtime": {
        "mean_p95_degradation_pct":
            float(
                w[
                    "mean_p95_degradation_pct"
                ]
            ),

        "mean_throughput_degradation_pct":
            float(
                w[
                    "mean_throughput_degradation_pct"
                ]
            ),

        "max_p95_degradation_pct":
            float(
                w[
                    "max_p95_degradation_pct"
                ]
            ),
    },

    "docker": {
        "mean_p95_degradation_pct":
            float(
                d[
                    "mean_p95_degradation_pct"
                ]
            ),

        "mean_throughput_degradation_pct":
            float(
                d[
                    "mean_throughput_degradation_pct"
                ]
            ),

        "max_p95_degradation_pct":
            float(
                d[
                    "max_p95_degradation_pct"
                ]
            ),
    },

    "docker_over_wasmtime_mean_p95_degradation":
        float(
            d[
                "mean_p95_degradation_pct"
            ]
            /
            w[
                "mean_p95_degradation_pct"
            ]
        ),

    "pair_results":
        pair_df.to_dict(
            orient="records"
        ),
}


analysis_json = (
    OUT_DIR
    / "interference_final_analysis.json"
)

analysis_json.write_text(
    json.dumps(
        analysis,
        indent=2,
    )
)


# ============================================================
# Console
# ============================================================

print("=" * 105)
print("COMET-Wasm MIXED-TENANT INTERFERENCE SUMMARY")
print("=" * 105)

print(
    f"{'Pair':18s} "
    f"{'Backend':10s} "
    f"{'P95 Deg.':>11s} "
    f"{'Thr. Deg.':>11s} "
    f"{'n':>5s} "
    f"{'CI':>12s}"
)

print("-" * 105)

for _, r in pair_df.iterrows():

    status = (
        "PASS"
        if r["ci_pass"]
        else "MAX-REPS"
    )

    print(
        f"{r['pair_label']:18s} "
        f"{r['backend']:10s} "
        f"{r['mean_p95_degradation_pct']:10.2f}% "
        f"{r['mean_throughput_degradation_pct']:10.2f}% "
        f"{int(r['repetitions']):5d} "
        f"{status:>12s}"
    )


print()
print(
    "Wasmtime mean P95 degradation:",
    f"{analysis['wasmtime']['mean_p95_degradation_pct']:.2f}%"
)

print(
    "Docker mean P95 degradation:",
    f"{analysis['docker']['mean_p95_degradation_pct']:.2f}%"
)

print(
    "Wasmtime mean throughput degradation:",
    f"{analysis['wasmtime']['mean_throughput_degradation_pct']:.2f}%"
)

print(
    "Docker mean throughput degradation:",
    f"{analysis['docker']['mean_throughput_degradation_pct']:.2f}%"
)

print(
    "Docker/Wasmtime P95-degradation ratio:",
    f"{analysis['docker_over_wasmtime_mean_p95_degradation']:.2f}x"
)


# ============================================================
# Figure 1 — pair P95 degradation
# ============================================================

pivot_p95 = pair_df.pivot(
    index="pair_label",
    columns="backend",
    values="mean_p95_degradation_pct",
).reindex(
    [
        PAIR_LABELS[p]
        for p in PAIRS
    ]
)

x = np.arange(
    len(pivot_p95)
)

width = 0.36

fig, ax = plt.subplots(
    figsize=(10.5, 6)
)

ax.bar(
    x - width / 2,
    pivot_p95["wasmtime"],
    width,
    label="Wasmtime",
)

ax.bar(
    x + width / 2,
    pivot_p95["docker"],
    width,
    label="Docker",
)

ax.set_ylabel(
    "Mean P95 Latency Degradation (%)"
)

ax.set_xlabel(
    "Mixed Workload Pair"
)

ax.set_title(
    "Mixed-Tenant Tail-Latency Interference"
)

ax.set_xticks(x)

ax.set_xticklabels(
    pivot_p95.index,
    rotation=20,
    ha="right",
)

ax.legend()

ax.grid(
    axis="y",
    linestyle="--",
    alpha=0.3,
)

fig.tight_layout()

p95_png = (
    FIG_DIR
    / "interference_p95_degradation.png"
)

p95_pdf = (
    FIG_DIR
    / "interference_p95_degradation.pdf"
)

fig.savefig(
    p95_png,
    dpi=300,
    bbox_inches="tight",
)

fig.savefig(
    p95_pdf,
    bbox_inches="tight",
)

plt.close(fig)


# ============================================================
# Figure 2 — throughput degradation
# ============================================================

pivot_thr = pair_df.pivot(
    index="pair_label",
    columns="backend",
    values="mean_throughput_degradation_pct",
).reindex(
    [
        PAIR_LABELS[p]
        for p in PAIRS
    ]
)

fig, ax = plt.subplots(
    figsize=(10.5, 6)
)

ax.bar(
    x - width / 2,
    pivot_thr["wasmtime"],
    width,
    label="Wasmtime",
)

ax.bar(
    x + width / 2,
    pivot_thr["docker"],
    width,
    label="Docker",
)

ax.set_ylabel(
    "Mean Throughput Degradation (%)"
)

ax.set_xlabel(
    "Mixed Workload Pair"
)

ax.set_title(
    "Mixed-Tenant Throughput Interference"
)

ax.set_xticks(x)

ax.set_xticklabels(
    pivot_thr.index,
    rotation=20,
    ha="right",
)

ax.legend()

ax.grid(
    axis="y",
    linestyle="--",
    alpha=0.3,
)

fig.tight_layout()

thr_png = (
    FIG_DIR
    / "interference_throughput_degradation.png"
)

thr_pdf = (
    FIG_DIR
    / "interference_throughput_degradation.pdf"
)

fig.savefig(
    thr_png,
    dpi=300,
    bbox_inches="tight",
)

fig.savefig(
    thr_pdf,
    bbox_inches="tight",
)

plt.close(fig)


print()
print("=" * 80)
print("INTERFERENCE CONSOLIDATION: PASS")
print("=" * 80)

print(
    "Comparison:",
    comparison_csv
)

print(
    "Pair table:",
    pair_csv
)

print(
    "Publication table:",
    publication_csv
)

print(
    "Analysis:",
    analysis_json
)

print(
    "Figures:",
    FIG_DIR
)

