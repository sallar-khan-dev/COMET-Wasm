#!/usr/bin/env python3

import argparse
import csv
import json
import math
import signal
import statistics
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from scipy.stats import t as student_t


# ============================================================
# Paths / imports
# ============================================================

ROOT = Path(__file__).resolve().parents[2]

sys.path.insert(
    0,
    str(ROOT)
)

from experiments.common.model_registry import (
    get_model,
    supported_models,
)


SERVER = (
    ROOT
    / "serving"
    / "multitenant_server"
    / "target"
    / "release"
    / "comet_multitenant_server"
)

RAW_DIR = ROOT / "results/raw/execution_time"
PROCESSED_DIR = ROOT / "results/processed/execution_time"

RAW_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# Experimental protocol
# ============================================================

WARMUP_REQUESTS = 1000
REQUESTS_PER_REPETITION = 5000

MIN_REPS = 20
MAX_REPS = 60

CONFIDENCE_LEVEL = 0.95
RELATIVE_CI_TARGET = 0.025

COOLDOWN_SECONDS = 1.0

WASMTIME_PORT = 8100
DOCKER_PORT = 8300

# Keep server placement consistent with performance campaign.
SERVER_CPUSET = ",".join(
    str(i)
    for i in range(0, 128, 2)
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
    choices=supported_models(),
)

parser.add_argument(
    "--fresh",
    action="store_true",
)

args = parser.parse_args()

BACKEND = args.backend
MODEL_NAME = args.model

MODEL_CFG = get_model(MODEL_NAME)

WASM = MODEL_CFG["wasm_artifact_abs"]
DOCKER_IMAGE = MODEL_CFG["docker_image"]

DOCKER_NAME = (
    f"comet-{MODEL_NAME.replace('_', '-')}-execution"
)

RAW_CSV = (
    RAW_DIR
    / f"{BACKEND}_{MODEL_NAME}_execution_time_full.csv"
)

SUMMARY_JSON = (
    PROCESSED_DIR
    / f"{BACKEND}_{MODEL_NAME}_execution_time_full_summary.json"
)


# ============================================================
# Statistics
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

    mean = statistics.mean(values)

    if n < 2:
        return {
            "n": n,
            "mean": mean,
            "sd": 0.0,
            "halfwidth": math.inf,
            "relative": math.inf,
        }

    sd = statistics.stdev(values)

    alpha = 1.0 - CONFIDENCE_LEVEL

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
# Test samples
# ============================================================

def load_test_samples():

    path = MODEL_CFG["test_path_abs"]

    if not path.exists():
        raise RuntimeError(
            f"Test dataset not found: {path}"
        )

    expected_features = int(
        MODEL_CFG["features"]
    )

    samples = []

    with path.open(
        newline=""
    ) as f:

        reader = csv.DictReader(f)

        if not reader.fieldnames:
            raise RuntimeError(
                f"CSV has no header: {path}"
            )

        excluded = {
            "label",
            "target",
            "class",
            "y",
            "expected",
            "prediction",
        }

        feature_columns = [
            name
            for name in reader.fieldnames
            if name.lower() not in excluded
        ]

        if len(feature_columns) != expected_features:
            raise RuntimeError(
                f"{MODEL_NAME}: expected "
                f"{expected_features} feature columns, "
                f"found {len(feature_columns)}: "
                f"{feature_columns}"
            )

        for row in reader:

            features = [
                float(row[col])
                for col in feature_columns
            ]

            samples.append(features)

    if not samples:
        raise RuntimeError(
            f"No valid samples found in {path}"
        )

    return samples


# ============================================================
# HTTP request
# ============================================================

def infer(
    url,
    features,
    tenant_id=None,
):

    payload = {
        "features": features
    }

    if tenant_id is not None:
        payload["tenant_id"] = int(
            tenant_id
        )

    body = json.dumps(
        payload
    ).encode()

    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type":
                "application/json"
        },
        method="POST",
    )

    with urllib.request.urlopen(
        req,
        timeout=5,
    ) as r:

        result = json.loads(
            r.read().decode()
        )

    for field in [
        "execution_time_ns",
        "inference_time_ns",
    ]:
        if field not in result:
            raise RuntimeError(
                f"Response does not contain {field}"
            )

    if int(result["execution_time_ns"]) <= 0:
        raise RuntimeError(
            "execution_time_ns must be > 0"
        )

    return result


# ============================================================
# Backend lifecycle
# ============================================================

