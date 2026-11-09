#!/usr/bin/env python3

import csv
import json
import math
import signal
import socket
import statistics
import subprocess
import time
import urllib.request
from pathlib import Path

from scipy.stats import t as student_t


ROOT = Path(__file__).resolve().parents[2]

SERVER = (
    ROOT
    / "serving/multitenant_server/target/release/"
      "comet_multitenant_server"
)

WASM = (
    ROOT
    / "wasm/tenant_nb_real/target/"
      "wasm32-unknown-unknown/release/"
      "tenant_nb_real.wasm"
)

DATA = (
    ROOT
    / "models/naive_bayes/breast_cancer/"
      "test_samples.csv"
)

RAW_DIR = ROOT / "results/raw/cold_start"
PROC_DIR = ROOT / "results/processed/cold_start"

RAW_DIR.mkdir(parents=True, exist_ok=True)
PROC_DIR.mkdir(parents=True, exist_ok=True)

MIN_REPS = 20
MAX_REPS = 60
CI_TARGET = 0.025
COOLDOWN_SECONDS = 1.0

DOCKER_IMAGE = "comet-nb-docker:v1"
DOCKER_NAME = "comet-nb-coldstart"
DOCKER_PORT = 8400

with DATA.open() as f:
    row = next(csv.DictReader(f))

FEATURES = [
    float(v)
    for k, v in row.items()
    if k != "label"
]

EXPECTED = int(row["label"])


def ci(values):

    n = len(values)

    if n == 0:
        return {
            "n": 0,
            "mean": 0.0,
            "halfwidth": math.inf,
            "relative": math.inf,
        }

    mean = statistics.mean(values)

    if n < 2:
        return {
            "n": n,
            "mean": mean,
            "halfwidth": math.inf,
            "relative": math.inf,
        }

    sd = statistics.stdev(values)

    critical = student_t.ppf(
        0.975,
        df=n - 1
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


def make_request(url, wasmtime):

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
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json"
        },
        method="POST",
    )

    t0 = time.perf_counter_ns()

    with urllib.request.urlopen(
        req,
        timeout=5,
    ) as r:
        result = json.loads(r.read())

    t1 = time.perf_counter_ns()

    if int(result["prediction"]) != EXPECTED:
        raise RuntimeError(
            "Incorrect prediction."
        )

    return (
        (t1 - t0) / 1_000_000.0
    )


def wait_port(host, port, timeout=20):

    deadline = time.time() + timeout

    while time.time() < deadline:

        sock = socket.socket(
            socket.AF_INET,
            socket.SOCK_STREAM
        )

        sock.settimeout(0.05)

        try:
            result = sock.connect_ex(
                (host, port)
            )

            if result == 0:
                return

        finally:
            sock.close()

        time.sleep(0.002)

    raise RuntimeError(
        "Port readiness timeout."
    )


