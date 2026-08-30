#!/usr/bin/env python3

import csv
import json
import math
import statistics
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import t as student_t


# ============================================================
# Configuration
# ============================================================

ROOT = Path(__file__).resolve().parents[2]

RAW_DIR = ROOT / "results" / "raw" / "density"
OUT_DIR = ROOT / "results" / "processed" / "density"
FIG_DIR = ROOT / "figures" / "density"

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

BACKENDS = [
    "wasmtime",
    "docker",
]

COMMON_LEVELS = [
    20,
    100,
    200,
]

CI_TARGET = 0.025


# ============================================================
# Helpers
# ============================================================

def detect_column(columns, candidates):

    lower = {
        c.lower(): c
        for c in columns
    }

    for candidate in candidates:

        if candidate.lower() in lower:
            return lower[candidate.lower()]

    # Fuzzy fallback.
    for c in columns:

        lc = c.lower()

        for candidate in candidates:

            if candidate.lower() in lc:
                return c

    return None


def ci95(values):

    values = [
        float(x)
        for x in values
    ]

    n = len(values)

    if n == 0:
        raise RuntimeError(
            "Cannot calculate CI on empty sample."
        )

    mean = statistics.mean(values)

    if n == 1:

        return {
            "n": 1,
            "mean": mean,
            "sd": 0.0,
            "halfwidth": math.inf,
            "relative": math.inf,
        }

    sd = statistics.stdev(values)

    critical = student_t.ppf(
        0.975,
        df=n - 1,
    )

    halfwidth = (
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
        "n": n,
        "mean": mean,
        "sd": sd,
        "halfwidth": halfwidth,
        "relative": relative,
    }


def read_density_csv(path):

    if not path.exists():
        raise FileNotFoundError(
            f"Missing raw density file: {path}"
        )

    with path.open(
        newline=""
    ) as f:

        rows = list(
            csv.DictReader(f)
        )

    if not rows:
        raise RuntimeError(
            f"No rows in {path}"
        )

    columns = list(
        rows[0].keys()
    )

    level_col = detect_column(
        columns,
        [
            "physical_tenants",
            "physical_units",
            "tenants",
            "tenant_count",
            "density_level",
            "level",
        ],
    )

    pss_col = detect_column(
        columns,
        [
            "pss_mib",
            "total_pss_mib",
            "mean_pss_mib",
            "pss",
        ],
    )

    if level_col is None:
        raise RuntimeError(
            f"Could not identify tenant-level column "
            f"in {path}. Columns={columns}"
        )

    if pss_col is None:
        raise RuntimeError(
            f"Could not identify PSS column "
            f"in {path}. Columns={columns}"
        )

    print(
        f"{path.name}: "
        f"level_col={level_col}, "
        f"pss_col={pss_col}"
    )

    grouped = {}

    for level in COMMON_LEVELS:

        values = [
            float(r[pss_col])
            for r in rows
            if int(
                float(
                    r[level_col]
                )
            ) == level
        ]

        if not values:

            raise RuntimeError(
                f"{path.name}: "
                f"missing common level {level}"
            )

        grouped[level] = ci95(
            values
        )

    return grouped


# ============================================================
# Load all 14 raw datasets
# ============================================================

stats = {}

all_ci_pass = True

for model in MODELS:

    stats[model] = {}

    for backend in BACKENDS:

        path = (
            RAW_DIR
            / (
                f"{backend}_{model}_"
                "density_full.csv"
            )
        )

        grouped = read_density_csv(
            path
        )

        stats[model][backend] = (
            grouped
        )

        for level in COMMON_LEVELS:

            s = grouped[level]

            passed = (
                s["n"] >= 20
                and
                s["relative"]
                <= CI_TARGET
            )

            all_ci_pass = (
                all_ci_pass
                and passed
            )

            print(
                f"  {model:22s} "
                f"{backend:8s} "
                f"N={level:3d} | "
                f"n={s['n']:2d} | "
                f"PSS={s['mean']:.3f} MiB | "
                f"CI={s['relative']*100:.3f}% | "
                f"{'PASS' if passed else 'CHECK'}"
            )


# ============================================================
# Build final comparison table
# ============================================================

rows = []