def start_wasmtime():

    # Remove any stale COMET-Wasm server from a previous
    # interrupted repetition. Otherwise the readiness probe
    # could connect to the wrong model on port 8100.
    subprocess.run(
        [
            "pkill",
            "-f",
            str(SERVER),
        ],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )

    time.sleep(0.2)

    proc = subprocess.Popen(
        [
            "taskset",
            "-c",
            SERVER_CPUSET,

            str(SERVER),

            MODEL_NAME,
            str(WASM),

            "1",
            str(WASMTIME_PORT),
        ],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )

    deadline = time.time() + 20

    while time.time() < deadline:

        if proc.poll() is not None:
            raise RuntimeError(
                "Wasmtime server exited."
            )

        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{WASMTIME_PORT}/health",
                timeout=1,
            ) as r:

                if r.status != 200:
                    continue

            with urllib.request.urlopen(
                f"http://127.0.0.1:{WASMTIME_PORT}/metadata",
                timeout=1,
            ) as r:

                metadata = json.loads(
                    r.read().decode()
                )

            if (
                metadata.get("model")
                == MODEL_NAME
                and int(
                    metadata.get("workers", 0)
                ) == 1
            ):
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

    proc.send_signal(signal.SIGTERM)

    try:
        proc.wait(timeout=5)

    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def docker_cleanup():

    subprocess.run(
        [
            "docker",
            "rm",
            "-f",
            DOCKER_NAME,
        ],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def start_docker():

    docker_cleanup()

    result = subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--rm",

            "--cpuset-cpus",
            SERVER_CPUSET,

            "--name",
            DOCKER_NAME,

            "-p",
            f"{DOCKER_PORT}:8085",

            DOCKER_IMAGE,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            result.stderr
        )

    deadline = time.time() + 30

    zero_sample = [
        0.0
    ] * int(MODEL_CFG["features"])

    while time.time() < deadline:

        try:
            infer(
                f"http://127.0.0.1:{DOCKER_PORT}/infer",
                zero_sample,
            )

            return

        except Exception:
            pass

        time.sleep(0.05)

    docker_cleanup()

    raise RuntimeError(
        "Docker readiness timeout."
    )


# ============================================================
# One clean repetition
# ============================================================

def run_repetition(samples):

    proc = None

    try:

        if BACKEND == "wasmtime":

            proc = start_wasmtime()

            url = (
                f"http://127.0.0.1:"
                f"{WASMTIME_PORT}/infer"
            )

            tenant_id = 0

        else:

            start_docker()

            url = (
                f"http://127.0.0.1:"
                f"{DOCKER_PORT}/infer"
            )

            tenant_id = None

        # --------------------------------------------
        # Warm-up
        # --------------------------------------------

        for i in range(
            WARMUP_REQUESTS
        ):

            sample = samples[
                i % len(samples)
            ]

            infer(
                url,
                sample,
                tenant_id=tenant_id,
            )

        # --------------------------------------------
        # Measurement
        # --------------------------------------------

        execution_values = []
        inference_values = []

        for i in range(
            REQUESTS_PER_REPETITION
        ):

            sample = samples[
                i % len(samples)
            ]

            result = infer(
                url,
                sample,
                tenant_id=tenant_id,
            )

            execution_values.append(
                int(
                    result[
                        "execution_time_ns"
                    ]
                )
            )

            inference_values.append(
                int(
                    result[
                        "inference_time_ns"
                    ]
                )
            )

        execution_sorted = sorted(
            execution_values
        )

        n = len(
            execution_sorted
        )

        p95_index = int(
            0.95 * (n - 1)
        )

        p99_index = int(
            0.99 * (n - 1)
        )

        return {
            "execution_mean_ns":
                statistics.mean(
                    execution_values
                ),

            "execution_median_ns":
                statistics.median(
                    execution_values
                ),

            "execution_p95_ns":
                execution_sorted[
                    p95_index
                ],

            "execution_p99_ns":
                execution_sorted[
                    p99_index
                ],

            "inference_mean_ns":
                statistics.mean(
                    inference_values
                ),
        }

    finally:

        if proc is not None:
            stop_wasmtime(proc)

        if BACKEND == "docker":
            docker_cleanup()

        time.sleep(
            COOLDOWN_SECONDS
        )


# ============================================================
# Raw storage
# ============================================================

FIELDS = [
    "backend",
    "model",
    "repetition",
    "requests",
    "execution_mean_ns",
    "execution_median_ns",
    "execution_p95_ns",
    "execution_p99_ns",
    "inference_mean_ns",
    "timestamp_unix",
]


if args.fresh and RAW_CSV.exists():
    RAW_CSV.unlink()


existing = []

if RAW_CSV.exists():

    with RAW_CSV.open() as f:
        existing = list(
            csv.DictReader(f)
        )


def append_raw(row):

    exists = RAW_CSV.exists()

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

        writer.writerow(row)


# ============================================================
# Experiment
# ============================================================

samples = load_test_samples()

print()
print("=" * 76)
print("COMET-Wasm EXECUTION-TIME EXPERIMENT")
print("=" * 76)
print(f"Backend: {BACKEND}")
print(f"Model: {MODEL_NAME}")
print(f"Test samples: {len(samples)}")
print(f"Warm-up requests: {WARMUP_REQUESTS}")
print(f"Measured requests/repetition: {REQUESTS_PER_REPETITION}")
print(f"Minimum repetitions: {MIN_REPS}")
print(f"Maximum repetitions: {MAX_REPS}")
print("Relative 95% CI target: 2.50%")
print(f"Raw CSV: {RAW_CSV}")
print()


