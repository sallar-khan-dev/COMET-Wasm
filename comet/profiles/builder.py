#!/usr/bin/env python3

import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

import pandas as pd
import numpy as np
from scipy.stats import t as student_t


ROOT = Path(__file__).resolve().parents[2]


def json_default(obj):
    """
    Convert NumPy scalar values produced by Pandas/SciPy
    into native Python values for JSON serialization.
    """

    if isinstance(obj, np.generic):
        return obj.item()

    raise TypeError(
        f"Object of type {type(obj).__name__} "
        "is not JSON serializable"
    )


MODELS = [
    "logistic_regression",
    "naive_bayes",
    "decision_tree",
    "kmeans",
    "random_forest",
    "svm",
    "mlp",
]

BACKENDS = [
    "wasmtime",
    "docker",
]

CONCURRENCY_LEVELS = [
    1, 2, 4, 8, 16, 32, 64, 128, 256
]

CI_TARGET = 0.025

OUT_DIR = ROOT / "results/processed/comet"
OUT_DIR.mkdir(parents=True, exist_ok=True)


EXECUTION_CSV = (
    ROOT
    / "results/processed/execution_time/"
    "execution_time_final_comparison.csv"
)

COLD_CSV = (
    ROOT
    / "results/processed/cold_start/"
    "cold_start_final_comparison.csv"
)

DENSITY_CSV = (
    ROOT
    / "results/processed/density/"
    "density_uniform_final_comparison.csv"
)

INTERFERENCE_CSV = (
    ROOT
    / "results/processed/interference/"
    "interference_final_comparison.csv"
)


def require(path):
    if not path.exists():
        raise FileNotFoundError(path)


for path in [
    EXECUTION_CSV,
    COLD_CSV,
    DENSITY_CSV,
    INTERFERENCE_CSV,
]:
    require(path)


def ci95(values):

    values = [float(x) for x in values]

    n = len(values)

    if n == 0:
        raise RuntimeError("Empty sample")

    mean = statistics.mean(values)

    if n == 1:
        return {
            "n": 1,
            "mean": mean,
            "sd": 0.0,
            "halfwidth": float("inf"),
            "relative": float("inf"),
        }

    sd = statistics.stdev(values)

    critical = student_t.ppf(
        0.975,
        n - 1,
    )

    hw = (
        critical
        * sd
        / math.sqrt(n)
    )

    rel = (
        hw / abs(mean)
        if abs(mean) > 1e-12
        else float("inf")
    )

    return {
        "n": n,
        "mean": mean,
        "sd": sd,
        "halfwidth": hw,
        "relative": rel,
    }


def row_for_model(df, model):

    subset = df[
        df["model"] == model
    ]

    if len(subset) != 1:
        raise RuntimeError(
            f"{model}: expected 1 row, "
            f"found {len(subset)}"
        )

    return subset.iloc[0]


# ============================================================
# Load consolidated evidence
# ============================================================

execution = pd.read_csv(
    EXECUTION_CSV
)

cold = pd.read_csv(
    COLD_CSV
)

density = pd.read_csv(
    DENSITY_CSV
)

interference = pd.read_csv(
    INTERFERENCE_CSV
)


# ============================================================
# Performance evidence from RAW CSV
# ============================================================

def performance_curve(
    backend,
    model,
):

    path = (
        ROOT
        / "results/raw/performance/"
        f"{backend}_{model}_performance_full.csv"
    )

    require(path)

    with path.open(
        newline=""
    ) as f:

        rows = list(
            csv.DictReader(f)
        )

    grouped = defaultdict(list)

    for row in rows:
        grouped[
            int(row["concurrency"])
        ].append(row)

    levels = sorted(grouped)

    if levels != CONCURRENCY_LEVELS:

        raise RuntimeError(
            f"{backend}/{model}: "
            f"levels={levels}"
        )

    result = {}

    for c in CONCURRENCY_LEVELS:

        records = grouped[c]

        throughput = ci95(
            [
                float(x["throughput_rps"])
                for x in records
            ]
        )

        p95 = ci95(
            [
                float(x["p95_latency_ms"])
                for x in records
            ]
        )

        p99 = ci95(
            [
                float(x["p99_latency_ms"])
                for x in records
            ]
        )

        result[str(c)] = {
            "concurrency": c,
            "repetitions": len(records),

            "throughput_rps":
                throughput,

            "p95_latency_ms":
                p95,

            "p99_latency_ms":
                p99,

            "error_rate_mean":
                statistics.mean(
                    [
                        float(
                            x["error_rate"]
                        )
                        for x in records
                    ]
                ),

            "ci_target_met":
                (
                    throughput[
                        "relative"
                    ] <= CI_TARGET
                    and
                    p95[
                        "relative"
                    ] <= CI_TARGET
                    and
                    p99[
                        "relative"
                    ] <= CI_TARGET
                ),
        }

    return result