for model in MODELS:

    w = stats[model][
        "wasmtime"
    ]

    d = stats[model][
        "docker"
    ]

    w_values = np.array(
        [
            w[level]["mean"]
            for level in COMMON_LEVELS
        ],
        dtype=float,
    )

    d_values = np.array(
        [
            d[level]["mean"]
            for level in COMMON_LEVELS
        ],
        dtype=float,
    )

    levels = np.array(
        COMMON_LEVELS,
        dtype=float,
    )

    # Linear memory model:
    # M(N) = intercept + slope * N
    w_slope, w_intercept = (
        np.polyfit(
            levels,
            w_values,
            1,
        )
    )

    d_slope, d_intercept = (
        np.polyfit(
            levels,
            d_values,
            1,
        )
    )

    row = {
        "model":
            model,

        "label":
            LABELS[model],

        "wasmtime_pss_20_mib":
            w[20]["mean"],

        "docker_pss_20_mib":
            d[20]["mean"],

        "wasmtime_pss_100_mib":
            w[100]["mean"],

        "docker_pss_100_mib":
            d[100]["mean"],

        "wasmtime_pss_200_mib":
            w[200]["mean"],

        "docker_pss_200_mib":
            d[200]["mean"],

        "docker_over_wasmtime_20":
            (
                d[20]["mean"]
                / w[20]["mean"]
            ),

        "docker_over_wasmtime_100":
            (
                d[100]["mean"]
                / w[100]["mean"]
            ),

        "docker_over_wasmtime_200":
            (
                d[200]["mean"]
                / w[200]["mean"]
            ),

        "wasmtime_memory_reduction_200_pct":
            (
                (
                    d[200]["mean"]
                    - w[200]["mean"]
                )
                / d[200]["mean"]
                * 100.0
            ),

        "wasmtime_pss_per_tenant_200_mib":
            (
                w[200]["mean"]
                / 200.0
            ),

        "docker_pss_per_tenant_200_mib":
            (
                d[200]["mean"]
                / 200.0
            ),

        "wasmtime_growth_slope_mib_per_tenant":
            float(w_slope),

        "docker_growth_slope_mib_per_tenant":
            float(d_slope),

        "wasmtime_fitted_intercept_mib":
            float(w_intercept),

        "docker_fitted_intercept_mib":
            float(d_intercept),

        "slope_ratio_docker_over_wasmtime":
            (
                float(d_slope / w_slope)
                if abs(w_slope) > 1e-12
                else math.inf
            ),

        "wasmtime_ci20_pct":
            w[20]["relative"] * 100.0,

        "docker_ci20_pct":
            d[20]["relative"] * 100.0,

        "wasmtime_ci100_pct":
            w[100]["relative"] * 100.0,

        "docker_ci100_pct":
            d[100]["relative"] * 100.0,

        "wasmtime_ci200_pct":
            w[200]["relative"] * 100.0,

        "docker_ci200_pct":
            d[200]["relative"] * 100.0,

        "wasmtime_n20":
            w[20]["n"],

        "docker_n20":
            d[20]["n"],

        "wasmtime_n100":
            w[100]["n"],

        "docker_n100":
            d[100]["n"],

        "wasmtime_n200":
            w[200]["n"],

        "docker_n200":
            d[200]["n"],
    }

    rows.append(
        row
    )


df = pd.DataFrame(
    rows
)


# Sort for publication:
# lowest Wasmtime memory at 200 tenants first.
df = (
    df.sort_values(
        "wasmtime_pss_200_mib",
        ascending=True,
    )
    .reset_index(drop=True)
)


# ============================================================
# Save full comparison
# ============================================================

COMPARISON_CSV = (
    OUT_DIR
    / "density_uniform_final_comparison.csv"
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
        "wasmtime_pss_20_mib",
        "docker_pss_20_mib",
        "wasmtime_pss_100_mib",
        "docker_pss_100_mib",
        "wasmtime_pss_200_mib",
        "docker_pss_200_mib",
        "docker_over_wasmtime_200",
        "wasmtime_growth_slope_mib_per_tenant",
        "docker_growth_slope_mib_per_tenant",
    ]
].copy()


publication.columns = [
    "Model",
    "Wasm PSS @20 (MiB)",
    "Docker PSS @20 (MiB)",
    "Wasm PSS @100 (MiB)",
    "Docker PSS @100 (MiB)",
    "Wasm PSS @200 (MiB)",
    "Docker PSS @200 (MiB)",
    "Docker/Wasm @200",
    "Wasm Growth (MiB/tenant)",
    "Docker Growth (MiB/tenant)",
]


for col in [
    "Wasm PSS @20 (MiB)",
    "Docker PSS @20 (MiB)",
    "Wasm PSS @100 (MiB)",
    "Docker PSS @100 (MiB)",
    "Wasm PSS @200 (MiB)",
    "Docker PSS @200 (MiB)",
]:

    publication[col] = (
        publication[col]
        .round(3)
    )