values = [
    float(r["execution_mean_ns"])
    for r in existing
]

existing_stats = ci_stats(values)

already_converged = (
    len(existing) >= MIN_REPS
    and existing_stats["relative"]
        <= RELATIVE_CI_TARGET
)

if already_converged:
    print(
        f"Existing dataset already satisfies CI target: "
        f"n={len(existing)}, "
        f"relative CI="
        f"{existing_stats['relative'] * 100:.3f}%"
    )


for repetition in (
    []
    if already_converged
    else range(
        len(existing) + 1,
        MAX_REPS + 1,
    )
):

    result = run_repetition(
        samples
    )

    row = {
        "backend": BACKEND,
        "model": MODEL_NAME,
        "repetition": repetition,
        "requests":
            REQUESTS_PER_REPETITION,
        **result,
        "timestamp_unix":
            time.time(),
    }

    append_raw(row)

    values.append(
        float(
            result[
                "execution_mean_ns"
            ]
        )
    )

    stats = ci_stats(
        values
    )

    print(
        f"rep={repetition:02d} | "
        f"exec={result['execution_mean_ns']:.1f} ns | "
        f"median={result['execution_median_ns']:.1f} ns | "
        f"P95={result['execution_p95_ns']:.1f} ns | "
        f"P99={result['execution_p99_ns']:.1f} ns | "
        f"CI={stats['relative'] * 100:.3f}%"
    )

    if (
        repetition >= MIN_REPS
        and stats["relative"]
        <= RELATIVE_CI_TARGET
    ):

        print(
            "CI target satisfied."
        )

        break


# ============================================================
# Final summary
# ============================================================

with RAW_CSV.open() as f:

    rows = list(
        csv.DictReader(f)
    )


execution_means = [
    float(
        r["execution_mean_ns"]
    )
    for r in rows
]

execution_medians = [
    float(
        r["execution_median_ns"]
    )
    for r in rows
]

execution_p95 = [
    float(
        r["execution_p95_ns"]
    )
    for r in rows
]

execution_p99 = [
    float(
        r["execution_p99_ns"]
    )
    for r in rows
]

inference_means = [
    float(
        r["inference_mean_ns"]
    )
    for r in rows
]

stats = ci_stats(
    execution_means
)


summary = {
    "backend": BACKEND,
    "model": MODEL_NAME,

    "test_samples":
        len(samples),

    "warmup_requests":
        WARMUP_REQUESTS,

    "requests_per_repetition":
        REQUESTS_PER_REPETITION,

    "repetitions":
        len(rows),

    "total_measured_requests":
        len(rows)
        * REQUESTS_PER_REPETITION,

    "execution_mean_ns":
        statistics.mean(
            execution_means
        ),

    "execution_median_of_medians_ns":
        statistics.median(
            execution_medians
        ),

    "execution_mean_p95_ns":
        statistics.mean(
            execution_p95
        ),

    "execution_mean_p99_ns":
        statistics.mean(
            execution_p99
        ),

    "inference_mean_ns":
        statistics.mean(
            inference_means
        ),

    "execution_95ci_halfwidth_ns":
        stats["halfwidth"],

    "execution_relative_95ci":
        stats["relative"],

    "ci_target_pass":
        bool(
            stats["relative"]
            <= RELATIVE_CI_TARGET
        ),
}


SUMMARY_JSON.write_text(
    json.dumps(
        summary,
        indent=2,
    )
)


print()
print("=" * 76)
print("EXECUTION-TIME SUMMARY")
print("=" * 76)

print(
    f"n={len(rows)} repetitions"
)

print(
    f"Mean execution time: "
    f"{summary['execution_mean_ns']:.2f} ns "
    f"({summary['execution_mean_ns']/1000:.4f} us)"
)

print(
    f"Median execution time: "
    f"{summary['execution_median_of_medians_ns']:.2f} ns"
)

print(
    f"Mean P95 execution time: "
    f"{summary['execution_mean_p95_ns']:.2f} ns"
)

print(
    f"Mean P99 execution time: "
    f"{summary['execution_mean_p99_ns']:.2f} ns"
)

print(
    f"95% CI: ±"
    f"{summary['execution_95ci_halfwidth_ns']:.2f} ns"
)

print(
    f"Relative CI: "
    f"{summary['execution_relative_95ci']*100:.3f}%"
)

print()
print(f"Raw CSV: {RAW_CSV}")
print(f"Summary JSON: {SUMMARY_JSON}")

print()
print(
    "EXECUTION-TIME EXPERIMENT: COMPLETE"
)
