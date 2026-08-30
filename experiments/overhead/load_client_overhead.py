#!/usr/bin/env python3

import argparse
import asyncio
import csv
import json
import statistics
import time
import sys
from pathlib import Path

import aiohttp
import numpy as np


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

parser.add_argument(
    "--warmup",
    type=int,
    default=1000,
)

args = parser.parse_args()


if args.concurrency < 1:
    raise SystemExit("Concurrency must be >= 1")

if args.requests < args.concurrency:
    raise SystemExit(
        "Requests must be >= concurrency"
    )

if args.physical_units < 1:
    raise SystemExit(
        "Physical units must be >= 1"
    )


ROOT = Path(__file__).resolve().parents[2]

if str(ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(ROOT)
    )

from experiments.common.model_registry import get_model


MODEL_NAME = args.model

MODEL_CFG = get_model(
    MODEL_NAME
)

DATA = MODEL_CFG[
    "test_path_abs"
]

MODEL_PATH = MODEL_CFG[
    "model_path_abs"
]


with DATA.open(
    newline=""
) as f:

    row = next(
        csv.DictReader(f)
    )


FEATURES = [
    float(value)
    for key, value in row.items()
    if key != "label"
]


if len(FEATURES) != int(
    MODEL_CFG["features"]
):

    raise RuntimeError(
        f"{MODEL_NAME}: feature-count mismatch. "
        f"Registry={MODEL_CFG['features']}, "
        f"sample={len(FEATURES)}"
    )


# ============================================================
# Expected prediction
# ============================================================

if MODEL_CFG["task"] == "clustering_inference":

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
                centroid
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

WASMTIME_URL = (
    "http://127.0.0.1:8100/infer"
)

DOCKER_BASE_PORT = 8300


def percentile(values, p):
    return float(
        np.percentile(values, p)
    )


def request_target(index):
    physical_id = (
        index
        % args.physical_units
    )

    if args.backend == "wasmtime":

        url = WASMTIME_URL

        body = {
            "tenant_id": physical_id,
            "features": FEATURES,
        }

    else:

        port = (
            DOCKER_BASE_PORT
            + physical_id
        )

        url = (
            f"http://127.0.0.1:"
            f"{port}/infer"
        )

        body = {
            "features": FEATURES
        }

    return physical_id, url, body


async def one_request(
    session,
    index,
):
    physical_id, url, body = (
        request_target(index)
    )

    start_ns = (
        time.perf_counter_ns()
    )

    try:

        async with session.post(
            url,
            json=body,
        ) as response:

            payload = (
                await response.json()
            )

            elapsed_ms = (
                time.perf_counter_ns()
                - start_ns
            ) / 1_000_000.0

            if response.status != 200:

                return {
                    "success": False,
                    "correct": False,
                    "latency_ms": elapsed_ms,
                    "physical_id": physical_id,
                }

            prediction = int(
                payload["prediction"]
            )

            return {
                "success": True,
                "correct":
                    prediction == EXPECTED,
                "latency_ms":
                    elapsed_ms,
                "e2e_latency_ns":
                    elapsed_ms * 1_000_000.0,
                "inference_time_ns":
                    float(payload["inference_time_ns"]),
                "execution_time_ns":
                    float(payload["execution_time_ns"]),
                "physical_id":
                    physical_id,
            }

    except Exception:

        elapsed_ms = (
            time.perf_counter_ns()
            - start_ns
        ) / 1_000_000.0

        return {
            "success": False,
            "correct": False,
            "latency_ms": elapsed_ms,
            "physical_id": physical_id,
        }


async def run_load():

    connector = aiohttp.TCPConnector(
        limit=args.concurrency,
        limit_per_host=0,
        force_close=False,
        enable_cleanup_closed=True,
    )

    timeout = aiohttp.ClientTimeout(
        total=30
    )

    queue = asyncio.Queue()

    for i in range(args.requests):
        queue.put_nowait(i)

    results = []

    async with aiohttp.ClientSession(
        connector=connector,
        timeout=timeout,
    ) as session:

        # Client/network warm-up
        warm_count = max(
            args.warmup,
            args.physical_units,
            args.concurrency,
        )

        for i in range(warm_count):
            await one_request(
                session,
                i,
            )

        async def worker():

            while True:

                try:
                    index = (
                        queue.get_nowait()
                    )

                except asyncio.QueueEmpty:
                    return

                result = (
                    await one_request(
                        session,
                        index,
                    )
                )

                results.append(
                    result
                )

                queue.task_done()

        start_wall = (
            time.perf_counter()
        )

        workers = [
            asyncio.create_task(
                worker()
            )
            for _ in range(
                args.concurrency
            )
        ]

        await asyncio.gather(
            *workers
        )

        elapsed = (
            time.perf_counter()
            - start_wall
        )

    return results, elapsed


results, elapsed = asyncio.run(
    run_load()
)


successful = [
    x
    for x in results
    if x["success"]
]

correct = [
    x
    for x in successful
    if x["correct"]
]

latencies = [
    x["latency_ms"]
    for x in successful
]

e2e_ns = [
    x["e2e_latency_ns"]
    for x in successful
]

inference_ns = [
    x["inference_time_ns"]
    for x in successful
]

execution_ns = [
    x["execution_time_ns"]
    for x in successful
]


if not latencies:
    raise SystemExit(
        "No successful requests."
    )


summary = {
    "backend":
        args.backend,

    "model":
        MODEL_NAME,

    "client":
        "aiohttp_async",

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
        max(latencies),

    "mean_e2e_ns":
        statistics.mean(e2e_ns),

    "mean_inference_time_ns":
        statistics.mean(inference_ns),

    "mean_execution_time_ns":
        statistics.mean(execution_ns),

    "mean_non_execution_e2e_ns":
        statistics.mean(e2e_ns)
        - statistics.mean(execution_ns),

    "mean_outside_inference_ns":
        statistics.mean(e2e_ns)
        - statistics.mean(inference_ns),
}


out = Path(args.output)

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
