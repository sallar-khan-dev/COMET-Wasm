#!/usr/bin/env python3

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.stats import t as student_t


ROOT = Path(__file__).resolve().parents[2]

WASM_RAW = (
    ROOT
    / "results/raw/density/"
    "wasmtime_naive_bayes_density_full.csv"
)

DOCKER_RAW = (
    ROOT
    / "results/raw/density/"
    "docker_naive_bayes_density_full.csv"
)

OUT_DIR = (
    ROOT
    / "results/processed/density"
)

FIG_DIR = ROOT / "figures"

OUT_DIR.mkdir(
    parents=True,
    exist_ok=True
)

FIG_DIR.mkdir(
    parents=True,
    exist_ok=True
)

OUT_CSV = (
    OUT_DIR
    / "naive_bayes_density_final_comparison.csv"
)

OUT_JSON = (
    OUT_DIR
    / "naive_bayes_density_final_analysis.json"
)

OUT_FIG = (
    FIG_DIR
    / "naive_bayes_density_full_pss.png"
)

OUT_FIG_LOG = (
    FIG_DIR
    / "naive_bayes_density_full_pss_log.png"
)


# ============================================================
# Helpers
# ============================================================

def summarize(path, backend):

    df = pd.read_csv(path)

    rows = []

    for level, group in df.groupby(
        "physical_tenants"
    ):

        values = group[
            "pss_mib"
        ].astype(float)

        rss = group[
            "rss_mib"
        ].astype(float)

        private = group[
            "private_mib"
        ].astype(float)

        n = len(values)

        mean = values.mean()

        sd = values.std(
            ddof=1
        )

        critical = student_t.ppf(
            0.975,
            n - 1
        )

        halfwidth = (
            critical
            * sd
            / math.sqrt(n)
        )

        rows.append({
            "backend":
                backend,

            "physical_tenants":
                int(level),

            "n":
                int(n),

            "pss_mean_mib":
                float(mean),

            "pss_sd_mib":
                float(sd),

            "ci95_halfwidth_mib":
                float(halfwidth),

            "ci95_lower_mib":
                float(
                    mean
                    - halfwidth
                ),

            "ci95_upper_mib":
                float(
                    mean
                    + halfwidth
                ),

            "relative_ci_halfwidth_pct":
                float(
                    halfwidth
                    / mean
                    * 100.0
                ),

            "rss_mean_mib":
                float(
                    rss.mean()
                ),

            "private_mean_mib":
                float(
                    private.mean()
                ),
        })

    result = pd.DataFrame(
        rows
    ).sort_values(
        "physical_tenants"
    )

    return result


def regression(summary):

    x = summary[
        "physical_tenants"
    ].to_numpy(
        dtype=float
    )

    y = summary[
        "pss_mean_mib"
    ].to_numpy(
        dtype=float
    )

    slope, intercept = np.polyfit(
        x,
        y,
        1
    )

    predicted = (
        intercept
        + slope * x
    )

    ss_res = np.sum(
        (y - predicted) ** 2
    )

    ss_tot = np.sum(
        (y - np.mean(y)) ** 2
    )

    r2 = (
        1.0
        - ss_res / ss_tot
        if ss_tot > 0
        else 1.0
    )

    return {
        "intercept_mib":
            float(intercept),

        "slope_mib_per_tenant":
            float(slope),

        "slope_kib_per_tenant":
            float(
                slope * 1024.0
            ),

        "r2":
            float(r2),
    }


# ============================================================
# Load and summarize
# ============================================================

wasm = summarize(
    WASM_RAW,
    "wasmtime"
)

docker = summarize(
    DOCKER_RAW,
    "docker"
)

expected = [
    1,
    5,
    10,
    20,
    50,
    100,
    200,
]

assert (
    wasm[
        "physical_tenants"
    ].tolist()
    == expected
)

assert (
    docker[
        "physical_tenants"
    ].tolist()
    == expected
)

assert all(
    wasm["n"] == 20
)

assert all(
    docker["n"] == 20
)


wasm_fit = regression(
    wasm
)

docker_fit = regression(
    docker
)


# ============================================================
# Pair comparison
# ============================================================

comparison = pd.merge(
    wasm,
    docker,
    on="physical_tenants",
    suffixes=(
        "_wasmtime",
        "_docker"
    )
)


