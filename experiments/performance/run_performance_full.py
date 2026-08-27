#!/usr/bin/env python3

import argparse
import csv
import json
import math
import os
import signal
import statistics
import subprocess
import tempfile
import time
from pathlib import Path
import sys

import pandas as pd
from scipy.stats import t as student_t


ROOT = Path(__file__).resolve().parents[2]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.common.model_registry import get_model

SERVER = (
    ROOT
    / "serving"
    / "multitenant_server"
    / "target"
    / "release"
    / "comet_multitenant_server"
)


LOAD_CLIENT = (
    ROOT
    / "experiments"
    / "performance"
    / "load_client_async.py"
)

RAW_DIR = (
    ROOT
    / "results"
    / "raw"
    / "performance"
)

PROCESSED_DIR = (
    ROOT
    / "results"
    / "processed"
    / "performance"
)

RAW_DIR.mkdir(
    parents=True,
    exist_ok=True
)

PROCESSED_DIR.mkdir(
    parents=True,
    exist_ok=True
)


# ============================================================
# Experiment constants
# ============================================================

CONCURRENCY_LEVELS = [
    1,
    2,
    4,
    8,
    16,
    32,
    64,
    128,
    256,
]

PHYSICAL_UNITS = 20

REQUESTS_PER_REPETITION = 5000

MIN_REPS = 20
MAX_REPS = 60

CONFIDENCE_LEVEL = 0.95

RELATIVE_CI_TARGET = 0.025

COOLDOWN_SECONDS = 1.0

WASMTIME_PORT = 8100

DOCKER_BASE_PORT = 8300



# Server = NUMA node 0 = even CPUs
SERVER_CPUSET = ",".join(
    str(i)
    for i in range(0, 128, 2)
)

# Client = NUMA node 1 = odd CPUs
CLIENT_CPUSET = ",".join(
    str(i)
    for i in range(1, 128, 2)
)


# ============================================================
# CLI
# ============================================================

parser = argparse.ArgumentParser()

parser.add_argument(
    "--backend",
    required=True,
    choices=["wasmtime", "docker"],
)

parser.add_argument(
    "--model",
    required=True,
)

parser.add_argument(
    "--physical-units",
    type=int,
    default=20,
    help=(
        "Number of physical Wasmtime workers / "
        "Docker containers. Default: 20."
    ),
)

parser.add_argument(
    "--levels",
    nargs="*",
    type=int,
    default=None,
)

parser.add_argument(
    "--fresh",
    action="store_true",
)

args = parser.parse_args()

BACKEND = args.backend
MODEL_NAME = args.model

PHYSICAL_UNITS = int(
    args.physical_units
)

if PHYSICAL_UNITS < 1:
    raise SystemExit(
        "--physical-units must be >= 1"
    )

MODEL_CFG = get_model(
    MODEL_NAME
)

WASM = MODEL_CFG["wasm_artifact_abs"]
DOCKER_IMAGE = MODEL_CFG["docker_image"]

DOCKER_PREFIX = (
    f"comet-{MODEL_NAME.replace('_', '-')}-perf"
)

LEVELS = (
    args.levels
    if args.levels
    else CONCURRENCY_LEVELS
)


UNIT_SUFFIX = (
    ""
    if PHYSICAL_UNITS == 20
    else f"_pu{PHYSICAL_UNITS}_diagnostic"
)

RAW_CSV = (
    RAW_DIR
    / (
        f"{BACKEND}_{MODEL_NAME}"
        f"_performance_full{UNIT_SUFFIX}.csv"
    )
)

SUMMARY_JSON = (
    PROCESSED_DIR
    / (
        f"{BACKEND}_{MODEL_NAME}"
        f"_performance_full{UNIT_SUFFIX}_summary.json"
    )
)


# ============================================================
# Generic helpers
# ============================================================

def run(
    cmd,
    check=True,
):
    return subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=check,
    )


def docker_name(index):
    return (
        f"{DOCKER_PREFIX}-{index}"
    )


def docker_port(index):
    return (
        DOCKER_BASE_PORT
        + index
    )


# ============================================================
# CI
# ============================================================

