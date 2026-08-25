#!/usr/bin/env python3

import argparse
import concurrent.futures
import csv
import json
import math
import statistics
import time
import urllib.request
from pathlib import Path

import numpy as np


parser = argparse.ArgumentParser()

parser.add_argument(
    "--backend",
    required=True,
    choices=["wasmtime", "docker"],
)

parser.add_argument(
    "--concurrency",
    required=True,
    type=int,
)

parser.add_argument(
    "--requests",
    required=True,
    type=int,
)

parser.add_argument(
    "--physical-units",
    required=True,
    type=int,
)

parser.add_argument(
    "--output",
    required=True,
)

args = parser.parse_args()


ROOT = Path(__file__).resolve().parents[2]

DATA = (
    ROOT
    / "models"
    / "naive_bayes"
    / "breast_cancer"
    / "test_samples.csv"
)


with DATA.open() as f:
    row = next(
        csv.DictReader(f)
    )


FEATURES = [
    float(v)
    for k, v in row.items()
    if k != "label"
]


EXPECTED = int(
    row["label"]
)


WASMTIME_URL = (
    "http://127.0.0.1:8100/infer"
)

DOCKER_BASE_PORT = 8300


def percentile(values, p):
    return float(
        np.percentile(
            values,
            p
        )
    )


def request_wasmtime(index):

    tenant_id = (
        index
        % args.physical_units
    )

    body = json.dumps({
        "tenant_id": tenant_id,
        "features": FEATURES,
    }).encode()

    req = urllib.request.Request(
        WASMTIME_URL,
        data=body,
        headers={
            "Content-Type":
                "application/json"
        },
        method="POST",
    )

    start = time.perf_counter_ns()

    try:
        with urllib.request.urlopen(
            req,
            timeout=30
        ) as r:

            response = json.loads(
                r.read()
            )

        latency_ms = (
            time.perf_counter_ns()
            - start
        ) / 1_000_000.0

        return {
            "success":
                True,

            "correct":
                int(
                    response[
                        "prediction"
                    ]
                ) == EXPECTED,

            "latency_ms":
                latency_ms,
        }

    except Exception:

        latency_ms = (
            time.perf_counter_ns()
            - start
        ) / 1_000_000.0

        return {
            "success":
                False,

            "correct":
                False,

            "latency_ms":
                latency_ms,
        }


def request_docker(index):

    container_id = (
        index
        % args.physical_units
    )

    port = (
        DOCKER_BASE_PORT
        + container_id
    )

    body = json.dumps({
        "features": FEATURES,
    }).encode()

    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/infer",
        data=body,
        headers={
            "Content-Type":
                "application/json"
        },
        method="POST",
    )

    start = time.perf_counter_ns()

    try:
        with urllib.request.urlopen(
            req,
            timeout=30
        ) as r:

            response = json.loads(
                r.read()
            )

        latency_ms = (
            time.perf_counter_ns()
            - start
        ) / 1_000_000.0

        return {
            "success":
                True,

            "correct":
                int(
                    response[
                        "prediction"
                    ]
                ) == EXPECTED,

            "latency_ms":
                latency_ms,
        }

    except Exception:

        latency_ms = (
            time.perf_counter_ns()
            - start
        ) / 1_000_000.0

        return {
            "success":
                False,

            "correct":
                False,

            "latency_ms":
                latency_ms,
        }


request_fn = (
    request_wasmtime
    if args.backend == "wasmtime"
    else request_docker
)


# Warm client/network path
for i in range(
    min(
        20,
        args.physical_units
    )
):
    request_fn(i)


start_wall = (
    time.perf_counter()
)


results = []

with concurrent.futures.ThreadPoolExecutor(
    max_workers=args.concurrency
) as executor:

    futures = [
        executor.submit(
            request_fn,
            i
        )
        for i in range(
            args.requests
        )
    ]

    for future in (
        concurrent.futures
        .as_completed(futures)
    ):
        results.append(
            future.result()
        )


elapsed = (
    time.perf_counter()
    - start_wall
)


successful = [
    r
    for r in results
    if r["success"]
]


correct = [
    r
    for r in successful
    if r["correct"]
]


latencies = [
    r["latency_ms"]
    for r in successful
]


if not latencies:
    raise SystemExit(
        "No successful requests."
    )


summary = {
    "backend":
        args.backend,

    "physical_units":
        args.physical_units,

    "concurrency":
        args.concurrency,

    "requests":
        args.requests,

    "successful_requests":
        len(successful),

    "correct_predictions":
        len(correct),

    "errors":
        args.requests
        - len(successful),

    "error_rate":
        (
            args.requests
            - len(successful)
        ) / args.requests,

    "elapsed_seconds":
        elapsed,

    "throughput_rps":
        len(successful)
        / elapsed,

    "mean_latency_ms":
        statistics.mean(
            latencies
        ),

    "p50_latency_ms":
        percentile(
            latencies,
            50
        ),

    "p90_latency_ms":
        percentile(
            latencies,
            90
        ),

    "p95_latency_ms":
        percentile(
            latencies,
            95
        ),

    "p99_latency_ms":
        percentile(
            latencies,
            99
        ),

    "max_latency_ms":
        max(
            latencies
        ),
}


out = Path(
    args.output
)

out.parent.mkdir(
    parents=True,
    exist_ok=True
)

out.write_text(
    json.dumps(
        summary,
        indent=2
    )
)


print(
    json.dumps(
        summary,
        indent=2
    )
)