comparison[
    "docker_to_wasmtime_pss_ratio"
] = (
    comparison[
        "pss_mean_mib_docker"
    ]
    /
    comparison[
        "pss_mean_mib_wasmtime"
    ]
)


comparison[
    "docker_minus_wasmtime_mib"
] = (
    comparison[
        "pss_mean_mib_docker"
    ]
    -
    comparison[
        "pss_mean_mib_wasmtime"
    ]
)


comparison[
    "wasmtime_memory_reduction_vs_docker_pct"
] = (
    1.0
    -
    comparison[
        "pss_mean_mib_wasmtime"
    ]
    /
    comparison[
        "pss_mean_mib_docker"
    ]
) * 100.0


comparison[
    "wasmtime_pss_per_tenant_mib"
] = (
    comparison[
        "pss_mean_mib_wasmtime"
    ]
    /
    comparison[
        "physical_tenants"
    ]
)


comparison[
    "docker_pss_per_tenant_mib"
] = (
    comparison[
        "pss_mean_mib_docker"
    ]
    /
    comparison[
        "physical_tenants"
    ]
)


# ============================================================
# Crossover analysis
# ============================================================

denominator = (
    docker_fit[
        "slope_mib_per_tenant"
    ]
    -
    wasm_fit[
        "slope_mib_per_tenant"
    ]
)

if abs(denominator) > 1e-12:

    fitted_crossover = (
        wasm_fit[
            "intercept_mib"
        ]
        -
        docker_fit[
            "intercept_mib"
        ]
    ) / denominator

else:
    fitted_crossover = None


observed_lower = None
observed_upper = None

previous = None

for _, row in comparison.iterrows():

    difference = (
        row[
            "docker_minus_wasmtime_mib"
        ]
    )

    if (
        previous is not None
        and previous[
            "difference"
        ] < 0
        and difference > 0
    ):

        observed_lower = (
            previous[
                "physical_tenants"
            ]
        )

        observed_upper = (
            int(
                row[
                    "physical_tenants"
                ]
            )
        )

        break

    previous = {
        "physical_tenants":
            int(
                row[
                    "physical_tenants"
                ]
            ),

        "difference":
            float(difference),
    }


# ============================================================
# Save table
# ============================================================

columns = [
    "physical_tenants",

    "pss_mean_mib_wasmtime",
    "ci95_halfwidth_mib_wasmtime",

    "pss_mean_mib_docker",
    "ci95_halfwidth_mib_docker",

    "docker_to_wasmtime_pss_ratio",

    "docker_minus_wasmtime_mib",

    "wasmtime_memory_reduction_vs_docker_pct",

    "wasmtime_pss_per_tenant_mib",
    "docker_pss_per_tenant_mib",
]


comparison[
    columns
].to_csv(
    OUT_CSV,
    index=False
)


# ============================================================
# JSON
# ============================================================

analysis = {
    "experiment":
        "naive_bayes_full_density",

    "observations":
        {
            "wasmtime":
                140,

            "docker":
                140,

            "total":
                280,
        },

    "density_levels":
        expected,

    "repetitions_per_level":
        20,

    "wasmtime_regression":
        wasm_fit,

    "docker_regression":
        docker_fit,

    "fitted_crossover_tenants":
        (
            float(
                fitted_crossover
            )
            if fitted_crossover
            is not None
            else None
        ),

    "observed_crossover_interval":
        (
            [
                int(
                    observed_lower
                ),
                int(
                    observed_upper
                ),
            ]
            if (
                observed_lower
                is not None
            )
            else None
        ),

    "comparison":
        comparison[
            columns
        ].to_dict(
            orient="records"
        ),

    "measurement_scope":
        (
            "Process-level PSS. "
            "Wasmtime represents one "
            "server process containing "
            "all independent Stores and "
            "Instances. Docker represents "
            "aggregate PSS across native "
            "inference processes inside "
            "containers."
        ),
}


OUT_JSON.write_text(
    json.dumps(
        analysis,
        indent=2
    )
)


# ============================================================
# Main publication figure
# ============================================================

plt.figure(
    figsize=(8.0, 5.2)
)

plt.errorbar(
    wasm[
        "physical_tenants"
    ],
    wasm[
        "pss_mean_mib"
    ],
    yerr=wasm[
        "ci95_halfwidth_mib"
    ],
    marker="o",
    capsize=4,
    linewidth=1.8,
    label="Wasmtime"
)

