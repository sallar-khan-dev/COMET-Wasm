#!/usr/bin/env python3

import argparse
import csv
import json
import math
import signal
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from scipy.stats import t as student_t


ROOT = Path(__file__).resolve().parents[2]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from comet.evaluation.live_backend import (
    CLIENT_CPUSET,
    LiveBackendPair,
)
from comet.scheduler.scheduler import (
    CometScheduler,
)


# ============================================================
# Frozen held-out protocol
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

POLICIES = [
    "comet",
    "wasmtime_only",
    "docker_only",
    "random",
    "best_static",
]

HELDOUT_CONCURRENCIES = [
    24,
    48,
    96,
    192,
]

PHYSICAL_UNITS = 20
TENANTS = 20

REQUESTS = 5000

MIN_REPS = 20
MAX_REPS = 60

CONFIDENCE_LEVEL = 0.95
CI_TARGET = 0.025

COOLDOWN_SECONDS = 1.0

SEED = 42

# Frozen before held-out measurements.
BEST_STATIC_BACKEND = "wasmtime"


RAW_DIR = (
    ROOT
    / "results"
    / "raw"
    / "evaluation"
    / "live_heldout"
)

PROC_DIR = (
    ROOT
    / "results"
    / "processed"
    / "evaluation"
)

RAW_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

PROC_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


# ============================================================
# CLI
# ============================================================

parser = argparse.ArgumentParser()

parser.add_argument(
    "--model",
    choices=MODELS,
)

parser.add_argument(
    "--policy",
    choices=POLICIES,
)

parser.add_argument(
    "--levels",
    nargs="*",
    type=int,
)

parser.add_argument(
    "--fresh",
    action="store_true",
)

parser.add_argument(
    "--smoke",
    action="store_true",
    help=(
        "Run 3 repetitions with 500 requests. "
        "No scientific result files."
    ),
)

args = parser.parse_args()


SELECTED_MODELS = (
    [args.model]
    if args.model
    else MODELS
)

SELECTED_POLICIES = (
    [args.policy]
    if args.policy
    else POLICIES
)

SELECTED_LEVELS = (
    args.levels
    if args.levels
    else HELDOUT_CONCURRENCIES
)


for level in SELECTED_LEVELS:
    if level not in HELDOUT_CONCURRENCIES:
        raise SystemExit(
            f"{level} is not a frozen held-out "
            "concurrency level."
        )


# ============================================================
# Statistics
# ============================================================

