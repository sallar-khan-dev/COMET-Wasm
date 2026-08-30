#!/usr/bin/env python3

import argparse
import asyncio
import csv
import json
import statistics
import sys
import time
from pathlib import Path

import aiohttp
import numpy as np


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
    "--model-a",
    required=True,
)

parser.add_argument(
    "--model-b",
    default=None,
)

parser.add_argument(
    "--port-a",
    required=True,
    type=int,
)

parser.add_argument(
    "--port-b",
    type=int,
    default=None,
)

parser.add_argument(
    "--physical-units",
    type=int,
    default=20,
)

parser.add_argument(
    "--concurrency",
    type=int,
    default=32,
)

parser.add_argument(
    "--requests",
    type=int,
    default=5000,
)

parser.add_argument(
    "--output",
    required=True,
)

args = parser.parse_args()


if args.physical_units != 20:
    raise SystemExit(
        "Frozen interference protocol requires "
        "--physical-units 20"
    )

if args.concurrency != 32:
    raise SystemExit(
        "Frozen interference protocol requires "
        "--concurrency 32"
    )

if args.requests != 5000:
    raise SystemExit(
        "Frozen interference protocol requires "
        "--requests 5000"
    )

if (
    args.model_b is not None
    and args.port_b is None
):
    raise SystemExit(
        "--port-b required when --model-b is supplied"
    )


# ============================================================
# Repository
# ============================================================

ROOT = Path(__file__).resolve().parents[2]

if str(ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(ROOT)
    )

from experiments.common.model_registry import (
    get_model,
)


# ============================================================
# Workload preparation
# ============================================================

def prepare_model(
    model_name,
):

    cfg = get_model(
        model_name
    )

    data_path = cfg[
        "test_path_abs"
    ]

    model_path = cfg[
        "model_path_abs"
    ]

    with data_path.open(
        newline=""
    ) as f:

        row = next(
            csv.DictReader(f)
        )

    features = [
        float(value)
        for key, value in row.items()
        if key.lower()
        not in {
            "label",
            "target",
            "class",
            "y",
            "expected",
            "prediction",
        }
    ]

    if len(features) != int(
        cfg["features"]
    ):

        raise RuntimeError(
            f"{model_name}: feature mismatch "
            f"{len(features)} != {cfg['features']}"
        )

    if (
        cfg["task"]
        == "clustering_inference"
    ):

        model_data = json.loads(
            model_path.read_text()
        )

        centroids = model_data[
            "centroids"
        ]

        best_cluster = 0
        best_distance = float(
            "inf"
        )

        for cid, centroid in enumerate(
            centroids
        ):

            distance = sum(
                (x - mu) ** 2
                for x, mu in zip(
                    features,
                    centroid,
                )
            )

            if distance < best_distance:

                best_distance = distance
                best_cluster = cid

        expected = best_cluster

    else:

        expected = int(
            row["label"]
        )

    return {
        "name":
            model_name,

        "features":
            features,

        "expected":
            expected,
    }


MODEL_A = prepare_model(
    args.model_a
)

MODEL_B = (
    prepare_model(
        args.model_b
    )
    if args.model_b
    else None
)


# ============================================================
# Request target
# ============================================================

def request_target(
    workload,
    port,
    index,
):

    physical_id = (
        index
        % args.physical_units
    )

    if args.backend == "wasmtime":

        url = (
            f"http://127.0.0.1:"
            f"{port}/infer"
        )

        body = {
            "tenant_id":
                physical_id,

            "features":
                workload["features"],
        }

    else:

        # Docker pool:
        # supplied port is base port.
        actual_port = (
            port
            + physical_id
        )

        url = (
            f"http://127.0.0.1:"
            f"{actual_port}/infer"
        )

        body = {
            "features":
                workload["features"]
        }

    return (
        physical_id,
        url,
        body,
    )


# ============================================================
# Single request
# ============================================================

async def one_request(
    session,
    workload,
    port,
    index,
):

    physical_id, url, body = (
        request_target(
            workload,
            port,
            index,
        )
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
                }

            prediction = int(
                payload["prediction"]
            )

            return {
                "success":
                    True,

                "correct":
                    prediction
                    == workload["expected"],

                "latency_ms":
                    elapsed_ms,
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
        }


