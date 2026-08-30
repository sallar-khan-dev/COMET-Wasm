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


ROOT = Path(__file__).resolve().parents[2]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from experiments.common.model_registry import (
    get_model,
    supported_models,
)


# ============================================================
# Protocol
# ============================================================

REQUESTS_PER_REP = 5000
WARMUP_REQUESTS = 1000

MIN_REPS = 20
MAX_REPS = 60

CI_TARGET = 0.025

CONCURRENCY = 1
PHYSICAL_UNITS = 1

WASMTIME_PORT = 8100
DOCKER_PORT = 8300

# Dedicated single-backend CPU placement.
SERVER_CPU = "0"
CLIENT_CPU = "1"

COOLDOWN_SECONDS = 1.0


SERVER = (
    ROOT
    / "serving"
    / "multitenant_server"
    / "target"
    / "release"
    / "comet_multitenant_server"
)

CLIENT = (
    ROOT
    / "experiments"
    / "overhead"
    / "load_client_overhead.py"
)

RAW_DIR = ROOT / "results/raw/overhead"
PROCESSED_DIR = ROOT / "results/processed/overhead"

RAW_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


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
MODEL = get_model(MODEL_NAME)

RAW_CSV = (
    RAW_DIR
    / f"{BACKEND}_{MODEL_NAME}_overhead_full.csv"
)

SUMMARY_JSON = (
    PROCESSED_DIR
    / f"{BACKEND}_{MODEL_NAME}_overhead_full_summary.json"
)

TMP_JSON = (
    PROCESSED_DIR
    / f".tmp_{BACKEND}_{MODEL_NAME}_overhead.json"
)

DOCKER_NAME = (
    f"comet-overhead-{MODEL_NAME.replace('_', '-')}"
)


# ============================================================
# Statistics
# ============================================================

def ci_stats(values):

    n = len(values)

    if n < 2:
        return {
            "n": n,
            "mean":
                statistics.mean(values)
                if values else 0.0,
            "halfwidth": math.inf,
            "relative": math.inf,
        }

    mean = statistics.mean(values)
    sd = statistics.stdev(values)

    critical = student_t.ppf(
        0.975,
        n - 1,
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
        "halfwidth": halfwidth,
        "relative": relative,
    }


# ============================================================
# Cleanup / readiness
# ============================================================

def kill_wasmtime():

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


def docker_cleanup():

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


def wait_wasmtime(proc):

    deadline = time.time() + 20

    while time.time() < deadline:

        if proc.poll() is not None:
            raise RuntimeError(
                "Wasmtime server exited during startup"
            )

        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{WASMTIME_PORT}/metadata",
                timeout=1,
            ) as r:

                metadata = json.loads(
                    r.read().decode()
                )

            if (
                metadata.get("model") == MODEL_NAME
                and int(metadata.get("workers", 0)) == 1
            ):
                return

        except Exception:
            pass

        time.sleep(0.05)

    raise RuntimeError(
        "Wasmtime readiness timeout"
    )


def wait_docker():

    sample = (
        [0.0] * int(MODEL["features"])
    )

    body = json.dumps({
        "features": sample
    }).encode()

    deadline = time.time() + 30

    while time.time() < deadline:

        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{DOCKER_PORT}/infer",
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
                    return

        except Exception:
            pass

        time.sleep(0.05)

    raise RuntimeError(
        "Docker readiness timeout"
    )


# ============================================================
# Backend startup
# ============================================================

def start_wasmtime():

    kill_wasmtime()

    time.sleep(0.2)

    proc = subprocess.Popen(
        [
            "taskset",
            "-c",
            SERVER_CPU,

            str(SERVER),

            MODEL_NAME,
            str(MODEL["wasm_artifact_abs"]),

            "1",
            str(WASMTIME_PORT),
        ],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )

    wait_wasmtime(proc)

    return proc


def stop_wasmtime(proc):

    if proc is None:
        return

    if proc.poll() is not None:
        return

    proc.send_signal(signal.SIGTERM)

    try:
        proc.wait(timeout=5)

    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def start_docker():

    docker_cleanup()

    result = subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--rm",

            "--name",
            DOCKER_NAME,

            "--cpuset-cpus",
            SERVER_CPU,

            "-p",
            f"{DOCKER_PORT}:8085",

            MODEL["docker_image"],
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )

    if result.returncode != 0:
        raise RuntimeError(
            result.stderr
        )

    wait_docker()