def ci_stats(values):

    values = [
        float(v)
        for v in values
    ]

    n = len(values)

    if n == 0:
        return {
            "n": 0,
            "mean": None,
            "sd": None,
            "halfwidth": None,
            "relative": None,
        }

    mean = statistics.mean(
        values
    )

    if n < 2:
        return {
            "n": n,
            "mean": mean,
            "sd": 0.0,
            "halfwidth": math.inf,
            "relative": math.inf,
        }

    sd = statistics.stdev(
        values
    )

    alpha = (
        1.0
        - CONFIDENCE_LEVEL
    )

    critical = student_t.ppf(
        1.0 - alpha / 2.0,
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


# ============================================================
# Lifecycle policy
# ============================================================

scheduler = CometScheduler()


def required_backends(
    model,
    policy,
    concurrency,
):

    if policy == "wasmtime_only":
        return {
            "wasmtime"
        }

    if policy == "docker_only":
        return {
            "docker"
        }

    if policy == "random":
        return {
            "wasmtime",
            "docker",
        }

    if policy == "best_static":
        return {
            BEST_STATIC_BACKEND
        }

    if policy == "comet":

        decision = scheduler.schedule(
            model=model,
            concurrency=concurrency,
            tenants=TENANTS,
        )

        if not decision[
            "admitted"
        ]:
            return set()

        return {
            decision[
                "selected_backend"
            ]
        }

    raise ValueError(
        policy
    )


def start_required(
    harness,
    backends,
):
    try:

        if "wasmtime" in backends:
            harness.start_wasmtime()

        if "docker" in backends:
            harness.start_docker()

    except Exception:
        harness.stop()
        raise


# ============================================================
# Run one repetition
# ============================================================

def run_repetition(
    model,
    policy,
    concurrency,
    repetition,
    requests,
):

    backends = required_backends(
        model,
        policy,
        concurrency,
    )

    # A fully rejected COMET scenario can be
    # represented without launching a backend.
    if not backends:

        return {
            "evaluation_type":
                "live_heldout",

            "model":
                model,

            "policy":
                policy,

            "concurrency":
                concurrency,

            "tenants":
                TENANTS,

            "physical_units":
                PHYSICAL_UNITS,

            "requests":
                requests,

            "admitted_requests":
                0,

            "successful_requests":
                0,

            "correct_predictions":
                0,

            "rejected_requests":
                requests,

            "request_errors":
                0,

            "admission_rate":
                0.0,

            "error_rate_among_admitted":
                None,

            "correctness_rate":
                None,

            "backend_distribution":
                {},

            "elapsed_seconds":
                0.0,

            "throughput_rps":
                0.0,

            "mean_latency_ms":
                None,

            "p50_latency_ms":
                None,

            "p95_latency_ms":
                None,

            "p99_latency_ms":
                None,

            "repetition":
                repetition,
        }

    harness = LiveBackendPair(
        model,
        PHYSICAL_UNITS,
    )

    with tempfile.NamedTemporaryFile(
        suffix=".json",
        delete=False,
    ) as tmp:

        output = Path(
            tmp.name
        )

    try:

        start_required(
            harness,
            backends,
        )

        cmd = [
            "taskset",
            "-c",
            CLIENT_CPUSET,

            str(
                ROOT
                / ".venv"
                / "bin"
                / "python"
            ),

            "-m",
            "comet.evaluation.live_client",

            "--model",
            model,

            "--policy",
            policy,

            "--concurrency",
            str(
                concurrency
            ),

            "--tenants",
            str(
                TENANTS
            ),

            "--physical-units",
            str(
                PHYSICAL_UNITS
            ),

            "--requests",
            str(
                requests
            ),

            "--seed",
            str(
                SEED
                + repetition
            ),

            "--static-backend",
            BEST_STATIC_BACKEND,

            "--output",
            str(
                output
            ),
        ]

        proc = subprocess.run(
            cmd,
            cwd=ROOT,
            text=True,
            capture_output=True,
        )

        if proc.returncode != 0:
            raise RuntimeError(
                "Live client failed\n"
                f"STDOUT:\n{proc.stdout}\n"
                f"STDERR:\n{proc.stderr}"
            )

        data = json.loads(
            output.read_text()
        )

        data[
            "repetition"
        ] = repetition

        data[
            "available_backends"
        ] = sorted(
            backends
        )

        return data

    finally:

        harness.stop()

        output.unlink(
            missing_ok=True
        )


# ============================================================
# Persistence
# ============================================================

FIELDS = [
    "model",
    "policy",
    "concurrency",
    "repetition",
    "admission_rate",
    "successful_requests",
    "request_errors",
    "correctness_rate",
    "throughput_rps",
    "mean_latency_ms",
    "p50_latency_ms",
    "p95_latency_ms",
    "p99_latency_ms",
    "mean_scheduler_decision_ns",
]


def append_raw(
    path,
    row,
):

    exists = path.exists()

    with path.open(
        "a",
        newline="",
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=FIELDS,
        )

        if not exists:
            writer.writeheader()

        writer.writerow({
            key: row.get(
                key
            )
            for key in FIELDS
        })


def load_existing(
    path,
):

    if not path.exists():
        return []

    with path.open(
        newline=""
    ) as f:

        return list(
            csv.DictReader(f)
        )


# ============================================================
# Scientific cell
# ============================================================

def run_cell(
    model,
    policy,
    concurrency,
):

    raw_path = (
        RAW_DIR
        / (
            f"{model}__"
            f"{policy}__"
            f"c{concurrency}.csv"
        )
    )

    if args.fresh and raw_path.exists():
        raw_path.unlink()

    existing = load_existing(
        raw_path
    )

    start_rep = (
        len(existing)
        + 1
    )

    if existing:

        p95_values = [
            float(
                x[
                    "p95_latency_ms"
                ]
            )
            for x in existing
            if x[
                "p95_latency_ms"
            ] not in {
                "",
                "None",
                None,
            }
        ]

        throughput_values = [
            float(
                x[
                    "throughput_rps"
                ]
            )
            for x in existing
        ]

    else:
        p95_values = []
        throughput_values = []

    # Smoke is deliberately separate from
    # scientific persistence.
    if args.smoke:

        smoke_rows = []

        for rep in range(
            1,
            4,
        ):

            result = run_repetition(
                model,
                policy,
                concurrency,
                rep,
                500,
            )

            smoke_rows.append(
                result
            )

            print(
                f"SMOKE "
                f"{model:22s} "
                f"{policy:15s} "
                f"C={concurrency:<3d} "
                f"rep={rep} "
                f"admit="
                f"{result['admission_rate']:.3f} "
                f"p95="
                f"{result['p95_latency_ms']} "
                f"rps="
                f"{result['throughput_rps']:.1f}"
            )

            time.sleep(
                COOLDOWN_SECONDS
            )

        return {
            "smoke": True,
            "rows": smoke_rows,
        }

    for rep in range(
        start_rep,
        MAX_REPS + 1,
    ):

        result = run_repetition(
            model,
            policy,
            concurrency,
            rep,
            REQUESTS,
        )

        if (
            result[
                "successful_requests"
            ] > 0
            and
            result[
                "correctness_rate"
            ] != 1.0
        ):
            raise RuntimeError(
                f"Incorrect prediction detected: "
                f"{model} {policy} "
                f"C={concurrency} rep={rep}"
            )

        append_raw(
            raw_path,
            result,
        )

        if (
            result[
                "p95_latency_ms"
            ] is not None
        ):
            p95_values.append(
                float(
                    result[
                        "p95_latency_ms"
                    ]
                )
            )

        throughput_values.append(
            float(
                result[
                    "throughput_rps"
                ]
            )
        )

        p95_ci = (
            ci_stats(
                p95_values
            )
            if p95_values
            else None
        )

        thr_ci = ci_stats(
            throughput_values
        )

        p95_rel = (
            p95_ci[
                "relative"
            ]
            if p95_ci
            else None
        )

        print(
            f"{model:22s} "
            f"{policy:15s} "
            f"C={concurrency:<3d} "
            f"rep={rep:<2d} "
            f"p95="
            f"{result['p95_latency_ms']} "
            f"rps="
            f"{result['throughput_rps']:.1f} "
            f"CI95="
            f"{p95_rel} "
            f"CIRPS="
            f"{thr_ci['relative']}"
        )

        if (
            rep >= MIN_REPS
            and
            p95_ci is not None
            and
            p95_ci[
                "relative"
            ] <= CI_TARGET
            and
            thr_ci[
                "relative"
            ] <= CI_TARGET
        ):
            break

        time.sleep(
            COOLDOWN_SECONDS
        )

    rows = load_existing(
        raw_path
    )

    p95_values = [
        float(
            x[
                "p95_latency_ms"
            ]
        )
        for x in rows
        if x[
            "p95_latency_ms"
        ] not in {
            "",
            "None",
            None,
        }
    ]

    throughput_values = [
        float(
            x[
                "throughput_rps"
            ]
        )
        for x in rows
    ]

    p95_ci = (
        ci_stats(
            p95_values
        )
        if p95_values
        else None
    )

    thr_ci = ci_stats(
        throughput_values
    )

    return {
        "model":
            model,

        "policy":
            policy,

        "concurrency":
            concurrency,

        "repetitions":
            len(rows),

        "p95_latency_ms":
            p95_ci,

        "throughput_rps":
            thr_ci,

        "ci_target_met":
            bool(
                p95_ci is not None
                and
                p95_ci[
                    "relative"
                ] <= CI_TARGET
                and
                thr_ci[
                    "relative"
                ] <= CI_TARGET
            ),
    }


# ============================================================
# Main
# ============================================================

summaries = []

for model in SELECTED_MODELS:

    for policy in SELECTED_POLICIES:

        for concurrency in SELECTED_LEVELS:

            print()
            print(
                "=" * 78
            )

            print(
                f"LIVE HELD-OUT: "
                f"{model} | "
                f"{policy} | "
                f"C={concurrency}"
            )

            print(
                "=" * 78
            )

            summary = run_cell(
                model,
                policy,
                concurrency,
            )

            if not args.smoke:
                summaries.append(
                    summary
                )


if args.smoke:

    print()
    print(
        "LIVE HELD-OUT SMOKE: PASS"
    )

    raise SystemExit(0)


summary_file = (
    PROC_DIR
    / "live_heldout_summary.json"
)

summary_file.write_text(
    json.dumps(
        {
            "schema_version":
                "comet-live-heldout-v1",

            "heldout_concurrencies":
                HELDOUT_CONCURRENCIES,

            "physical_units":
                PHYSICAL_UNITS,

            "tenants":
                TENANTS,

            "requests_per_repetition":
                REQUESTS,

            "min_repetitions":
                MIN_REPS,

            "max_repetitions":
                MAX_REPS,

            "confidence":
                CONFIDENCE_LEVEL,

            "relative_ci_target":
                CI_TARGET,

            "best_static_backend":
                BEST_STATIC_BACKEND,

            "cells":
                summaries,
        },
        indent=2,
    )
    + "\n"
)


print()
print(
    "=" * 78
)

print(
    f"COMPLETED CELLS: "
    f"{len(summaries)}"
)

print(
    "OUTPUT:",
    summary_file
)

print(
    "=" * 78
)
