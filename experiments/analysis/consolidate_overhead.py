#!/usr/bin/env python3

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


# ============================================================
# Paths
# ============================================================

ROOT = Path(__file__).resolve().parents[2]

INPUT_DIR = (
    ROOT
    / "results"
    / "processed"
    / "overhead"
)

OUTPUT_DIR = INPUT_DIR

FIGURE_DIR = (
    ROOT
    / "figures"
    / "overhead"
)

FIGURE_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


# ============================================================
# Models
# ============================================================

MODELS = [
    "logistic_regression",
    "naive_bayes",
    "decision_tree",
    "kmeans",
    "random_forest",
    "svm",
    "mlp",
]

LABELS = {
    "logistic_regression": "Logistic Regression",
    "naive_bayes": "Naive Bayes",
    "decision_tree": "Decision Tree",
    "kmeans": "K-Means",
    "random_forest": "Random Forest",
    "svm": "SVM",
    "mlp": "MLP",
}


# ============================================================
# Load summaries
# ============================================================

rows = []

total_requests = 0


for model in MODELS:

    data = {}

    for backend in [
        "wasmtime",
        "docker",
    ]:

        path = (
            INPUT_DIR
            / (
                f"{backend}_{model}_"
                "overhead_full_summary.json"
            )
        )

        if not path.exists():

            raise FileNotFoundError(
                f"Missing summary: {path}"
            )

        data[backend] = json.loads(
            path.read_text()
        )

        total_requests += int(
            data[backend][
                "total_measured_requests"
            ]
        )


    w = data["wasmtime"]
    d = data["docker"]


    w_e2e = float(
        w["mean_e2e_ns"]
    )

    d_e2e = float(
        d["mean_e2e_ns"]
    )

    w_inf = float(
        w["mean_inference_ns"]
    )

    d_inf = float(
        d["mean_inference_ns"]
    )

    w_exec = float(
        w["mean_execution_ns"]
    )

    d_exec = float(
        d["mean_execution_ns"]
    )

    w_non = float(
        w["mean_non_execution_e2e_ns"]
    )

    d_non = float(
        d["mean_non_execution_e2e_ns"]
    )


    rows.append({

        "model":
            model,

        "label":
            LABELS[model],


        # --------------------------------------------
        # E2E latency
        # --------------------------------------------

        "wasmtime_e2e_us":
            w_e2e / 1000.0,

        "docker_e2e_us":
            d_e2e / 1000.0,

        "docker_over_wasmtime_e2e":
            d_e2e / w_e2e,

        "wasmtime_e2e_reduction_pct":
            (
                (d_e2e - w_e2e)
                / d_e2e
                * 100.0
            ),


        # --------------------------------------------
        # Server-side inference
        # --------------------------------------------

        "wasmtime_inference_us":
            w_inf / 1000.0,

        "docker_inference_us":
            d_inf / 1000.0,


        # --------------------------------------------
        # Isolated execution
        # --------------------------------------------

        "wasmtime_execution_us":
            w_exec / 1000.0,

        "docker_execution_us":
            d_exec / 1000.0,

        "wasmtime_over_docker_execution":
            w_exec / d_exec,


        # --------------------------------------------
        # Non-execution path
        # --------------------------------------------

        "wasmtime_non_execution_e2e_us":
            w_non / 1000.0,

        "docker_non_execution_e2e_us":
            d_non / 1000.0,


        # --------------------------------------------
        # Fractions
        # --------------------------------------------

        "wasmtime_execution_share_pct":
            float(
                w["execution_fraction_of_e2e"]
            ) * 100.0,

        "docker_execution_share_pct":
            float(
                d["execution_fraction_of_e2e"]
            ) * 100.0,


        # --------------------------------------------
        # Throughput
        # --------------------------------------------

        "wasmtime_throughput_rps":
            float(
                w["mean_throughput_rps"]
            ),

        "docker_throughput_rps":
            float(
                d["mean_throughput_rps"]
            ),


        # --------------------------------------------
        # Statistical metadata
        # --------------------------------------------

        "wasmtime_repetitions":
            int(
                w["repetitions"]
            ),

        "docker_repetitions":
            int(
                d["repetitions"]
            ),

        "wasmtime_e2e_ci_pct":
            float(
                w["e2e_relative_95ci"]
            ) * 100.0,

        "docker_e2e_ci_pct":
            float(
                d["e2e_relative_95ci"]
            ) * 100.0,

        "wasmtime_execution_ci_pct":
            float(
                w["execution_relative_95ci"]
            ) * 100.0,

        "docker_execution_ci_pct":
            float(
                d["execution_relative_95ci"]
            ) * 100.0,

        "wasmtime_ci_pass":
            bool(
                w["ci_target_pass"]
            ),

        "docker_ci_pass":
            bool(
                d["ci_target_pass"]
            ),
    })