publication[
    "Docker/Wasm @200"
] = (
    publication[
        "Docker/Wasm @200"
    ]
    .round(2)
)


publication[
    "Wasm Growth (MiB/tenant)"
] = (
    publication[
        "Wasm Growth (MiB/tenant)"
    ]
    .round(5)
)


publication[
    "Docker Growth (MiB/tenant)"
] = (
    publication[
        "Docker Growth (MiB/tenant)"
    ]
    .round(5)
)


PUBLICATION_CSV = (
    OUT_DIR
    / "density_uniform_publication_table.csv"
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
        "uniform_cross_model_density",

    "models":
        7,

    "backends":
        2,

    "common_density_levels":
        COMMON_LEVELS,

    "configurations":
        14,

    "model_backend_level_cells":
        42,

    "ci_target_percent":
        CI_TARGET * 100.0,

    "all_common_level_ci_pass":
        bool(
            all_ci_pass
        ),

    "wasmtime_lower_pss_20_models":
        int(
            (
                df["wasmtime_pss_20_mib"]
                <
                df["docker_pss_20_mib"]
            ).sum()
        ),

    "wasmtime_lower_pss_100_models":
        int(
            (
                df["wasmtime_pss_100_mib"]
                <
                df["docker_pss_100_mib"]
            ).sum()
        ),

    "wasmtime_lower_pss_200_models":
        int(
            (
                df["wasmtime_pss_200_mib"]
                <
                df["docker_pss_200_mib"]
            ).sum()
        ),

    "mean_docker_over_wasmtime_pss_200":
        float(
            df[
                "docker_over_wasmtime_200"
            ].mean()
        ),

    "median_docker_over_wasmtime_pss_200":
        float(
            df[
                "docker_over_wasmtime_200"
            ].median()
        ),

    "rows":
        df.to_dict(
            orient="records"
        ),
}


ANALYSIS_JSON = (
    OUT_DIR
    / "density_uniform_final_analysis.json"
)

ANALYSIS_JSON.write_text(
    json.dumps(
        analysis,
        indent=2,
    )
)


# ============================================================
# Console output
# ============================================================

print()
print("=" * 128)
print(
    "COMET-Wasm UNIFORM CROSS-MODEL "
    "MEMORY-DENSITY COMPARISON"
)
print("=" * 128)

print(
    f"{'Model':22s} "
    f"{'W20':>8s} "
    f"{'D20':>8s} "
    f"{'W100':>9s} "
    f"{'D100':>9s} "
    f"{'W200':>9s} "
    f"{'D200':>9s} "
    f"{'D/W@200':>9s} "
    f"{'W slope':>10s} "
    f"{'D slope':>10s}"
)

print("-" * 128)


for _, r in df.iterrows():

    print(
        f"{r['label']:22s} "
        f"{r['wasmtime_pss_20_mib']:8.2f} "
        f"{r['docker_pss_20_mib']:8.2f} "
        f"{r['wasmtime_pss_100_mib']:9.2f} "
        f"{r['docker_pss_100_mib']:9.2f} "
        f"{r['wasmtime_pss_200_mib']:9.2f} "
        f"{r['docker_pss_200_mib']:9.2f} "
        f"{r['docker_over_wasmtime_200']:8.2f}x "
        f"{r['wasmtime_growth_slope_mib_per_tenant']:10.5f} "
        f"{r['docker_growth_slope_mib_per_tenant']:10.5f}"
    )


print()
print(
    "Wasmtime lower PSS @20:",
    f"{analysis['wasmtime_lower_pss_20_models']}/7"
)

print(
    "Wasmtime lower PSS @100:",
    f"{analysis['wasmtime_lower_pss_100_models']}/7"
)

print(
    "Wasmtime lower PSS @200:",
    f"{analysis['wasmtime_lower_pss_200_models']}/7"
)

print(
    "Mean Docker/Wasmtime PSS @200:",
    f"{analysis['mean_docker_over_wasmtime_pss_200']:.2f}x"
)

print(
    "All common-level CI targets pass:",
    analysis[
        "all_common_level_ci_pass"
    ]
)


# ============================================================
# Figure 1:
# Cross-model density curves
# ============================================================

fig, ax = plt.subplots(
    figsize=(11.5, 6.5)
)


for _, r in df.iterrows():

    ax.plot(
        COMMON_LEVELS,
        [
            r["wasmtime_pss_20_mib"],
            r["wasmtime_pss_100_mib"],
            r["wasmtime_pss_200_mib"],
        ],
        marker="o",
        label=(
            f"{r['label']} — Wasmtime"
        ),
    )


ax.set_xlabel(
    "Physical Tenants"
)