# ============================================================
# Interference aggregation
# ============================================================

interference_lookup = {}

for backend in BACKENDS:

    for model in MODELS:

        subset = interference[
            (
                interference[
                    "backend"
                ] == backend
            )
            &
            (
                interference[
                    "model"
                ] == model
            )
        ]

        if subset.empty:
            raise RuntimeError(
                f"No interference data: "
                f"{backend}/{model}"
            )

        interference_lookup[
            (backend, model)
        ] = {
            "observations":
                len(subset),

            "mean_p95_degradation_pct":
                float(
                    subset[
                        "p95_degradation_pct"
                    ].mean()
                ),

            "max_p95_degradation_pct":
                float(
                    subset[
                        "p95_degradation_pct"
                    ].max()
                ),

            "mean_throughput_degradation_pct":
                float(
                    subset[
                        "throughput_degradation_pct"
                    ].mean()
                ),
        }


# ============================================================
# Build profiles
# ============================================================

profiles = []

for model in MODELS:

    ex = row_for_model(
        execution,
        model,
    )

    cs = row_for_model(
        cold,
        model,
    )

    den = row_for_model(
        density,
        model,
    )

    for backend in BACKENDS:

        curve = performance_curve(
            backend,
            model,
        )

        c32 = curve["32"]

        peak_c = max(
            CONCURRENCY_LEVELS,
            key=lambda c:
                curve[str(c)][
                    "throughput_rps"
                ]["mean"]
        )

        if backend == "wasmtime":

            execution_us = float(
                ex["wasmtime_us"]
            )

            startup_ms = float(
                cs[
                    "wasmtime_startup_ms"
                ]
            )

            cold_result_ms = float(
                cs[
                    "wasmtime_cold_to_first_result_ms"
                ]
            )

            pss20 = float(
                den[
                    "wasmtime_pss_20_mib"
                ]
            )

            pss100 = float(
                den[
                    "wasmtime_pss_100_mib"
                ]
            )

            pss200 = float(
                den[
                    "wasmtime_pss_200_mib"
                ]
            )

            slope = float(
                den[
                    "wasmtime_growth_slope_mib_per_tenant"
                ]
            )

        else:

            execution_us = float(
                ex["docker_us"]
            )

            startup_ms = float(
                cs[
                    "docker_startup_ms"
                ]
            )

            cold_result_ms = float(
                cs[
                    "docker_cold_to_first_result_ms"
                ]
            )

            pss20 = float(
                den[
                    "docker_pss_20_mib"
                ]
            )

            pss100 = float(
                den[
                    "docker_pss_100_mib"
                ]
            )

            pss200 = float(
                den[
                    "docker_pss_200_mib"
                ]
            )

            slope = float(
                den[
                    "docker_growth_slope_mib_per_tenant"
                ]
            )

        inter = interference_lookup[
            (backend, model)
        ]

        profiles.append({
            "model":
                model,

            "backend":
                backend,

            "raw": {
                "execution_us":
                    execution_us,

                "throughput_rps_c32":
                    c32[
                        "throughput_rps"
                    ]["mean"],

                "p95_latency_ms_c32":
                    c32[
                        "p95_latency_ms"
                    ]["mean"],

                "p99_latency_ms_c32":
                    c32[
                        "p99_latency_ms"
                    ]["mean"],

                "peak_throughput_rps":
                    curve[
                        str(peak_c)
                    ][
                        "throughput_rps"
                    ]["mean"],

                "peak_throughput_concurrency":
                    peak_c,

                "pss_20_mib":
                    pss20,

                "pss_100_mib":
                    pss100,

                "pss_200_mib":
                    pss200,

                "memory_growth_mib_per_tenant":
                    slope,

                "startup_ms":
                    startup_ms,

                "cold_to_first_result_ms":
                    cold_result_ms,

                "interference_p95_degradation_pct":
                    inter[
                        "mean_p95_degradation_pct"
                    ],

                "interference_throughput_degradation_pct":
                    inter[
                        "mean_throughput_degradation_pct"
                    ],

                "interference_observations":
                    inter[
                        "observations"
                    ],
            },

            "performance_curve":
                curve,
        })


# ============================================================
# Normalization
# ============================================================