plt.errorbar(
    docker[
        "physical_tenants"
    ],
    docker[
        "pss_mean_mib"
    ],
    yerr=docker[
        "ci95_halfwidth_mib"
    ],
    marker="s",
    capsize=4,
    linewidth=1.8,
    label="Docker"
)

plt.xlabel(
    "Physical isolated inference instances"
)

plt.ylabel(
    "Aggregate inference-process PSS (MiB)"
)

plt.title(
    "Memory Density: Wasmtime vs Docker"
)

plt.xticks(
    expected
)

plt.grid(
    alpha=0.25
)

plt.legend()

plt.tight_layout()

plt.savefig(
    OUT_FIG,
    dpi=300,
    bbox_inches="tight"
)

plt.close()


# ============================================================
# Log-scale figure
# ============================================================

plt.figure(
    figsize=(8.0, 5.2)
)

plt.errorbar(
    wasm[
        "physical_tenants"
    ],
    wasm[
        "pss_mean_mib"
    ],
    yerr=wasm[
        "ci95_halfwidth_mib"
    ],
    marker="o",
    capsize=4,
    linewidth=1.8,
    label="Wasmtime"
)

plt.errorbar(
    docker[
        "physical_tenants"
    ],
    docker[
        "pss_mean_mib"
    ],
    yerr=docker[
        "ci95_halfwidth_mib"
    ],
    marker="s",
    capsize=4,
    linewidth=1.8,
    label="Docker"
)

plt.yscale(
    "log"
)

plt.xlabel(
    "Physical isolated inference instances"
)

plt.ylabel(
    "Aggregate inference-process PSS (MiB, log scale)"
)

plt.title(
    "Memory-Density Scaling: Wasmtime vs Docker"
)

plt.xticks(
    expected
)

plt.grid(
    alpha=0.25
)

plt.legend()

plt.tight_layout()

plt.savefig(
    OUT_FIG_LOG,
    dpi=300,
    bbox_inches="tight"
)

plt.close()


# ============================================================
# Terminal summary
# ============================================================

print()
print(
    "=" * 76
)

print(
    "COMET-Wasm FULL NAIVE BAYES "
    "DENSITY ANALYSIS"
)

print(
    "=" * 76
)

print()

print(
    "Wasmtime linear model:"
)

print(
    "  intercept = "
    f"{wasm_fit['intercept_mib']:.4f} MiB"
)

print(
    "  slope     = "
    f"{wasm_fit['slope_mib_per_tenant']:.6f} "
    "MiB/tenant"
)

print(
    "              "
    f"{wasm_fit['slope_kib_per_tenant']:.3f} "
    "KiB/tenant"
)

print(
    "  R^2       = "
    f"{wasm_fit['r2']:.6f}"
)

print()

print(
    "Docker linear model:"
)

print(
    "  intercept = "
    f"{docker_fit['intercept_mib']:.4f} MiB"
)

print(
    "  slope     = "
    f"{docker_fit['slope_mib_per_tenant']:.6f} "
    "MiB/tenant"
)

print(
    "              "
    f"{docker_fit['slope_kib_per_tenant']:.3f} "
    "KiB/tenant"
)

print(
    "  R^2       = "
    f"{docker_fit['r2']:.6f}"
)

print()

if fitted_crossover is not None:

    print(
        "Fitted crossover: "
        f"{fitted_crossover:.2f} tenants"
    )

if observed_lower is not None:

    print(
        "Observed crossover occurs between "
        f"{observed_lower} and "
        f"{observed_upper} tenants."
    )

print()

display = comparison[
    [
        "physical_tenants",

        "pss_mean_mib_wasmtime",

        "pss_mean_mib_docker",

        "docker_to_wasmtime_pss_ratio",

        "wasmtime_memory_reduction_vs_docker_pct",
    ]
].copy()

display.columns = [
    "Tenants",
    "Wasmtime_PSS",
    "Docker_PSS",
    "Docker/Wasm",
    "Wasm_reduction_%",
]

print(
    display.to_string(
        index=False,
        float_format=lambda x:
            f"{x:.3f}"
    )
)

print()

print(
    "Comparison CSV:",
    OUT_CSV
)

print(
    "Analysis JSON:",
    OUT_JSON
)

print(
    "Main figure:",
    OUT_FIG
)

print(
    "Log figure:",
    OUT_FIG_LOG
)

print()

print(
    "FULL DENSITY STATISTICAL ANALYSIS: PASS"
)