df = pd.DataFrame(
    rows
)


# ============================================================
# Sort by Wasmtime E2E latency
# ============================================================

df = (
    df.sort_values(
        by="wasmtime_e2e_us",
        ascending=True,
    )
    .reset_index(drop=True)
)


# ============================================================
# Save full comparison CSV
# ============================================================

COMPARISON_CSV = (
    OUTPUT_DIR
    / "overhead_final_comparison.csv"
)

df.to_csv(
    COMPARISON_CSV,
    index=False,
)


# ============================================================
# Publication table
# ============================================================

publication = df[
    [
        "label",
        "wasmtime_e2e_us",
        "docker_e2e_us",
        "wasmtime_e2e_reduction_pct",
        "wasmtime_execution_us",
        "docker_execution_us",
        "wasmtime_execution_share_pct",
        "docker_execution_share_pct",
    ]
].copy()


publication.columns = [
    "Model",
    "Wasmtime E2E (us)",
    "Docker E2E (us)",
    "Wasmtime E2E Reduction (%)",
    "Wasmtime Execution (us)",
    "Docker Execution (us)",
    "Wasmtime Execution Share (%)",
    "Docker Execution Share (%)",
]


for col in [
    "Wasmtime E2E (us)",
    "Docker E2E (us)",
    "Wasmtime Execution (us)",
    "Docker Execution (us)",
]:

    publication[col] = (
        publication[col]
        .round(3)
    )


for col in [
    "Wasmtime E2E Reduction (%)",
    "Wasmtime Execution Share (%)",
    "Docker Execution Share (%)",
]:

    publication[col] = (
        publication[col]
        .round(2)
    )


PUBLICATION_CSV = (
    OUTPUT_DIR
    / "overhead_publication_table.csv"
)

publication.to_csv(
    PUBLICATION_CSV,
    index=False,
)


# ============================================================
# Analysis JSON
# ============================================================

analysis = {

    "experiment":
        "synchronized_overhead_decomposition",

    "models":
        len(MODELS),

    "backends": [
        "wasmtime",
        "docker",
    ],

    "backend_model_configurations":
        len(MODELS) * 2,

    "total_measured_requests":
        total_requests,

    "concurrency":
        1,

    "physical_units":
        1,

    "ci_target_percent":
        2.5,

    "all_ci_pass":
        bool(
            df[
                [
                    "wasmtime_ci_pass",
                    "docker_ci_pass",
                ]
            ]
            .all()
            .all()
        ),

    "wasmtime_lower_e2e_models":
        int(
            (
                df["wasmtime_e2e_us"]
                <
                df["docker_e2e_us"]
            )
            .sum()
        ),

    "docker_lower_execution_models":
        int(
            (
                df["docker_execution_us"]
                <
                df["wasmtime_execution_us"]
            )
            .sum()
        ),

    "comparisons":
        df.to_dict(
            orient="records"
        ),
}


ANALYSIS_JSON = (
    OUTPUT_DIR
    / "overhead_final_analysis.json"
)

ANALYSIS_JSON.write_text(
    json.dumps(
        analysis,
        indent=2,
    )
)