# ============================================================
# Stream
# ============================================================

async def run_stream(
    session,
    workload,
    port,
    start_event,
):

    queue = asyncio.Queue()

    for i in range(
        args.requests
    ):
        queue.put_nowait(i)

    results = []

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
                    workload,
                    port,
                    index,
                )
            )

            results.append(
                result
            )

            queue.task_done()

    # Synchronized measured start.
    await start_event.wait()

    start = (
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
        - start
    )

    return (
        results,
        elapsed,
    )


# ============================================================
# Summary
# ============================================================

def summarize(
    workload,
    results,
    elapsed,
):

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

    if not latencies:

        raise RuntimeError(
            f"{workload['name']}: "
            "no successful requests"
        )

    if len(correct) != len(
        successful
    ):

        raise RuntimeError(
            f"{workload['name']}: "
            "incorrect predictions detected"
        )

    return {
        "model":
            workload["name"],

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
            float(
                np.percentile(
                    latencies,
                    50,
                )
            ),

        "p90_latency_ms":
            float(
                np.percentile(
                    latencies,
                    90,
                )
            ),

        "p95_latency_ms":
            float(
                np.percentile(
                    latencies,
                    95,
                )
            ),

        "p99_latency_ms":
            float(
                np.percentile(
                    latencies,
                    99,
                )
            ),

        "max_latency_ms":
            max(
                latencies
            ),
    }


# ============================================================
# Main async experiment
# ============================================================

async def main():

    connector = aiohttp.TCPConnector(
        limit=(
            args.concurrency
            * (
                2
                if MODEL_B
                else 1
            )
        ),
        limit_per_host=0,
        force_close=False,
        enable_cleanup_closed=True,
    )

    timeout = aiohttp.ClientTimeout(
        total=30
    )

    async with aiohttp.ClientSession(
        connector=connector,
        timeout=timeout,
    ) as session:

        # --------------------------------------------
        # Identical warm-up rule to validated client:
        # max(physical_units, concurrency) = 32
        # --------------------------------------------

        warm_count = max(
            args.physical_units,
            args.concurrency,
        )

        for i in range(
            warm_count
        ):

            result = await one_request(
                session,
                MODEL_A,
                args.port_a,
                i,
            )

            if (
                not result["success"]
                or not result["correct"]
            ):

                raise RuntimeError(
                    "Model A warm-up failed"
                )

        if MODEL_B:

            for i in range(
                warm_count
            ):

                result = await one_request(
                    session,
                    MODEL_B,
                    args.port_b,
                    i,
                )

                if (
                    not result["success"]
                    or not result["correct"]
                ):

                    raise RuntimeError(
                        "Model B warm-up failed"
                    )

        start_event = (
            asyncio.Event()
        )

        task_a = asyncio.create_task(
            run_stream(
                session,
                MODEL_A,
                args.port_a,
                start_event,
            )
        )

        task_b = None

        if MODEL_B:

            task_b = asyncio.create_task(
                run_stream(
                    session,
                    MODEL_B,
                    args.port_b,
                    start_event,
                )
            )

        # Ensure both stream tasks exist before release.
        await asyncio.sleep(0)

        start_event.set()

        results_a, elapsed_a = (
            await task_a
        )

        summary_a = summarize(
            MODEL_A,
            results_a,
            elapsed_a,
        )

        summary_b = None

        if task_b:

            results_b, elapsed_b = (
                await task_b
            )

            summary_b = summarize(
                MODEL_B,
                results_b,
                elapsed_b,
            )

    return {
        "backend":
            args.backend,

        "mode":
            (
                "mixed"
                if MODEL_B
                else "solo"
            ),

        "physical_units_per_model":
            args.physical_units,

        "concurrency_per_model":
            args.concurrency,

        "requests_per_model":
            args.requests,

        "stream_a":
            summary_a,

        "stream_b":
            summary_b,
    }


result = asyncio.run(
    main()
)

out = Path(
    args.output
)

out.parent.mkdir(
    parents=True,
    exist_ok=True,
)

out.write_text(
    json.dumps(
        result,
        indent=2,
    )
)

print(
    json.dumps(
        result,
        indent=2,
    )
)