METRICS = {
    "compute_efficiency":
        ("execution_us", "low"),

    "memory_efficiency":
        ("pss_200_mib", "low"),

    "latency_efficiency":
        ("p95_latency_ms_c32", "low"),

    "throughput_efficiency":
        ("throughput_rps_c32", "high"),

    "startup_efficiency":
        ("startup_ms", "low"),

    "density_efficiency":
        (
            "memory_growth_mib_per_tenant",
            "low",
        ),

    "interference_resilience":
        (
            "interference_p95_degradation_pct",
            "low",
        ),
}

normalization = {}

for name, (
    raw_metric,
    direction,
) in METRICS.items():

    values = [
        float(
            p["raw"][raw_metric]
        )
        for p in profiles
    ]

    lo = min(values)
    hi = max(values)

    normalization[name] = {
        "raw_metric":
            raw_metric,

        "minimum":
            lo,

        "maximum":
            hi,

        "direction":
            direction,
    }

    for p in profiles:

        value = float(
            p["raw"][raw_metric]
        )

        if abs(
            hi - lo
        ) < 1e-12:

            score = 1.0

        elif direction == "high":

            score = (
                value - lo
            ) / (
                hi - lo
            )

        else:

            score = 1.0 - (
                (
                    value - lo
                )
                /
                (
                    hi - lo
                )
            )

        p.setdefault(
            "normalized",
            {}
        )[name] = float(score)


# ============================================================
# Validation
# ============================================================

validation = {
    "models": 7,
    "backends": 2,
    "expected_profiles": 14,
    "actual_profiles":
        len(profiles),

    "expected_performance_cells":
        126,

    "actual_performance_cells":
        sum(
            len(
                p[
                    "performance_curve"
                ]
            )
            for p in profiles
        ),

    "profile_dimensions": [
        "compute",
        "memory",
        "latency",
        "throughput",
        "startup",
        "density",
        "interference",
    ],
}

validation[
    "pass"
] = (
    validation[
        "actual_profiles"
    ] == 14
    and
    validation[
        "actual_performance_cells"
    ] == 126
)


if not validation["pass"]:
    raise RuntimeError(
        json.dumps(
            validation,
            indent=2,
        )
    )


# ============================================================
# Persistence
# ============================================================

payload = {
    "schema_version":
        "comet-profile-v1",

    "canonical_scoring_concurrency":
        32,

    "performance_concurrency_levels":
        CONCURRENCY_LEVELS,

    "relative_ci_target":
        CI_TARGET,

    "profiles":
        profiles,
}


(
    OUT_DIR
    / "characterization_profiles.json"
).write_text(
    json.dumps(
        payload,
        indent=2,
        default=json_default,
    )
)


flat = []

for p in profiles:

    row = {
        "model":
            p["model"],

        "backend":
            p["backend"],
    }

    row.update(
        p["raw"]
    )

    row.update(
        p["normalized"]
    )

    flat.append(row)


pd.DataFrame(
    flat
).to_csv(
    OUT_DIR
    / "characterization_profiles.csv",
    index=False,
)


(
    OUT_DIR
    / "normalization_parameters.json"
).write_text(
    json.dumps(
        normalization,
        indent=2,
        default=json_default,
    )
)


(
    OUT_DIR
    / "profile_validation.json"
).write_text(
    json.dumps(
        validation,
        indent=2,
        default=json_default,
    )
)


# ============================================================
# Console
# ============================================================

print("=" * 126)
print(
    "COMET-Wasm EMPIRICAL "
    "CHARACTERIZATION PROFILE DATABASE"
)
print("=" * 126)

print(
    f"{'Model':22s} "
    f"{'Backend':9s} "
    f"{'Exec(us)':>10s} "
    f"{'P95@32':>10s} "
    f"{'RPS@32':>10s} "
    f"{'PSS@200':>10s} "
    f"{'Startup':>10s} "
    f"{'Int-P95':>10s}"
)

print("-" * 126)

for p in profiles:

    r = p["raw"]

    print(
        f"{p['model']:22s} "
        f"{p['backend']:9s} "
        f"{r['execution_us']:10.4f} "
        f"{r['p95_latency_ms_c32']:10.3f} "
        f"{r['throughput_rps_c32']:10.1f} "
        f"{r['pss_200_mib']:10.2f} "
        f"{r['startup_ms']:10.2f} "
        f"{r['interference_p95_degradation_pct']:9.2f}%"
    )

print()
print(
    "Profiles:",
    f"{len(profiles)}/14"
)

print(
    "Performance cells:",
    f"{validation['actual_performance_cells']}/126"
)

print(
    "PROFILE VALIDATION:",
    "PASS"
)

print()
print(
    "Output:",
    OUT_DIR
)