ax.set_ylabel(
    "Total PSS (MiB)"
)

ax.set_title(
    "Wasmtime Memory Density Across ML Workloads"
)

ax.set_xticks(
    COMMON_LEVELS
)

ax.grid(
    linestyle="--",
    alpha=0.3,
)

ax.legend(
    fontsize=8,
    ncol=2,
)

fig.tight_layout()

WASM_CURVES_PNG = (
    FIG_DIR
    / "density_wasmtime_cross_model.png"
)

WASM_CURVES_PDF = (
    FIG_DIR
    / "density_wasmtime_cross_model.pdf"
)

fig.savefig(
    WASM_CURVES_PNG,
    dpi=300,
    bbox_inches="tight",
)

fig.savefig(
    WASM_CURVES_PDF,
    bbox_inches="tight",
)

plt.close(fig)


# ============================================================
# Figure 2:
# PSS at 200 tenants
# ============================================================

x = np.arange(
    len(df)
)

width = 0.36

fig, ax = plt.subplots(
    figsize=(11, 6.3)
)

wb = ax.bar(
    x - width / 2,
    df["wasmtime_pss_200_mib"],
    width,
    label="Wasmtime",
)

db = ax.bar(
    x + width / 2,
    df["docker_pss_200_mib"],
    width,
    label="Docker",
)

ax.set_ylabel(
    "Total PSS at 200 Tenants (MiB)"
)

ax.set_xlabel(
    "Machine Learning Workload"
)

ax.set_title(
    "Memory Density at 200 Physical Tenants"
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
    alpha=0.3,
)

fig.tight_layout()

PSS200_PNG = (
    FIG_DIR
    / "density_pss_200_tenants.png"
)

PSS200_PDF = (
    FIG_DIR
    / "density_pss_200_tenants.pdf"
)

fig.savefig(
    PSS200_PNG,
    dpi=300,
    bbox_inches="tight",
)

fig.savefig(
    PSS200_PDF,
    bbox_inches="tight",
)

plt.close(fig)


# ============================================================
# Figure 3:
# Docker/Wasmtime ratio at 200
# ============================================================

fig, ax = plt.subplots(
    figsize=(10.5, 6)
)

bars = ax.bar(
    df["label"],
    df[
        "docker_over_wasmtime_200"
    ],
)

ax.set_ylabel(
    "Docker / Wasmtime PSS at 200 Tenants (×)"
)

ax.set_xlabel(
    "Machine Learning Workload"
)

ax.set_title(
    "Docker Memory Cost Relative to Wasmtime "
    "at High Tenant Density"
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

fig.tight_layout()

RATIO_PNG = (
    FIG_DIR
    / "density_ratio_200_tenants.png"
)

RATIO_PDF = (
    FIG_DIR
    / "density_ratio_200_tenants.pdf"
)

fig.savefig(
    RATIO_PNG,
    dpi=300,
    bbox_inches="tight",
)

fig.savefig(
    RATIO_PDF,
    bbox_inches="tight",
)

plt.close(fig)


# ============================================================
# Figure 4:
# Marginal memory growth slope
# ============================================================

fig, ax = plt.subplots(
    figsize=(11, 6.3)
)

wb = ax.bar(
    x - width / 2,
    df[
        "wasmtime_growth_slope_mib_per_tenant"
    ],
    width,
    label="Wasmtime",
)

db = ax.bar(
    x + width / 2,
    df[
        "docker_growth_slope_mib_per_tenant"
    ],
    width,
    label="Docker",
)

ax.set_ylabel(
    "Fitted Memory Growth (MiB / Tenant)"
)

ax.set_xlabel(
    "Machine Learning Workload"
)

ax.set_title(
    "Incremental Memory Growth with Tenant Density"
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
    alpha=0.3,
)

fig.tight_layout()

SLOPE_PNG = (
    FIG_DIR
    / "density_memory_growth_slope.png"
)

SLOPE_PDF = (
    FIG_DIR
    / "density_memory_growth_slope.pdf"
)

fig.savefig(
    SLOPE_PNG,
    dpi=300,
    bbox_inches="tight",
)

fig.savefig(
    SLOPE_PDF,
    bbox_inches="tight",
)

plt.close(fig)


print()
print("=" * 86)
print(
    "UNIFORM DENSITY CONSOLIDATION: PASS"
)
print("=" * 86)

print(
    "Comparison:",
    COMPARISON_CSV
)

print(
    "Publication table:",
    PUBLICATION_CSV
)

print(
    "Analysis:",
    ANALYSIS_JSON
)

print(
    "Figures:",
    FIG_DIR
)

