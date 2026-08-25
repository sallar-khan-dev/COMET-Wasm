#!/usr/bin/env python3

import csv
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[2]

WASM_CSV = ROOT / "results/raw/density/wasmtime_nb_density_pilot.csv"
DOCKER_CSV = ROOT / "results/raw/density/docker_nb_density_pilot.csv"

OUT_CSV = ROOT / "results/processed/density/nb_density_pilot_comparison.csv"
OUT_JSON = ROOT / "results/processed/density/nb_density_pilot_analysis.json"
OUT_FIG = ROOT / "figures/nb_density_pilot_pss.png"


def load_wasmtime():
    df = pd.read_csv(WASM_CSV)

    if "physical_workers" not in df.columns:
        raise RuntimeError(
            "Wasmtime CSV missing physical_workers column"
        )

    return df.rename(
        columns={
            "physical_workers": "physical_tenants"
        }
    )


def load_docker():
    df = pd.read_csv(DOCKER_CSV)

    if "containers" in df.columns:
        df = df.rename(
            columns={
                "containers": "physical_tenants"
            }
        )

    elif "physical_containers" in df.columns:
        df = df.rename(
            columns={
                "physical_containers": "physical_tenants"
            }
        )

    else:
        raise RuntimeError(
            "Docker CSV missing container-count column"
        )

    return df


def summarize(df, backend):
    grouped = (
        df.groupby("physical_tenants")
        .agg(
            n=("pss_mib", "count"),
            rss_mean_mib=("rss_mib", "mean"),
            rss_sd_mib=("rss_mib", "std"),
            pss_mean_mib=("pss_mib", "mean"),
            pss_sd_mib=("pss_mib", "std"),
            private_mean_mib=("private_mib", "mean"),
        )
        .reset_index()
    )

    grouped["backend"] = backend

    return grouped


def linear_fit(summary):
    x = summary["physical_tenants"].to_numpy(
        dtype=float
    )

    y = summary["pss_mean_mib"].to_numpy(
        dtype=float
    )

    slope, intercept = np.polyfit(
        x,
        y,
        1
    )

    predicted = (
        slope * x + intercept
    )

    ss_res = np.sum(
        (y - predicted) ** 2
    )

    ss_tot = np.sum(
        (y - np.mean(y)) ** 2
    )

    r2 = (
        1.0 - ss_res / ss_tot
        if ss_tot > 0
        else 1.0
    )

    return {
        "slope_mib_per_tenant":
            float(slope),

        "intercept_mib":
            float(intercept),

        "r2":
            float(r2),
    }


wasm_raw = load_wasmtime()
docker_raw = load_docker()

wasm = summarize(
    wasm_raw,
    "wasmtime"
)

docker = summarize(
    docker_raw,
    "docker"
)

expected_levels = {
    1,
    5,
    10,
    20
}

assert (
    set(wasm["physical_tenants"])
    == expected_levels
), "Unexpected Wasmtime tenant levels"

assert (
    set(docker["physical_tenants"])
    == expected_levels
), "Unexpected Docker tenant levels"


wasm_fit = linear_fit(
    wasm
)

docker_fit = linear_fit(
    docker
)


comparison = pd.merge(
    wasm[
        [
            "physical_tenants",
            "pss_mean_mib",
            "pss_sd_mib",
            "rss_mean_mib",
        ]
    ],
    docker[
        [
            "physical_tenants",
            "pss_mean_mib",
            "pss_sd_mib",
            "rss_mean_mib",
        ]
    ],
    on="physical_tenants",
    suffixes=(
        "_wasmtime",
        "_docker"
    )
)


comparison["docker_to_wasmtime_pss_ratio"] = (
    comparison["pss_mean_mib_docker"]
    /
    comparison["pss_mean_mib_wasmtime"]
)

comparison["pss_difference_mib"] = (
    comparison["pss_mean_mib_docker"]
    -
    comparison["pss_mean_mib_wasmtime"]
)

comparison[
    "wasmtime_pss_per_physical_tenant_mib"
] = (
    comparison["pss_mean_mib_wasmtime"]
    /
    comparison["physical_tenants"]
)

comparison[
    "docker_pss_per_physical_tenant_mib"
] = (
    comparison["pss_mean_mib_docker"]
    /
    comparison["physical_tenants"]
)


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

    crossover = (
        wasm_fit["intercept_mib"]
        -
        docker_fit["intercept_mib"]
    ) / denominator

else:
    crossover = None


OUT_CSV.parent.mkdir(
    parents=True,
    exist_ok=True
)

comparison.to_csv(
    OUT_CSV,
    index=False
)


analysis = {
    "experiment":
        "naive_bayes_density_pilot",

    "tenant_levels":
        sorted(expected_levels),

    "wasmtime_fit":
        wasm_fit,

    "docker_fit":
        docker_fit,

    "estimated_pss_crossover_tenants":
        (
            float(crossover)
            if crossover is not None
            else None
        ),

    "comparison":
        comparison.to_dict(
            orient="records"
        ),

    "interpretation_note":
        (
            "Pilot only. Results must not be "
            "treated as final publication claims "
            "until the full CI-controlled density "
            "experiment is completed."
        ),
}

OUT_JSON.write_text(
    json.dumps(
        analysis,
        indent=2
    )
)


# ============================================================
# Figure
# ============================================================

plt.figure(
    figsize=(7.5, 4.8)
)

plt.errorbar(
    wasm["physical_tenants"],
    wasm["pss_mean_mib"],
    yerr=wasm["pss_sd_mib"],
    marker="o",
    capsize=4,
    label="Wasmtime"
)

plt.errorbar(
    docker["physical_tenants"],
    docker["pss_mean_mib"],
    yerr=docker["pss_sd_mib"],
    marker="s",
    capsize=4,
    label="Docker"
)

plt.xlabel(
    "Physical tenants / isolated instances"
)

plt.ylabel(
    "Total PSS (MiB)"
)

plt.title(
    "Naive Bayes Memory-Density Pilot"
)

plt.xticks(
    [1, 5, 10, 20]
)

plt.grid(
    alpha=0.25
)

plt.legend()

plt.tight_layout()

plt.savefig(
    OUT_FIG,
    dpi=300
)

plt.close()


# ============================================================
# Terminal report
# ============================================================

print(
    "===== COMET-Wasm Density Pilot Analysis ====="
)

print()

print(
    "Wasmtime:"
)
print(
    "  slope     = "
    f"{wasm_fit['slope_mib_per_tenant']:.4f} "
    "MiB/tenant"
)
print(
    "  intercept = "
    f"{wasm_fit['intercept_mib']:.4f} MiB"
)
print(
    "  R^2       = "
    f"{wasm_fit['r2']:.6f}"
)

print()

print(
    "Docker:"
)
print(
    "  slope     = "
    f"{docker_fit['slope_mib_per_tenant']:.4f} "
    "MiB/tenant"
)
print(
    "  intercept = "
    f"{docker_fit['intercept_mib']:.4f} MiB"
)
print(
    "  R^2       = "
    f"{docker_fit['r2']:.6f}"
)

print()

if crossover is not None:
    print(
        "Estimated fitted crossover: "
        f"{crossover:.2f} physical tenants"
    )

print()

print(
    comparison[
        [
            "physical_tenants",
            "pss_mean_mib_wasmtime",
            "pss_mean_mib_docker",
            "docker_to_wasmtime_pss_ratio",
            "pss_difference_mib",
        ]
    ].to_string(
        index=False
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
    "Figure:",
    OUT_FIG
)

print()

print(
    "DENSITY PILOT ANALYSIS: PASS"
)