# ============================================================
# Console table
# ============================================================

print("=" * 118)

print(
    "COMET-Wasm FINAL SYNCHRONIZED "
    "OVERHEAD COMPARISON"
)

print("=" * 118)

print(
    f"{'Model':22s} "
    f"{'Wasm E2E':>11s} "
    f"{'Docker E2E':>11s} "
    f"{'E2E Gain':>10s} "
    f"{'Wasm Exec':>11s} "
    f"{'Docker Exec':>11s} "
    f"{'Wasm Share':>11s} "
    f"{'Docker Share':>12s}"
)

print("-" * 118)


for _, r in df.iterrows():

    print(
        f"{r['label']:22s} "
        f"{r['wasmtime_e2e_us']:10.3f}u "
        f"{r['docker_e2e_us']:10.3f}u "
        f"{r['wasmtime_e2e_reduction_pct']:9.2f}% "
        f"{r['wasmtime_execution_us']:10.3f}u "
        f"{r['docker_execution_us']:10.3f}u "
        f"{r['wasmtime_execution_share_pct']:10.2f}% "
        f"{r['docker_execution_share_pct']:11.2f}%"
    )


print()

print(
    "Wasmtime lower E2E latency: "
    f"{analysis['wasmtime_lower_e2e_models']}"
    f"/{len(MODELS)} models"
)

print(
    "Docker lower isolated execution: "
    f"{analysis['docker_lower_execution_models']}"
    f"/{len(MODELS)} models"
)

print(
    "Total measured synchronized requests:",
    f"{total_requests:,}"
)

print(
    "All CI targets passed:",
    analysis["all_ci_pass"]
)


# ============================================================
# Figure 1:
# E2E latency
# ============================================================

x = np.arange(
    len(df)
)

width = 0.36


fig, ax = plt.subplots(
    figsize=(11, 6.2)
)


wasm_bars = ax.bar(
    x - width / 2,
    df["wasmtime_e2e_us"],
    width,
    label="Wasmtime",
)

docker_bars = ax.bar(
    x + width / 2,
    df["docker_e2e_us"],
    width,
    label="Docker",
)


ax.set_ylabel(
    "Mean End-to-End Latency (µs)"
)

ax.set_xlabel(
    "Machine Learning Workload"
)

ax.set_title(
    "Synchronized End-to-End Inference Latency"
)

ax.set_xticks(
    x
)

ax.set_xticklabels(
    df["label"],
    rotation=25,
    ha="right",
)

ax.legend()

ax.grid(
    axis="y",
    linestyle="--",
    alpha=0.3,
)


def annotate(
    axis,
    bars,
    decimals=1,
):

    for bar in bars:

        height = (
            bar.get_height()
        )

        axis.annotate(
            f"{height:.{decimals}f}",
            xy=(
                bar.get_x()
                + bar.get_width() / 2,
                height,
            ),
            xytext=(0, 4),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=8,
        )


annotate(
    ax,
    wasm_bars,
    1,
)

annotate(
    ax,
    docker_bars,
    1,
)


ax.set_ylim(
    0,
    max(
        df["wasmtime_e2e_us"].max(),
        df["docker_e2e_us"].max(),
    )
    * 1.18,
)


fig.tight_layout()


E2E_PNG = (
    FIGURE_DIR
    / "overhead_e2e_wasmtime_vs_docker.png"
)

E2E_PDF = (
    FIGURE_DIR
    / "overhead_e2e_wasmtime_vs_docker.pdf"
)


fig.savefig(
    E2E_PNG,
    dpi=300,
    bbox_inches="tight",
)

fig.savefig(
    E2E_PDF,
    bbox_inches="tight",
)

plt.close(fig)


# ============================================================
# Figure 2:
# execution share of E2E
# ============================================================

fig, ax = plt.subplots(
    figsize=(11, 6.2)
)


