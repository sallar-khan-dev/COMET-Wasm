#!/usr/bin/env python3

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


# ============================================================
# Paths
# ============================================================

ROOT = Path(__file__).resolve().parents[2]

INPUT = (
    ROOT
    / "results"
    / "processed"
    / "execution_time"
    / "execution_time_final_comparison.csv"
)

OUTPUT_DIR = (
    ROOT
    / "figures"
    / "execution_time"
)

TABLE_DIR = (
    ROOT
    / "results"
    / "processed"
    / "execution_time"
)

OUTPUT_DIR.mkdir(
    parents=True,
    exist_ok=True
)

TABLE_DIR.mkdir(
    parents=True,
    exist_ok=True
)


# ============================================================
# Load consolidated execution-time results
# ============================================================

if not INPUT.exists():
    raise FileNotFoundError(
        f"Execution-time comparison file not found: {INPUT}"
    )

df = pd.read_csv(INPUT)

print("=" * 72)
print("EXECUTION-TIME INPUT")
print("=" * 72)
print(df.to_string(index=False))
print()


# ============================================================
# Normalise expected column names
# ============================================================

rename_candidates = {
    "wasmtime_execution_mean_us": "wasmtime_us",
    "docker_execution_mean_us": "docker_us",
    "wasmtime_mean_us": "wasmtime_us",
    "docker_mean_us": "docker_us",
    "wasmtime_execution_us": "wasmtime_us",
    "docker_execution_us": "docker_us",
}

for old, new in rename_candidates.items():
    if old in df.columns and new not in df.columns:
        df = df.rename(columns={old: new})


# If nanoseconds are stored, derive microseconds.

if "wasmtime_us" not in df.columns:

    possible = [
        "wasmtime_execution_mean_ns",
        "wasmtime_mean_ns",
        "wasmtime_ns",
    ]

    source = next(
        (c for c in possible if c in df.columns),
        None,
    )

    if source is not None:
        df["wasmtime_us"] = df[source] / 1000.0


if "docker_us" not in df.columns:

    possible = [
        "docker_execution_mean_ns",
        "docker_mean_ns",
        "docker_ns",
    ]

    source = next(
        (c for c in possible if c in df.columns),
        None,
    )

    if source is not None:
        df["docker_us"] = df[source] / 1000.0


required = [
    "model",
    "wasmtime_us",
    "docker_us",
]

missing = [
    c for c in required
    if c not in df.columns
]

if missing:
    raise RuntimeError(
        "Required columns are missing from "
        f"{INPUT.name}: {missing}\n"
        f"Available columns: {list(df.columns)}"
    )


# ============================================================
# Publication-friendly labels
# ============================================================

labels = {
    "logistic_regression": "Logistic Regression",
    "naive_bayes": "Naive Bayes",
    "decision_tree": "Decision Tree",
    "kmeans": "K-Means",
    "random_forest": "Random Forest",
    "svm": "SVM",
    "mlp": "MLP",
}

df["label"] = (
    df["model"]
    .map(labels)
    .fillna(df["model"])
)


# ============================================================
# Sort LOWEST -> HIGHEST
#
# Ordering reference = Wasmtime isolated execution time
# ============================================================

df = (
    df.sort_values(
        by="wasmtime_us",
        ascending=True,
    )
    .reset_index(drop=True)
)


# ============================================================
# Comparison metrics
# ============================================================

df["wasm_docker_ratio"] = (
    df["wasmtime_us"]
    / df["docker_us"]
)

df["wasmtime_overhead_percent"] = (
    (
        df["wasmtime_us"]
        - df["docker_us"]
    )
    / df["docker_us"]
    * 100.0
)


# ============================================================
# Publication table
# ============================================================

publication_table = df[
    [
        "label",
        "wasmtime_us",
        "docker_us",
        "wasm_docker_ratio",
        "wasmtime_overhead_percent",
    ]
].copy()

publication_table.columns = [
    "Model",
    "Wasmtime Execution Time (us)",
    "Docker Execution Time (us)",
    "Wasm/Docker Ratio",
    "Wasmtime Overhead (%)",
]

publication_table[
    "Wasmtime Execution Time (us)"
] = publication_table[
    "Wasmtime Execution Time (us)"
].round(4)