def measure_wasmtime():

    subprocess.run(
        ["pkill", "-f", "comet_multitenant_server"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    start_ns = time.perf_counter_ns()

    proc = subprocess.Popen(
        [
            str(SERVER),
            "naive_bayes",
            str(WASM),
            "1",
            "8100",
        ],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )

    try:

        deadline = time.time() + 20

        while True:

            if proc.poll() is not None:
                raise RuntimeError(
                    "Wasmtime exited before readiness."
                )

            try:
                with urllib.request.urlopen(
                    "http://127.0.0.1:8100/health",
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

            time.sleep(0.002)

        ready_ns = time.perf_counter_ns()

        first_ms = make_request(
            "http://127.0.0.1:8100/infer",
            True
        )

        first_done_ns = time.perf_counter_ns()

        warm = []

        for _ in range(20):
            warm.append(
                make_request(
                    "http://127.0.0.1:8100/infer",
                    True
                )
            )

        return {
            "startup_ms":
                (
                    ready_ns - start_ns
                ) / 1_000_000.0,

            "first_inference_ms":
                first_ms,

            "cold_to_first_result_ms":
                (
                    first_done_ns - start_ns
                ) / 1_000_000.0,

            "warm_inference_ms":
                statistics.mean(warm),
        }

    finally:

        if proc.poll() is None:

            proc.send_signal(
                signal.SIGTERM
            )

            try:
                proc.wait(timeout=5)

            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


def measure_docker():

    subprocess.run(
        [
            "docker",
            "rm",
            "-f",
            DOCKER_NAME,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    start_ns = time.perf_counter_ns()

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

        # Application-level readiness without consuming inference.
        #
        # Docker port forwarding may become reachable before the
        # inference server inside the container is fully ready.
        # Therefore TCP-connect readiness is insufficient for a
        # cold-start measurement. Wait until the application itself
        # reports that the HTTP server is listening.

        deadline = time.time() + 30

        ready_marker = (
            "Docker NB server listening on "
            "http://0.0.0.0:8085"
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

            if ready_marker in combined:
                break

            if time.time() > deadline:
                raise RuntimeError(
                    "Docker application readiness timeout."
                )

            time.sleep(0.002)

        ready_ns = time.perf_counter_ns()

        # The first /infer request below is now genuinely the first
        # inference request seen by this fresh container.
        first_ms = make_request(
            f"http://127.0.0.1:{DOCKER_PORT}/infer",
            False
        )

        first_done_ns = time.perf_counter_ns()

        warm = []

        for _ in range(20):
            warm.append(
                make_request(
                    f"http://127.0.0.1:{DOCKER_PORT}/infer",
                    False
                )
            )

        return {
            "startup_ms":
                (
                    ready_ns - start_ns
                ) / 1_000_000.0,

            "first_inference_ms":
                first_ms,

            "cold_to_first_result_ms":
                (
                    first_done_ns - start_ns
                ) / 1_000_000.0,

            "warm_inference_ms":
                statistics.mean(warm),
        }

    finally:

        subprocess.run(
            [
                "docker",
                "rm",
                "-f",
                DOCKER_NAME,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


def run_backend(
    backend,
):

    out_csv = (
        RAW_DIR
        / f"{backend}_naive_bayes_cold_start.csv"
    )

    out_json = (
        PROC_DIR
        / f"{backend}_naive_bayes_cold_start_summary.json"
    )

    if out_csv.exists():
        out_csv.unlink()

    measurements = []

    for rep in range(
        1,
        MAX_REPS + 1
    ):

        data = (
            measure_wasmtime()
            if backend == "wasmtime"
            else measure_docker()
        )

        measurements.append(data)

        exists = out_csv.exists()

        with out_csv.open(
            "a",
            newline="",
        ) as f:

            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "backend",
                    "repetition",
                    "startup_ms",
                    "first_inference_ms",
                    "cold_to_first_result_ms",
                    "warm_inference_ms",
                ],
            )

            if not exists:
                writer.writeheader()

            writer.writerow({
                "backend": backend,
                "repetition": rep,
                **data,
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

        print(
            f"rep={rep:02d} | "
            f"startup={data['startup_ms']:.3f} ms | "
            f"first={data['first_inference_ms']:.3f} ms | "
            f"cold→result={data['cold_to_first_result_ms']:.3f} ms | "
            f"CI startup={startup['relative']*100:.2f}% | "
            f"CI cold={cold['relative']*100:.2f}% | "
            f"CI first={first['relative']*100:.2f}%"
        )

        stable = (
            rep >= MIN_REPS
            and startup["relative"] <= CI_TARGET
            and cold["relative"] <= CI_TARGET
            and first["relative"] <= CI_TARGET
        )

        if stable:
            print("CI targets satisfied.")
            break

        time.sleep(
            COOLDOWN_SECONDS
        )

    summary = {
        "backend": backend,
        "model": "naive_bayes",
        "repetitions": len(measurements),
        "startup_ms": ci(
            [x["startup_ms"] for x in measurements]
        ),
        "first_inference_ms": ci(
            [x["first_inference_ms"] for x in measurements]
        ),
        "cold_to_first_result_ms": ci(
            [x["cold_to_first_result_ms"] for x in measurements]
        ),
        "warm_inference_ms": ci(
            [x["warm_inference_ms"] for x in measurements]
        ),
    }

    out_json.write_text(
        json.dumps(
            summary,
            indent=2
        )
    )

    print()
    print(
        f"===== {backend.upper()} COLD-START SUMMARY ====="
    )
    print(
        f"n={summary['repetitions']}"
    )
    print(
        f"startup="
        f"{summary['startup_ms']['mean']:.3f} ms"
    )
    print(
        f"first inference="
        f"{summary['first_inference_ms']['mean']:.3f} ms"
    )
    print(
        f"cold→first result="
        f"{summary['cold_to_first_result_ms']['mean']:.3f} ms"
    )
    print(
        f"warm="
        f"{summary['warm_inference_ms']['mean']:.3f} ms"
    )


if __name__ == "__main__":

    import argparse

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--backend",
        required=True,
        choices=[
            "wasmtime",
            "docker",
        ],
    )

    args = parser.parse_args()

    run_backend(
        args.backend
    )