# ============================================================
# One repetition
# ============================================================

def run_repetition():

    proc = None

    try:

        if BACKEND == "wasmtime":
            proc = start_wasmtime()

        else:
            start_docker()

        cmd = [
            "taskset",
            "-c",
            CLIENT_CPU,

            sys.executable,
            str(CLIENT),

            "--backend",
            BACKEND,

            "--model",
            MODEL_NAME,

            "--concurrency",
            str(CONCURRENCY),

            "--requests",
            str(REQUESTS_PER_REP),

            "--physical-units",
            str(PHYSICAL_UNITS),

            "--warmup",
            str(WARMUP_REQUESTS),

            "--output",
            str(TMP_JSON),
        ]

        result = subprocess.run(
            cmd,
            cwd=ROOT,
            text=True,
            capture_output=True,
        )

        if result.returncode != 0:
            raise RuntimeError(
                "Overhead client failed:\n"
                + result.stderr
                + "\n"
                + result.stdout
            )

        data = json.loads(
            TMP_JSON.read_text()
        )

        if int(data["errors"]) != 0:
            raise RuntimeError(
                f"Client reported {data['errors']} errors"
            )

        if (
            int(data["correct_predictions"])
            != int(data["successful_requests"])
        ):
            raise RuntimeError(
                "Prediction correctness failure"
            )

        e2e = float(
            data["mean_e2e_ns"]
        )

        inference = float(
            data["mean_inference_time_ns"]
        )

        execution = float(
            data["mean_execution_time_ns"]
        )

        return {
            "throughput_rps":
                float(data["throughput_rps"]),

            "e2e_mean_ns":
                e2e,

            "inference_mean_ns":
                inference,

            "execution_mean_ns":
                execution,

            "non_execution_e2e_ns":
                e2e - execution,

            "outside_inference_ns":
                e2e - inference,

            "server_non_execution_ns":
                inference - execution,
        }

    finally:

        if proc is not None:
            stop_wasmtime(proc)

        if BACKEND == "docker":
            docker_cleanup()

        if TMP_JSON.exists():
            TMP_JSON.unlink()

        time.sleep(
            COOLDOWN_SECONDS
        )


# ============================================================
# Persistence
# ============================================================

