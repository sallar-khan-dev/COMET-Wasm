#!/usr/bin/env python3

import json
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]

IN_DIR = ROOT / "results/processed/cold_start"
FIG_DIR = ROOT / "figures/cold_start"

FIG_DIR.mkdir(parents=True, exist_ok=True)

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


rows = []

for model in MODELS:

    data = {}

    for backend in ["wasmtime", "docker"]:

        p = (
            IN_DIR
            / f"{backend}_{model}_cold_start_full_summary.json"
        )

        if not p.exists():
            raise FileNotFoundError(p)

        data[backend] = json.loads(
            p.read_text()
        )

    w = data["wasmtime"]
    d = data["docker"]

    ws = float(w["startup_ms"]["mean"])
    ds = float(d["startup_ms"]["mean"])

    wc = float(
        w["cold_to_first_result_ms"]["mean"]
    )
    dc = float(
        d["cold_to_first_result_ms"]["mean"]
    )

    wf = float(
        w["first_inference_ms"]["mean"]
    )
    df = float(
        d["first_inference_ms"]["mean"]
    )

    ww = float(
        w["warm_inference_ms"]["mean"]
    )
    dw = float(
        d["warm_inference_ms"]["mean"]
    )

    rows.append({
        "model": model,
        "label": LABELS[model],

        "wasmtime_startup_ms": ws,
        "docker_startup_ms": ds,

        "startup_ratio_docker_over_wasm":
            ds / ws,

        "wasmtime_startup_reduction_pct":
            (ds - ws) / ds * 100.0,

        "wasmtime_cold_to_first_result_ms": wc,
        "docker_cold_to_first_result_ms": dc,

        "cold_result_ratio_docker_over_wasm":
            dc / wc,

        "wasmtime_first_inference_ms": wf,
        "docker_first_inference_ms": df,

        "wasmtime_warm_inference_ms": ww,
        "docker_warm_inference_ms": dw,

        "wasmtime_repetitions":
            int(w["repetitions"]),

        "docker_repetitions":
            int(d["repetitions"]),

        "wasmtime_startup_ci_pct":
            float(
                w["startup_ms"]["relative"]
            ) * 100.0,

        "docker_startup_ci_pct":
            float(
                d["startup_ms"]["relative"]
            ) * 100.0,

        "wasmtime_cold_ci_pct":
            float(
                w["cold_to_first_result_ms"]["relative"]
            ) * 100.0,

        "docker_cold_ci_pct":
            float(
                d["cold_to_first_result_ms"]["relative"]
            ) * 100.0,

        "wasmtime_primary_ci_pass":
            bool(w["primary_ci_pass"]),

        "docker_primary_ci_pass":
            bool(d["primary_ci_pass"]),
    })


df = pd.DataFrame(rows)

df = (
    df.sort_values(
        "wasmtime_startup_ms"
    )
    .reset_index(drop=True)
)


# ============================================================
# Save full comparison CSV
# ============================================================

comparison_csv = (
    IN_DIR
    / "cold_start_final_comparison.csv"
)

df.to_csv(
    comparison_csv,
    index=False,
)


# ============================================================
# Publication table
# ============================================================

pub = df[
    [
        "label",
        "wasmtime_startup_ms",
        "docker_startup_ms",
        "startup_ratio_docker_over_wasm",
        "wasmtime_cold_to_first_result_ms",
        "docker_cold_to_first_result_ms",
    ]
].copy()

pub.columns = [
    "Model",
    "Wasmtime Startup (ms)",
    "Docker Startup (ms)",
    "Docker/Wasmtime Startup",
    "Wasmtime Cold-to-Result (ms)",
    "Docker Cold-to-Result (ms)",
]

pub["Wasmtime Startup (ms)"] = (
    pub["Wasmtime Startup (ms)"].round(3)
)

pub["Docker Startup (ms)"] = (
    pub["Docker Startup (ms)"].round(3)
)

pub["Docker/Wasmtime Startup"] = (
    pub["Docker/Wasmtime Startup"].round(2)
)

pub["Wasmtime Cold-to-Result (ms)"] = (
    pub["Wasmtime Cold-to-Result (ms)"].round(3)
)

pub["Docker Cold-to-Result (ms)"] = (
    pub["Docker Cold-to-Result (ms)"].round(3)
)

publication_csv = (
    IN_DIR
    / "cold_start_publication_table.csv"
)

pub.to_csv(
    publication_csv,
    index=False,
)


# ============================================================
# Analysis JSON
# ============================================================

analysis = {
    "experiment": "unified_cold_start",

    "models": len(df),

    "configurations": len(df) * 2,

    "primary_ci_target_percent": 2.5,

    "all_primary_ci_pass": bool(
        df[
            [
                "wasmtime_primary_ci_pass",
                "docker_primary_ci_pass",
            ]
        ].all().all()
    ),

    "wasmtime_faster_startup_models": int(
        (
            df["wasmtime_startup_ms"]
            <
            df["docker_startup_ms"]
        ).sum()
    ),

    "wasmtime_faster_cold_result_models": int(
        (
            df["wasmtime_cold_to_first_result_ms"]
            <
            df["docker_cold_to_first_result_ms"]
        ).sum()
    ),

    "mean_startup_ratio_docker_over_wasm":
        float(
            df[
                "startup_ratio_docker_over_wasm"
            ].mean()
        ),

    "min_startup_ratio_docker_over_wasm":
        float(
            df[
                "startup_ratio_docker_over_wasm"
            ].min()
        ),

    "max_startup_ratio_docker_over_wasm":
        float(
            df[
                "startup_ratio_docker_over_wasm"
            ].max()
        ),

    "rows":
        df.to_dict(
            orient="records"
        ),
}