wasm_bars = ax.bar(
    x - width / 2,
    df[
        "wasmtime_execution_share_pct"
    ],
    width,
    label="Wasmtime",
)

docker_bars = ax.bar(
    x + width / 2,
    df[
        "docker_execution_share_pct"
    ],
    width,
    label="Docker",
)


ax.set_ylabel(
    "Model Execution Share of E2E Latency (%)"
)

ax.set_xlabel(
    "Machine Learning Workload"
)

ax.set_title(
    "Fraction of End-to-End Latency Spent "
    "in Isolated Model Execution"
)

ax.set_xticks(
    x
)

ax.set_xticklabels(
    df["label"],
    rotation=25,
    ha="right",
)

ax.legend()

ax.grid(
    axis="y",
    linestyle="--",
    alpha=0.3,
)


annotate(
    ax,
    wasm_bars,
    2,
)

annotate(
    ax,
    docker_bars,
    2,
)


ax.set_ylim(
    0,
    max(
        df[
            "wasmtime_execution_share_pct"
        ].max(),
        df[
            "docker_execution_share_pct"
        ].max(),
    )
    * 1.20,
)


fig.tight_layout()


SHARE_PNG = (
    FIGURE_DIR
    / "overhead_execution_share.png"
)

SHARE_PDF = (
    FIGURE_DIR
    / "overhead_execution_share.pdf"
)


fig.savefig(
    SHARE_PNG,
    dpi=300,
    bbox_inches="tight",
)

fig.savefig(
    SHARE_PDF,
    bbox_inches="tight",
)

plt.close(fig)


# ============================================================
# Figure 3:
# non-execution E2E cost
# ============================================================

fig, ax = plt.subplots(
    figsize=(11, 6.2)
)


wasm_bars = ax.bar(
    x - width / 2,
    df[
        "wasmtime_non_execution_e2e_us"
    ],
    width,
    label="Wasmtime",
)

docker_bars = ax.bar(
    x + width / 2,
    df[
        "docker_non_execution_e2e_us"
    ],
    width,
    label="Docker",
)


ax.set_ylabel(
    "Mean Non-Execution E2E Time (µs)"
)

ax.set_xlabel(
    "Machine Learning Workload"
)

ax.set_title(
    "End-to-End Latency Outside "
    "Isolated Model Execution"
)

ax.set_xticks(
    x
)

ax.set_xticklabels(
    df["label"],
    rotation=25,
    ha="right",
)

ax.legend()

ax.grid(
    axis="y",
    linestyle="--",
    alpha=0.3,
)


annotate(
    ax,
    wasm_bars,
    1,
)

annotate(
    ax,
    docker_bars,
    1,
)


ax.set_ylim(
    0,
    max(
        df[
            "wasmtime_non_execution_e2e_us"
        ].max(),
        df[
            "docker_non_execution_e2e_us"
        ].max(),
    )
    * 1.18,
)


fig.tight_layout()


NONEXEC_PNG = (
    FIGURE_DIR
    / "overhead_non_execution_e2e.png"
)

NONEXEC_PDF = (
    FIGURE_DIR
    / "overhead_non_execution_e2e.pdf"
)


fig.savefig(
    NONEXEC_PNG,
    dpi=300,
    bbox_inches="tight",
)

fig.savefig(
    NONEXEC_PDF,
    bbox_inches="tight",
)

plt.close(fig)


# ============================================================
# Final output
# ============================================================

print()
print("=" * 78)

print(
    "OVERHEAD CONSOLIDATION / "
    "FIGURE GENERATION: PASS"
)

print("=" * 78)

print(
    "Comparison CSV:",
    COMPARISON_CSV,
)

print(
    "Publication CSV:",
    PUBLICATION_CSV,
)

print(
    "Analysis JSON:",
    ANALYSIS_JSON,
)

print(
    "E2E figure:",
    E2E_PNG,
)

print(
    "Execution-share figure:",
    SHARE_PNG,
)

print(
    "Non-execution figure:",
    NONEXEC_PNG,
)