publication_table[
    "Docker Execution Time (us)"
] = publication_table[
    "Docker Execution Time (us)"
].round(4)

publication_table[
    "Wasm/Docker Ratio"
] = publication_table[
    "Wasm/Docker Ratio"
].round(2)

publication_table[
    "Wasmtime Overhead (%)"
] = publication_table[
    "Wasmtime Overhead (%)"
].round(2)


TABLE_CSV = (
    TABLE_DIR
    / "execution_time_publication_table.csv"
)

publication_table.to_csv(
    TABLE_CSV,
    index=False,
)


# ============================================================
# Print table
# ============================================================

print("=" * 88)
print(
    "ISOLATED MODEL EXECUTION TIME "
    "(LOWEST -> HIGHEST)"
)
print("=" * 88)

print(
    publication_table.to_string(
        index=False
    )
)

print()


# ============================================================
# Plot
# ============================================================

x = np.arange(len(df))

width = 0.36

fig, ax = plt.subplots(
    figsize=(11, 6.5)
)


bars_wasm = ax.bar(
    x - width / 2,
    df["wasmtime_us"],
    width,
    label="Wasmtime",
)

bars_docker = ax.bar(
    x + width / 2,
    df["docker_us"],
    width,
    label="Docker",
)


# ============================================================
# Axis formatting
# ============================================================

ax.set_xlabel(
    "Machine Learning Workload",
    fontsize=12,
)

ax.set_ylabel(
    "Mean Isolated Execution Time (µs)",
    fontsize=12,
)

ax.set_title(
    "Isolated Model Execution Time: "
    "Wasmtime vs Docker",
    fontsize=13,
)

ax.set_xticks(x)

ax.set_xticklabels(
    df["label"],
    rotation=25,
    ha="right",
)

ax.legend()

ax.grid(
    axis="y",
    linestyle="--",
    alpha=0.35,
)


# ============================================================
# Value labels
# ============================================================

def add_labels(bars):

    for bar in bars:

        height = bar.get_height()

        if height < 1.0:
            label = f"{height:.3f}"

        elif height < 10.0:
            label = f"{height:.2f}"

        else:
            label = f"{height:.1f}"

        ax.annotate(
            label,
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


add_labels(bars_wasm)
add_labels(bars_docker)


max_value = max(
    df["wasmtime_us"].max(),
    df["docker_us"].max(),
)

ax.set_ylim(
    0,
    max_value * 1.15,
)


# ============================================================
# Figure note
# ============================================================

fig.text(
    0.5,
    0.01,
    (
        "Execution time represents isolated backend model "
        "execution and excludes HTTP/network latency. "
        "Workloads are ordered by increasing Wasmtime "
        "execution time."
    ),
    ha="center",
    fontsize=8,
)

plt.tight_layout(
    rect=[
        0,
        0.04,
        1,
        1,
    ]
)


# ============================================================
# Save publication figures
# ============================================================

PNG = (
    OUTPUT_DIR
    / "execution_time_wasmtime_vs_docker.png"
)

PDF = (
    OUTPUT_DIR
    / "execution_time_wasmtime_vs_docker.pdf"
)

SVG = (
    OUTPUT_DIR
    / "execution_time_wasmtime_vs_docker.svg"
)


fig.savefig(
    PNG,
    dpi=300,
    bbox_inches="tight",
)

fig.savefig(
    PDF,
    bbox_inches="tight",
)

fig.savefig(
    SVG,
    bbox_inches="tight",
)

plt.close(fig)


# ============================================================
# Final status
# ============================================================

print("=" * 72)
print("EXECUTION-TIME FIGURE GENERATION: COMPLETE")
print("=" * 72)

print(f"Input:  {INPUT}")
print(f"Table:  {TABLE_CSV}")
print(f"PNG:    {PNG}")
print(f"PDF:    {PDF}")
print(f"SVG:    {SVG}")

print()
print("Model order (LOWEST -> HIGHEST):")

for i, row in df.iterrows():

    print(
        f"{i + 1}. "
        f"{row['label']:<22s} "
        f"Wasmtime={row['wasmtime_us']:.4f} us | "
        f"Docker={row['docker_us']:.4f} us"
    )