analysis_json = (
    IN_DIR
    / "cold_start_final_analysis.json"
)

analysis_json.write_text(
    json.dumps(
        analysis,
        indent=2,
    )
)


# ============================================================
# Console output
# ============================================================

print("=" * 110)
print("COMET-Wasm FINAL COLD-START COMPARISON")
print("=" * 110)

print(
    f"{'Model':22s} "
    f"{'Wasm Start':>11s} "
    f"{'Docker Start':>12s} "
    f"{'Ratio':>8s} "
    f"{'Wasm Cold':>11s} "
    f"{'Docker Cold':>12s}"
)

print("-" * 110)

for _, r in df.iterrows():

    print(
        f"{r['label']:22s} "
        f"{r['wasmtime_startup_ms']:10.3f} "
        f"{r['docker_startup_ms']:11.3f} "
        f"{r['startup_ratio_docker_over_wasm']:7.2f}x "
        f"{r['wasmtime_cold_to_first_result_ms']:10.3f} "
        f"{r['docker_cold_to_first_result_ms']:11.3f}"
    )

print()

print(
    "Wasmtime faster startup:",
    f"{analysis['wasmtime_faster_startup_models']}/7"
)

print(
    "Wasmtime faster cold-to-first-result:",
    f"{analysis['wasmtime_faster_cold_result_models']}/7"
)

print(
    "Mean Docker/Wasmtime startup ratio:",
    f"{analysis['mean_startup_ratio_docker_over_wasm']:.2f}x"
)

print(
    "Ratio range:",
    f"{analysis['min_startup_ratio_docker_over_wasm']:.2f}x"
    "–"
    f"{analysis['max_startup_ratio_docker_over_wasm']:.2f}x"
)

print(
    "All primary CI targets passed:",
    analysis["all_primary_ci_pass"]
)


# ============================================================
# Figure helper
# ============================================================

x = np.arange(len(df))
width = 0.36


def save_grouped(
    wasm_col,
    docker_col,
    ylabel,
    title,
    stem,
):

    fig, ax = plt.subplots(
        figsize=(11, 6.2)
    )

    wb = ax.bar(
        x - width / 2,
        df[wasm_col],
        width,
        label="Wasmtime",
    )

    db = ax.bar(
        x + width / 2,
        df[docker_col],
        width,
        label="Docker",
    )

    ax.set_ylabel(ylabel)
    ax.set_xlabel(
        "Machine Learning Workload"
    )
    ax.set_title(title)

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
        alpha=0.3,
    )

    for bars in [wb, db]:

        for bar in bars:

            h = bar.get_height()

            ax.annotate(
                f"{h:.1f}",
                xy=(
                    bar.get_x()
                    + bar.get_width() / 2,
                    h,
                ),
                xytext=(0, 4),
                textcoords="offset points",
                ha="center",
                fontsize=8,
            )

    max_y = max(
        df[wasm_col].max(),
        df[docker_col].max(),
    )

    ax.set_ylim(
        0,
        max_y * 1.16,
    )

    fig.tight_layout()

    png = FIG_DIR / f"{stem}.png"
    pdf = FIG_DIR / f"{stem}.pdf"

    fig.savefig(
        png,
        dpi=300,
        bbox_inches="tight",
    )

    fig.savefig(
        pdf,
        bbox_inches="tight",
    )

    plt.close(fig)

    return png, pdf


startup_png, startup_pdf = save_grouped(
    "wasmtime_startup_ms",
    "docker_startup_ms",
    "Startup to Readiness (ms)",
    "Cold-Start Readiness: Wasmtime vs Docker",
    "cold_start_startup_wasmtime_vs_docker",
)


cold_png, cold_pdf = save_grouped(
    "wasmtime_cold_to_first_result_ms",
    "docker_cold_to_first_result_ms",
    "Launch to First Inference Result (ms)",
    "Cold Start to First Successful Inference",
    "cold_start_to_first_result",
)


# ============================================================
# Ratio figure
# ============================================================

fig, ax = plt.subplots(
    figsize=(10.5, 6)
)

bars = ax.bar(
    df["label"],
    df[
        "startup_ratio_docker_over_wasm"
    ],
)

ax.set_ylabel(
    "Docker / Wasmtime Startup Time (×)"
)

ax.set_xlabel(
    "Machine Learning Workload"
)

ax.set_title(
    "Docker Cold-Start Penalty Relative to Wasmtime"
)

ax.tick_params(
    axis="x",
    rotation=25,
)

ax.grid(
    axis="y",
    linestyle="--",
    alpha=0.3,
)

for bar in bars:

    h = bar.get_height()

    ax.annotate(
        f"{h:.1f}×",
        xy=(
            bar.get_x()
            + bar.get_width() / 2,
            h,
        ),
        xytext=(0, 4),
        textcoords="offset points",
        ha="center",
        fontsize=8,
    )

ax.set_ylim(
    0,
    df[
        "startup_ratio_docker_over_wasm"
    ].max()
    * 1.17,
)

fig.tight_layout()

ratio_png = (
    FIG_DIR
    / "cold_start_docker_wasmtime_ratio.png"
)

ratio_pdf = (
    FIG_DIR
    / "cold_start_docker_wasmtime_ratio.pdf"
)

fig.savefig(
    ratio_png,
    dpi=300,
    bbox_inches="tight",
)

fig.savefig(
    ratio_pdf,
    bbox_inches="tight",
)

plt.close(fig)


print()
print("=" * 80)
print("COLD-START CONSOLIDATION: PASS")
print("=" * 80)

print("Comparison CSV:", comparison_csv)
print("Publication CSV:", publication_csv)
print("Analysis JSON:", analysis_json)

print("Startup figure:", startup_png)
print("Cold-result figure:", cold_png)
print("Ratio figure:", ratio_png)