def ci_stats(values):

    n = len(values)

    if n == 0:
        return {
            "n": 0,
            "mean": 0.0,
            "sd": 0.0,
            "halfwidth": math.inf,
            "relative": math.inf,
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
# Wasmtime lifecycle
# ============================================================

def start_wasmtime():

    proc = subprocess.Popen(
        [
            "taskset",
            "-c",
            SERVER_CPUSET,

            str(SERVER),

            MODEL_NAME,

            str(WASM),

            str(PHYSICAL_UNITS),

            str(WASMTIME_PORT),
        ],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )

    deadline = (
        time.time()
        + 20
    )

    import urllib.request

    while time.time() < deadline:

        if proc.poll() is not None:
            raise RuntimeError(
                "Wasmtime server exited."
            )

        try:
            with urllib.request.urlopen(
                "http://127.0.0.1:8100/health",
                timeout=1,
            ) as r:

                if r.status == 200:
                    return proc

        except Exception:
            pass

        time.sleep(0.05)

    proc.kill()

    raise RuntimeError(
        "Wasmtime readiness timeout."
    )


def stop_wasmtime(proc):

    if proc.poll() is not None:
        return

    proc.send_signal(
        signal.SIGTERM
    )

    try:
        proc.wait(
            timeout=5
        )

    except subprocess.TimeoutExpired:

        proc.kill()
        proc.wait()


# ============================================================
# Docker lifecycle
# ============================================================

def docker_cleanup():

    result = run(
        [
            "docker",
            "ps",
            "-aq",
            "--filter",
            f"name={DOCKER_PREFIX}-",
        ],
        check=False,
    )

    ids = [
        x.strip()
        for x in result.stdout.splitlines()
        if x.strip()
    ]

    if ids:
        run(
            [
                "docker",
                "rm",
                "-f",
                *ids
            ],
            check=False,
        )


def start_docker():

    docker_cleanup()

    for i in range(
        PHYSICAL_UNITS
    ):

        result = run(
            [
                "docker",
                "run",
                "-d",
                "--rm",

                "--cpuset-cpus",
                SERVER_CPUSET,

                "--name",
                docker_name(i),

                "-p",
                f"{docker_port(i)}:8085",

                DOCKER_IMAGE,
            ],
            check=False,
        )

        if result.returncode != 0:
            docker_cleanup()

            raise RuntimeError(
                result.stderr
            )

    # readiness test
    import urllib.request

    deadline = (
        time.time()
        + 30
    )

    pending = set(
        range(
            PHYSICAL_UNITS
        )
    )

    while (
        pending
        and time.time() < deadline
    ):

        done = []

        for i in pending:

            try:

                body = json.dumps({
                    "features": [0.0] * int(
                        MODEL_CFG["features"]
                    )
                }).encode()

                req = urllib.request.Request(
                    f"http://127.0.0.1:"
                    f"{docker_port(i)}/infer",

                    data=body,

                    headers={
                        "Content-Type":
                            "application/json"
                    },

                    method="POST",
                )

                with urllib.request.urlopen(
                    req,
                    timeout=1,
                ) as r:

                    if r.status == 200:
                        done.append(i)

            except Exception:
                pass

        for i in done:
            pending.remove(i)

        if pending:
            time.sleep(0.05)

    if pending:
        docker_cleanup()

        raise RuntimeError(
            "Docker readiness timeout."
        )


# ============================================================
# One load repetition
# ============================================================

def run_load(
    backend,
    concurrency,
):

    with tempfile.NamedTemporaryFile(
        suffix=".json",
        delete=False,
    ) as tmp:

        output = tmp.name

    try:

        result = run(
            [
                "taskset",
                "-c",
                CLIENT_CPUSET,

                str(
                    ROOT
                    / ".venv"
                    / "bin"
                    / "python"
                ),

                str(
                    LOAD_CLIENT
                ),

                "--backend",
                backend,

                "--model",
                MODEL_NAME,

                "--physical-units",
                str(
                    PHYSICAL_UNITS
                ),

                "--concurrency",
                str(
                    concurrency
                ),

                "--requests",
                str(
                    REQUESTS_PER_REPETITION
                ),

                "--output",
                output,
            ],
            check=False,
        )

        if result.returncode != 0:

            raise RuntimeError(
                "Load generator failed:\n"
                + result.stdout
                + "\n"
                + result.stderr
            )

        data = json.loads(
            Path(output)
            .read_text()
        )

        return data

    finally:

        Path(output).unlink(
            missing_ok=True
        )


# ============================================================
# Persistence
# ============================================================

FIELDS = [
    "backend",
    "model",
    "physical_units",
    "concurrency",
    "repetition",
    "requests",
    "throughput_rps",
    "mean_latency_ms",
    "p50_latency_ms",
    "p90_latency_ms",
    "p95_latency_ms",
    "p99_latency_ms",
    "max_latency_ms",
    "error_rate",
    "timestamp_unix",
]


def load_existing():

    if (
        args.fresh
        and RAW_CSV.exists()
    ):
        RAW_CSV.unlink()

    if not RAW_CSV.exists():
        return []

    with RAW_CSV.open() as f:

        return list(
            csv.DictReader(f)
        )


def append_raw(row):

    exists = (
        RAW_CSV.exists()
    )

    with RAW_CSV.open(
        "a",
        newline="",
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=FIELDS,
        )

        if not exists:
            writer.writeheader()

        writer.writerow(
            row
        )


existing = load_existing()


# ============================================================
# Backend lifecycle per repetition
# ============================================================

def run_clean_repetition(
    backend,
    concurrency,
):

    wasmtime_proc = None

    try:

        if backend == "wasmtime":

            wasmtime_proc = start_wasmtime()

        else:

            start_docker()

        # Backend warm-up before measured load.
        warm_output = run_load(
            backend,
            min(concurrency, 16),
        )

        if int(warm_output["errors"]) != 0:

            raise RuntimeError(
                "Backend warm-up produced errors."
            )

        data = run_load(
            backend,
            concurrency,
        )

        return data

    finally:

        if wasmtime_proc is not None:

            stop_wasmtime(
                wasmtime_proc
            )

        if backend == "docker":

            docker_cleanup()

        time.sleep(
            COOLDOWN_SECONDS
        )


# ============================================================
# Experiment
# ============================================================

final_summary = {}

try:

    for concurrency in LEVELS:

        print()
        print(
            "=" * 72
        )

        print(
            f"CONCURRENCY = {concurrency}"
        )

        print(
            "=" * 72
        )

        previous = [
            r
            for r in existing
            if (
                r["backend"]
                == BACKEND
                and int(
                    r["concurrency"]
                ) == concurrency
            )
        ]

        throughput_values = [
            float(
                r[
                    "throughput_rps"
                ]
            )
            for r in previous
        ]

        p95_values = [
            float(
                r[
                    "p95_latency_ms"
                ]
            )
            for r in previous
        ]

        p99_values = [
            float(
                r[
                    "p99_latency_ms"
                ]
            )
            for r in previous
        ]

        repetition = (
            max(
                [
                    int(
                        r["repetition"]
                    )
                    for r in previous
                ],
                default=0,
            )
            + 1
        )

        if previous:

            print(
                f"Resuming with "
                f"{len(previous)} "
                "existing repetitions."
            )

        while True:

            t_stats = ci_stats(
                throughput_values
            )

            p95_stats = ci_stats(
                p95_values
            )

            p99_stats = ci_stats(
                p99_values
            )

            target_met = (
                len(
                    throughput_values
                ) >= MIN_REPS
                and t_stats[
                    "relative"
                ] <= RELATIVE_CI_TARGET
                and p95_stats[
                    "relative"
                ] <= RELATIVE_CI_TARGET
                and p99_stats[
                    "relative"
                ] <= RELATIVE_CI_TARGET
            )

            if target_met:

                print(
                    "CI targets satisfied."
                )

                break

            if len(
                throughput_values
            ) >= MAX_REPS:

                print(
                    "Maximum repetitions reached."
                )

                break

            data = run_clean_repetition(
                BACKEND,
                concurrency,
            )

            if (
                int(
                    data["errors"]
                ) != 0
            ):
                print(
                    "WARNING: errors observed:",
                    data["errors"],
                )

            row = {
                "backend":
                    BACKEND,

                "model":
                    MODEL_NAME,

                "physical_units":
                    PHYSICAL_UNITS,

                "concurrency":
                    concurrency,

                "repetition":
                    repetition,

                "requests":
                    REQUESTS_PER_REPETITION,

                "throughput_rps":
                    f"{data['throughput_rps']:.9f}",

                "mean_latency_ms":
                    f"{data['mean_latency_ms']:.9f}",

                "p50_latency_ms":
                    f"{data['p50_latency_ms']:.9f}",

                "p90_latency_ms":
                    f"{data['p90_latency_ms']:.9f}",

                "p95_latency_ms":
                    f"{data['p95_latency_ms']:.9f}",

                "p99_latency_ms":
                    f"{data['p99_latency_ms']:.9f}",

                "max_latency_ms":
                    f"{data['max_latency_ms']:.9f}",

                "error_rate":
                    f"{data['error_rate']:.9f}",

                "timestamp_unix":
                    f"{time.time():.6f}",
            }

            append_raw(
                row
            )

            throughput_values.append(
                data[
                    "throughput_rps"
                ]
            )

            p95_values.append(
                data[
                    "p95_latency_ms"
                ]
            )

            p99_values.append(
                data[
                    "p99_latency_ms"
                ]
            )

            t_stats = ci_stats(
                throughput_values
            )

            p95_stats = ci_stats(
                p95_values
            )

            p99_stats = ci_stats(
                p99_values
            )

            print(
                f"rep={repetition:02d} | "
                f"RPS={data['throughput_rps']:.1f} | "
                f"P95={data['p95_latency_ms']:.3f} ms | "
                f"P99={data['p99_latency_ms']:.3f} ms | "
                f"CI RPS={t_stats['relative']*100:.2f}% | "
                f"CI P95={p95_stats['relative']*100:.2f}% | "
                f"CI P99={p99_stats['relative']*100:.2f}%"
            )

            repetition += 1


        final_summary[
            str(
                concurrency
            )
        ] = {
            "concurrency":
                concurrency,

            "repetitions":
                len(
                    throughput_values
                ),

            "throughput":
                ci_stats(
                    throughput_values
                ),

            "p95":
                ci_stats(
                    p95_values
                ),

            "p99":
                ci_stats(
                    p99_values
                ),

            "ci_target_met":
                bool(
                    len(
                        throughput_values
                    )
                    >= MIN_REPS
                    and ci_stats(
                        throughput_values
                    )["relative"]
                    <= RELATIVE_CI_TARGET
                    and ci_stats(
                        p95_values
                    )["relative"]
                    <= RELATIVE_CI_TARGET
                    and ci_stats(
                        p99_values
                    )["relative"]
                    <= RELATIVE_CI_TARGET
                ),
        }


        SUMMARY_JSON.write_text(
            json.dumps(
                {
                    "backend":
                        BACKEND,

                    "model":
                        MODEL_NAME,

                    "physical_units":
                        PHYSICAL_UNITS,

                    "requests_per_repetition":
                        REQUESTS_PER_REPETITION,

                    "confidence_level":
                        CONFIDENCE_LEVEL,

                    "relative_ci_target":
                        RELATIVE_CI_TARGET,

                    "summary":
                        final_summary,
                },

                indent=2,
            )
        )


finally:

    docker_cleanup()


print()
print(
    "=" * 72
)

print(
    "FULL PERFORMANCE SUMMARY"
)

print(
    "=" * 72
)


for level in LEVELS:

    s = final_summary[
        str(level)
    ]

    print(
        f"C={level:>3} | "
        f"n={s['repetitions']:>2} | "
        f"RPS={s['throughput']['mean']:.1f} | "
        f"P95={s['p95']['mean']:.3f} ms | "
        f"P99={s['p99']['mean']:.3f} ms | "
        f"{'PASS' if s['ci_target_met'] else 'MAX-REPS'}"
    )


print()

print(
    "Raw CSV:",
    RAW_CSV
)

print(
    "Summary JSON:",
    SUMMARY_JSON
)

print()

print(
    "FULL PERFORMANCE EXPERIMENT: COMPLETE"
)