FIELDS = [
    "backend",
    "model",
    "repetition",
    "requests",
    "throughput_rps",
    "e2e_mean_ns",
    "inference_mean_ns",
    "execution_mean_ns",
    "non_execution_e2e_ns",
    "outside_inference_ns",
    "server_non_execution_ns",
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
# Main experiment
# ============================================================

e2e_values = [
    float(r["e2e_mean_ns"])
    for r in existing
]

execution_values = [
    float(r["execution_mean_ns"])
    for r in existing
]


print()
print("=" * 78)
print("COMET-Wasm SYNCHRONIZED OVERHEAD DECOMPOSITION")
print("=" * 78)
print(f"Backend: {BACKEND}")
print(f"Model: {MODEL_NAME}")
print(f"Concurrency: {CONCURRENCY}")
print(f"Physical units: {PHYSICAL_UNITS}")
print(f"Warm-up requests: {WARMUP_REQUESTS}")
print(
    f"Measured requests/repetition: "
    f"{REQUESTS_PER_REP}"
)
print(f"Minimum repetitions: {MIN_REPS}")
print(f"Maximum repetitions: {MAX_REPS}")
print("Relative 95% CI target: 2.50%")
print()


existing_e2e = ci_stats(e2e_values)
existing_exec = ci_stats(execution_values)

already_done = (
    len(existing) >= MIN_REPS
    and existing_e2e["relative"] <= CI_TARGET
    and existing_exec["relative"] <= CI_TARGET
)


for rep in (
    []
    if already_done
    else range(
        len(existing) + 1,
        MAX_REPS + 1,
    )
):

    result = run_repetition()

    row = {
        "backend": BACKEND,
        "model": MODEL_NAME,
        "repetition": rep,
        "requests":
            REQUESTS_PER_REP,
        **result,
        "timestamp_unix":
            time.time(),
    }

    append_raw(row)

    e2e_values.append(
        result["e2e_mean_ns"]
    )

    execution_values.append(
        result["execution_mean_ns"]
    )

    e2e_ci = ci_stats(
        e2e_values
    )

    exec_ci = ci_stats(
        execution_values
    )

    print(
        f"rep={rep:02d} | "
        f"E2E={result['e2e_mean_ns']/1000:.2f} us | "
        f"infer={result['inference_mean_ns']/1000:.3f} us | "
        f"exec={result['execution_mean_ns']/1000:.3f} us | "
        f"CI E2E={e2e_ci['relative']*100:.2f}% | "
        f"CI Exec={exec_ci['relative']*100:.2f}%"
    )

    if (
        rep >= MIN_REPS
        and e2e_ci["relative"] <= CI_TARGET
        and exec_ci["relative"] <= CI_TARGET
    ):

        print("CI targets satisfied.")
        break


# ============================================================
# Final summary
# ============================================================

with RAW_CSV.open() as f:
    rows = list(
        csv.DictReader(f)
    )


def values(key):

    return [
        float(r[key])
        for r in rows
    ]


e2e = values("e2e_mean_ns")
infer = values("inference_mean_ns")
execute = values("execution_mean_ns")
non_exec = values("non_execution_e2e_ns")
outside = values("outside_inference_ns")
server_non_exec = values("server_non_execution_ns")
throughput = values("throughput_rps")

e2e_ci = ci_stats(e2e)
exec_ci = ci_stats(execute)


summary = {
    "backend": BACKEND,
    "model": MODEL_NAME,

    "concurrency": CONCURRENCY,
    "physical_units": PHYSICAL_UNITS,

    "warmup_requests":
        WARMUP_REQUESTS,

    "requests_per_repetition":
        REQUESTS_PER_REP,

    "repetitions":
        len(rows),

    "total_measured_requests":
        len(rows)
        * REQUESTS_PER_REP,

    "mean_throughput_rps":
        statistics.mean(throughput),

    "mean_e2e_ns":
        statistics.mean(e2e),

    "mean_inference_ns":
        statistics.mean(infer),

    "mean_execution_ns":
        statistics.mean(execute),

    "mean_non_execution_e2e_ns":
        statistics.mean(non_exec),

    "mean_outside_inference_ns":
        statistics.mean(outside),

    "mean_server_non_execution_ns":
        statistics.mean(server_non_exec),

    "execution_fraction_of_e2e":
        statistics.mean(execute)
        / statistics.mean(e2e),

    "inference_fraction_of_e2e":
        statistics.mean(infer)
        / statistics.mean(e2e),

    "e2e_relative_95ci":
        e2e_ci["relative"],

    "execution_relative_95ci":
        exec_ci["relative"],

    "ci_target_pass":
        bool(
            e2e_ci["relative"] <= CI_TARGET
            and exec_ci["relative"] <= CI_TARGET
        ),
}


SUMMARY_JSON.write_text(
    json.dumps(
        summary,
        indent=2,
    )
)


print()
print("=" * 78)
print("OVERHEAD DECOMPOSITION SUMMARY")
print("=" * 78)

print(
    f"Repetitions: {len(rows)}"
)

print(
    f"E2E: "
    f"{summary['mean_e2e_ns']/1000:.3f} us"
)

print(
    f"Inference: "
    f"{summary['mean_inference_ns']/1000:.3f} us"
)

print(
    f"Execution: "
    f"{summary['mean_execution_ns']/1000:.3f} us"
)

print(
    f"Non-execution E2E: "
    f"{summary['mean_non_execution_e2e_ns']/1000:.3f} us"
)

print(
    f"Execution share of E2E: "
    f"{summary['execution_fraction_of_e2e']*100:.3f}%"
)

print(
    f"E2E CI: "
    f"{summary['e2e_relative_95ci']*100:.3f}%"
)

print(
    f"Execution CI: "
    f"{summary['execution_relative_95ci']*100:.3f}%"
)

print()
print(f"Raw CSV: {RAW_CSV}")
print(f"Summary JSON: {SUMMARY_JSON}")
print()
print("OVERHEAD DECOMPOSITION EXPERIMENT: COMPLETE")
