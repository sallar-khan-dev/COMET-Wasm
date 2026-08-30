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
# Paths / registry
# ============================================================

ROOT = Path(__file__).resolve().parents[2]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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

RAW_DIR = (
    ROOT
    / "results"
    / "raw"
    / "cold_start"
)

PROC_DIR = (
    ROOT
    / "results"
    / "processed"
    / "cold_start"
)

RAW_DIR.mkdir(
    parents=True,
    exist_ok=True
)

PROC_DIR.mkdir(
    parents=True,
    exist_ok=True
)


# ============================================================
# Protocol
# ============================================================

MIN_REPS = 20
MAX_REPS = 60

CI_TARGET = 0.025

COOLDOWN_SECONDS = 1.0

WASMTIME_PORT = 8100
DOCKER_PORT = 8400

WARM_REQUESTS = 20


# ============================================================
# CLI
# ============================================================

parser = argparse.ArgumentParser()

parser.add_argument(
    "--backend",
    required=True,
    choices=[
        "wasmtime",
        "docker",
    ],
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

MODEL = get_model(
    MODEL_NAME
)

WASM = MODEL[
    "wasm_artifact_abs"
]

DATA = MODEL[
    "test_path_abs"
]

MODEL_PATH = MODEL[
    "model_path_abs"
]

DOCKER_IMAGE = MODEL[
    "docker_image"
]

DOCKER_NAME = (
    "comet-coldstart-"
    + MODEL_NAME.replace(
        "_",
        "-",
    )
)


RAW_CSV = (
    RAW_DIR
    / (
        f"{BACKEND}_{MODEL_NAME}_"
        "cold_start_full.csv"
    )
)

SUMMARY_JSON = (
    PROC_DIR
    / (
        f"{BACKEND}_{MODEL_NAME}_"
        "cold_start_full_summary.json"
    )
)


# ============================================================
# Test sample / expected prediction
# ============================================================

with DATA.open(
    newline="",
) as f:

    row = next(
        csv.DictReader(f)
    )


FEATURES = [
    float(value)
    for key, value in row.items()
    if key.lower() not in {
        "label",
        "target",
        "class",
        "y",
        "expected",
        "prediction",
    }
]


if len(FEATURES) != int(
    MODEL["features"]
):

    raise RuntimeError(
        f"{MODEL_NAME}: "
        f"feature-count mismatch. "
        f"Registry={MODEL['features']}, "
        f"sample={len(FEATURES)}"
    )


# ------------------------------------------------------------
# Expected result
#
# For supervised models, use the CSV label.
# For K-Means, calculate the nearest exported centroid so that
# correctness does not depend on arbitrary cluster-label order.
# ------------------------------------------------------------

if MODEL["task"] == "clustering_inference":

    model_data = json.loads(
        MODEL_PATH.read_text()
    )

    centroids = model_data[
        "centroids"
    ]

    best_cluster = 0
    best_distance = float(
        "inf"
    )

    for cluster_id, centroid in enumerate(
        centroids
    ):

        distance = sum(
            (x - mu) ** 2
            for x, mu in zip(
                FEATURES,
                centroid,
            )
        )

        if distance < best_distance:

            best_distance = distance
            best_cluster = cluster_id

    EXPECTED = best_cluster

else:

    EXPECTED = int(
        row["label"]
    )


# ============================================================
# Statistics
# ============================================================

def ci(values):

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
        halfwidth
        / abs(mean)
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
# Inference request
# ============================================================

def make_request(
    url,
    wasmtime,
):

    body = (
        {
            "tenant_id": 0,
            "features": FEATURES,
        }
        if wasmtime
        else {
            "features": FEATURES,
        }
    )


    req = urllib.request.Request(
        url,
        data=json.dumps(
            body
        ).encode(),
        headers={
            "Content-Type":
                "application/json"
        },
        method="POST",
    )


    t0 = (
        time.perf_counter_ns()
    )


    with urllib.request.urlopen(
        req,
        timeout=5,
    ) as r:

        payload = json.loads(
            r.read()
        )


    t1 = (
        time.perf_counter_ns()
    )


    prediction = int(
        payload["prediction"]
    )


    if prediction != EXPECTED:

        raise RuntimeError(
            f"Incorrect prediction: "
            f"expected={EXPECTED}, "
            f"received={prediction}"
        )


    return (
        t1 - t0
    ) / 1_000_000.0


# ============================================================
# Cleanup
# ============================================================

def cleanup_wasmtime():

    subprocess.run(
        [
            "pkill",
            "-f",
            str(SERVER),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def cleanup_docker():

    subprocess.run(
        [
            "docker",
            "rm",
            "-f",
            DOCKER_NAME,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


# ============================================================
# Wasmtime cold start
# ============================================================

def measure_wasmtime():

    cleanup_wasmtime()

    time.sleep(
        0.1
    )


    start_ns = (
        time.perf_counter_ns()
    )


    proc = subprocess.Popen(
        [
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


    try:

        deadline = (
            time.time()
            + 20
        )


        while True:

            if proc.poll() is not None:

                raise RuntimeError(
                    "Wasmtime exited "
                    "before readiness."
                )


            try:

                with urllib.request.urlopen(
                    (
                        "http://127.0.0.1:"
                        f"{WASMTIME_PORT}/health"
                    ),
                    timeout=0.1,
                ) as r:

                    if r.status == 200:
                        break

            except Exception:
                pass


            if time.time() > deadline:

                raise RuntimeError(
                    "Wasmtime readiness timeout."
                )


            time.sleep(
                0.002
            )


        ready_ns = (
            time.perf_counter_ns()
        )


        first_ms = make_request(
            (
                "http://127.0.0.1:"
                f"{WASMTIME_PORT}/infer"
            ),
            True,
        )


        first_done_ns = (
            time.perf_counter_ns()
        )


        warm = []

        for _ in range(
            WARM_REQUESTS
        ):

            warm.append(
                make_request(
                    (
                        "http://127.0.0.1:"
                        f"{WASMTIME_PORT}/infer"
                    ),
                    True,
                )
            )


        return {

            "startup_ms":
                (
                    ready_ns
                    - start_ns
                )
                / 1_000_000.0,

            "first_inference_ms":
                first_ms,

            "cold_to_first_result_ms":
                (
                    first_done_ns
                    - start_ns
                )
                / 1_000_000.0,

            "warm_inference_ms":
                statistics.mean(
                    warm
                ),
        }


    finally:

        if proc.poll() is None:

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
# Docker cold start
# ============================================================

def measure_docker():

    cleanup_docker()

    time.sleep(
        0.1
    )


    start_ns = (
        time.perf_counter_ns()
    )


    result = subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--rm",

            "--name",
            DOCKER_NAME,

            "-p",
            f"{DOCKER_PORT}:8085",

            DOCKER_IMAGE,
        ],
        text=True,
        capture_output=True,
    )


    if result.returncode != 0:

        raise RuntimeError(
            result.stderr
        )


    try:

        # ----------------------------------------------------
        # Application-level readiness.
        #
        # Do not probe /infer because that would consume the
        # first cold inference request. Instead wait until the
        # application itself reports its listening state.
        # Every current COMET Docker server emits a line
        # containing:
        #
        #       "server listening on http://"
        #
        # ----------------------------------------------------

        deadline = (
            time.time()
            + 30
        )


        ready_marker = (
            "server listening on http://"
        )


        while True:

            logs = subprocess.run(
                [
                    "docker",
                    "logs",
                    DOCKER_NAME,
                ],
                text=True,
                capture_output=True,
            )


            combined = (
                logs.stdout
                + "\n"
                + logs.stderr
            )


            if (
                ready_marker.lower()
                in combined.lower()
            ):
                break


            container_alive = subprocess.run(
                [
                    "docker",
                    "inspect",
                    "-f",
                    "{{.State.Running}}",
                    DOCKER_NAME,
                ],
                text=True,
                capture_output=True,
            )


            if (
                container_alive.returncode != 0
                or
                container_alive.stdout.strip()
                != "true"
            ):

                raise RuntimeError(
                    "Docker container exited "
                    "before readiness.\n"
                    + combined
                )


            if time.time() > deadline:

                raise RuntimeError(
                    "Docker application "
                    "readiness timeout.\n"
                    + combined
                )


            time.sleep(
                0.002
            )


        ready_ns = (
            time.perf_counter_ns()
        )


        first_ms = make_request(
            (
                "http://127.0.0.1:"
                f"{DOCKER_PORT}/infer"
            ),
            False,
        )


        first_done_ns = (
            time.perf_counter_ns()
        )


        warm = []

        for _ in range(
            WARM_REQUESTS
        ):

            warm.append(
                make_request(
                    (
                        "http://127.0.0.1:"
                        f"{DOCKER_PORT}/infer"
                    ),
                    False,
                )
            )


        return {

            "startup_ms":
                (
                    ready_ns
                    - start_ns
                )
                / 1_000_000.0,

            "first_inference_ms":
                first_ms,

            "cold_to_first_result_ms":
                (
                    first_done_ns
                    - start_ns
                )
                / 1_000_000.0,

            "warm_inference_ms":
                statistics.mean(
                    warm
                ),
        }


    finally:

        cleanup_docker()


# ============================================================
# Persistence
# ============================================================

FIELDS = [
    "backend",
    "model",
    "repetition",
    "startup_ms",
    "first_inference_ms",
    "cold_to_first_result_ms",
    "warm_inference_ms",
    "timestamp_unix",
]


if args.fresh:

    if RAW_CSV.exists():
        RAW_CSV.unlink()

    if SUMMARY_JSON.exists():
        SUMMARY_JSON.unlink()


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

        writer.writerow(
            row
        )


# ============================================================
# Main experiment
# ============================================================

measurements = [
    {
        "startup_ms":
            float(r["startup_ms"]),

        "first_inference_ms":
            float(r["first_inference_ms"]),

        "cold_to_first_result_ms":
            float(r["cold_to_first_result_ms"]),

        "warm_inference_ms":
            float(r["warm_inference_ms"]),
    }

    for r in existing
]


print()
print("=" * 78)
print(
    "COMET-Wasm UNIFIED COLD-START EXPERIMENT"
)
print("=" * 78)

print(
    f"Backend: {BACKEND}"
)

print(
    f"Model: {MODEL_NAME}"
)

print(
    f"Dataset: {MODEL['dataset']}"
)

print(
    f"Workload class: "
    f"{MODEL['workload_class']}"
)

print(
    f"Features: {MODEL['features']}"
)

print(
    f"Minimum repetitions: {MIN_REPS}"
)

print(
    f"Maximum repetitions: {MAX_REPS}"
)

print(
    "Primary relative 95% CI target: 2.50%"
)

print(
    "Primary stopping metrics: "
    "startup + cold-to-first-result"
)

print(
    f"Warm requests/repetition: "
    f"{WARM_REQUESTS}"
)

print(
    f"Raw CSV: {RAW_CSV}"
)

print()


# ============================================================
# Resume check
# ============================================================

startup_existing = ci(
    [
        x["startup_ms"]
        for x in measurements
    ]
)

cold_existing = ci(
    [
        x["cold_to_first_result_ms"]
        for x in measurements
    ]
)


already_done = (
    len(measurements) >= MIN_REPS
    and
    startup_existing[
        "relative"
    ] <= CI_TARGET
    and
    cold_existing[
        "relative"
    ] <= CI_TARGET
)


if already_done:

    print(
        "Existing dataset already satisfies "
        "primary CI targets."
    )


# ============================================================
# Repetitions
# ============================================================

for rep in (
    []
    if already_done
    else range(
        len(measurements) + 1,
        MAX_REPS + 1,
    )
):

    data = (
        measure_wasmtime()
        if BACKEND == "wasmtime"
        else measure_docker()
    )


    measurements.append(
        data
    )


    append_raw({

        "backend":
            BACKEND,

        "model":
            MODEL_NAME,

        "repetition":
            rep,

        **data,

        "timestamp_unix":
            time.time(),
    })


    startup = ci(
        [
            x["startup_ms"]
            for x in measurements
        ]
    )

    cold = ci(
        [
            x["cold_to_first_result_ms"]
            for x in measurements
        ]
    )

    first = ci(
        [
            x["first_inference_ms"]
            for x in measurements
        ]
    )

    warm_ci = ci(
        [
            x["warm_inference_ms"]
            for x in measurements
        ]
    )


    print(
        f"rep={rep:02d} | "
        f"startup={data['startup_ms']:.3f} ms | "
        f"first={data['first_inference_ms']:.3f} ms | "
        f"cold→result="
        f"{data['cold_to_first_result_ms']:.3f} ms | "
        f"warm={data['warm_inference_ms']:.3f} ms | "
        f"CI startup="
        f"{startup['relative']*100:.2f}% | "
        f"CI cold="
        f"{cold['relative']*100:.2f}% | "
        f"CI first="
        f"{first['relative']*100:.2f}%"
    )


    stable = (
        rep >= MIN_REPS
        and
        startup["relative"]
        <= CI_TARGET
        and
        cold["relative"]
        <= CI_TARGET
    )


    if stable:

        print(
            "Primary CI targets satisfied."
        )

        break


    time.sleep(
        COOLDOWN_SECONDS
    )


# ============================================================
# Summary
# ============================================================

startup = ci(
    [
        x["startup_ms"]
        for x in measurements
    ]
)

first = ci(
    [
        x["first_inference_ms"]
        for x in measurements
    ]
)

cold = ci(
    [
        x["cold_to_first_result_ms"]
        for x in measurements
    ]
)

warm_ci = ci(
    [
        x["warm_inference_ms"]
        for x in measurements
    ]
)


summary = {

    "backend":
        BACKEND,

    "model":
        MODEL_NAME,

    "dataset":
        MODEL["dataset"],

    "workload_class":
        MODEL["workload_class"],

    "features":
        int(
            MODEL["features"]
        ),

    "repetitions":
        len(
            measurements
        ),

    "primary_ci_target":
        CI_TARGET,

    "primary_stopping_metrics": [
        "startup_ms",
        "cold_to_first_result_ms",
    ],

    "startup_ms":
        startup,

    "first_inference_ms":
        first,

    "cold_to_first_result_ms":
        cold,

    "warm_inference_ms":
        warm_ci,

    "primary_ci_pass":
        bool(
            startup["relative"]
            <= CI_TARGET
            and
            cold["relative"]
            <= CI_TARGET
        ),

    "first_inference_ci_pass":
        bool(
            first["relative"]
            <= CI_TARGET
        ),

    "warm_inference_ci_pass":
        bool(
            warm_ci["relative"]
            <= CI_TARGET
        ),
}


SUMMARY_JSON.write_text(
    json.dumps(
        summary,
        indent=2,
    )
)


# ============================================================
# Final output
# ============================================================

print()
print("=" * 78)

print(
    f"{BACKEND.upper()} / "
    f"{MODEL_NAME.upper()} "
    "COLD-START SUMMARY"
)

print("=" * 78)


print(
    f"n={summary['repetitions']}"
)


print(
    f"startup="
    f"{summary['startup_ms']['mean']:.3f} ms | "
    f"CI="
    f"{summary['startup_ms']['relative']*100:.3f}%"
)


print(
    f"first inference="
    f"{summary['first_inference_ms']['mean']:.3f} ms | "
    f"CI="
    f"{summary['first_inference_ms']['relative']*100:.3f}%"
)


print(
    f"cold→first result="
    f"{summary['cold_to_first_result_ms']['mean']:.3f} ms | "
    f"CI="
    f"{summary['cold_to_first_result_ms']['relative']*100:.3f}%"
)


print(
    f"warm="
    f"{summary['warm_inference_ms']['mean']:.3f} ms | "
    f"CI="
    f"{summary['warm_inference_ms']['relative']*100:.3f}%"
)


print(
    "Primary CI pass:",
    summary["primary_ci_pass"]
)


print()
print(
    f"Raw CSV: {RAW_CSV}"
)

print(
    f"Summary JSON: {SUMMARY_JSON}"
)

print()

print(
    "UNIFIED COLD-START EXPERIMENT: COMPLETE"
)

