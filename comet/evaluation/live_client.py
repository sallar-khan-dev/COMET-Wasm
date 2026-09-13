#!/usr/bin/env python3

import argparse
import asyncio
import csv
import json
import random
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

import aiohttp
import numpy as np


ROOT = Path(__file__).resolve().parents[2]

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from comet.evaluation.policies import (
    choose_policy_backend,
)
from comet.scheduler.scheduler import (
    CometScheduler,
)
from experiments.common.model_registry import (
    get_model,
)


WASMTIME_PORT = 8100
DOCKER_BASE_PORT = 8300


parser = argparse.ArgumentParser()

parser.add_argument(
    "--model",
    required=True,
)

parser.add_argument(
    "--policy",
    required=True,
    choices=[
        "comet",
        "wasmtime_only",
        "docker_only",
        "random",
        "best_static",
    ],
)

parser.add_argument(
    "--concurrency",
    type=int,
    required=True,
)

parser.add_argument(
    "--tenants",
    type=int,
    default=20,
)

parser.add_argument(
    "--physical-units",
    type=int,
    default=20,
)

parser.add_argument(
    "--requests",
    type=int,
    default=1000,
)

parser.add_argument(
    "--memory-budget-mib",
    type=float,
    default=None,
)

parser.add_argument(
    "--sla-p95-ms",
    type=float,
    default=None,
)

parser.add_argument(
    "--static-backend",
    default="wasmtime",
    choices=[
        "wasmtime",
        "docker",
    ],
)

parser.add_argument(
    "--seed",
    type=int,
    default=42,
)

parser.add_argument(
    "--output",
    required=True,
)

args = parser.parse_args()


if args.concurrency < 1:
    raise SystemExit(
        "concurrency must be >= 1"
    )

if args.requests < args.concurrency:
    raise SystemExit(
        "requests must be >= concurrency"
    )

if args.tenants < 1:
    raise SystemExit(
        "tenants must be >= 1"
    )

if args.physical_units < 1:
    raise SystemExit(
        "physical-units must be >= 1"
    )


# ============================================================
# Workload preparation
# ============================================================

cfg = get_model(
    args.model
)

with cfg["test_path_abs"].open(
    newline=""
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
    cfg["features"]
):
    raise RuntimeError(
        f"Feature mismatch: "
        f"{len(FEATURES)} != "
        f"{cfg['features']}"
    )


if (
    cfg["task"]
    == "clustering_inference"
):
    model_data = json.loads(
        cfg[
            "model_path_abs"
        ].read_text()
    )

    centroids = model_data[
        "centroids"
    ]

    EXPECTED = min(
        range(
            len(centroids)
        ),
        key=lambda cid: sum(
            (x - mu) ** 2
            for x, mu in zip(
                FEATURES,
                centroids[cid],
            )
        ),
    )

else:
    EXPECTED = int(
        row["label"]
    )


# ============================================================
# Scheduler decision
# ============================================================

scheduler = CometScheduler()

decision = scheduler.schedule(
    model=args.model,
    concurrency=args.concurrency,
    tenants=args.tenants,
    memory_budget_mib=
        args.memory_budget_mib,
    sla_p95_ms=
        args.sla_p95_ms,
)


rng = random.Random(
    args.seed
)


def choose_backend():
    return choose_policy_backend(
        args.policy,
        decision,
        static_backend=
            args.static_backend,
        rng=rng,
    )


# ============================================================
# Request routing
# ============================================================

def request_target(
    index,
    backend,
):
    physical_id = (
        index
        % args.physical_units
    )

    tenant_id = (
        index
        % args.tenants
    )

    if backend == "wasmtime":

        url = (
            "http://127.0.0.1:"
            f"{WASMTIME_PORT}/infer"
        )

        body = {
            "tenant_id":
                tenant_id,

            "features":
                FEATURES,
        }

    elif backend == "docker":

        port = (
            DOCKER_BASE_PORT
            + physical_id
        )

        url = (
            "http://127.0.0.1:"
            f"{port}/infer"
        )

        body = {
            "features":
                FEATURES,
        }

    else:
        return None, None

    return url, body


async def one_request(
    session,
    index,
):
    decision_start = (
        time.perf_counter_ns()
    )

    backend = choose_backend()

    decision_time_ns = (
        time.perf_counter_ns()
        - decision_start
    )

    if backend is None:
        return {
            "admitted": False,
            "success": False,
            "correct": False,
            "backend": None,
            "latency_ms": None,
            "decision_time_ns":
                decision_time_ns,
            "inference_time_ns": None,
            "execution_time_ns": None,
        }

    url, body = request_target(
        index,
        backend,
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
                    "admitted": True,
                    "success": False,
                    "correct": False,
                    "backend": backend,
                    "latency_ms":
                        elapsed_ms,
                    "decision_time_ns":
                        decision_time_ns,
                    "inference_time_ns":
                        None,
                    "execution_time_ns":
                        None,
                }

            prediction = int(
                payload["prediction"]
            )

            return {
                "admitted": True,
                "success": True,
                "correct":
                    prediction
                    == EXPECTED,
                "backend":
                    backend,
                "latency_ms":
                    elapsed_ms,
                "decision_time_ns":
                    decision_time_ns,
                "inference_time_ns":
                    payload.get(
                        "inference_time_ns"
                    ),
                "execution_time_ns":
                    payload.get(
                        "execution_time_ns"
                    ),
            }

    except Exception:

        elapsed_ms = (
            time.perf_counter_ns()
            - start_ns
        ) / 1_000_000.0

        return {
            "admitted": True,
            "success": False,
            "correct": False,
            "backend": backend,
            "latency_ms":
                elapsed_ms,
            "decision_time_ns":
                decision_time_ns,
            "inference_time_ns":
                None,
            "execution_time_ns":
                None,
        }


# ============================================================
# Async load
# ============================================================

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

    for i in range(
        args.requests
    ):
        queue.put_nowait(i)

    results = []

    async with aiohttp.ClientSession(
        connector=connector,
        timeout=timeout,
    ) as session:

        # Same warm-up rule as validated performance client.
        warm_count = max(
            args.physical_units,
            args.concurrency,
        )

        for i in range(
            warm_count
        ):
            backend = choose_backend()

            if backend is None:
                continue

            url, body = request_target(
                i,
                backend,
            )

            try:
                async with session.post(
                    url,
                    json=body,
                ) as response:
                    await response.read()
            except Exception:
                pass

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

    return results, elapsed


results, elapsed = asyncio.run(
    run_load()
)


# ============================================================
# Summary
# ============================================================

admitted = [
    x
    for x in results
    if x["admitted"]
]

successful = [
    x
    for x in admitted
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

decision_times = [
    x["decision_time_ns"]
    for x in results
]

server_inference = [
    int(
        x["inference_time_ns"]
    )
    for x in successful
    if x[
        "inference_time_ns"
    ] is not None
]

server_execution = [
    int(
        x["execution_time_ns"]
    )
    for x in successful
    if x[
        "execution_time_ns"
    ] is not None
]


backend_distribution = Counter(
    x["backend"]
    for x in admitted
    if x["backend"] is not None
)


def percentile(
    values,
    q,
):
    if not values:
        return None

    return float(
        np.percentile(
            values,
            q,
        )
    )


summary = {
    "evaluation_type":
        "live_policy_routing",

    "model":
        args.model,

    "policy":
        args.policy,

    "seed":
        args.seed,

    "concurrency":
        args.concurrency,

    "scheduler_operating_concurrency":
        decision[
            "operating_concurrency"
        ],

    "exact_operating_point":
        decision[
            "exact_operating_point"
        ],

    "tenants":
        args.tenants,

    "physical_units":
        args.physical_units,

    "requests":
        args.requests,

    "admitted_requests":
        len(admitted),

    "successful_requests":
        len(successful),

    "correct_predictions":
        len(correct),

    "rejected_requests":
        args.requests
        - len(admitted),

    "request_errors":
        len(admitted)
        - len(successful),

    "admission_rate":
        len(admitted)
        / args.requests,

    "error_rate_among_admitted":
        (
            (
                len(admitted)
                - len(successful)
            )
            / len(admitted)
            if admitted
            else None
        ),

    "correctness_rate":
        (
            len(correct)
            / len(successful)
            if successful
            else None
        ),

    "backend_distribution":
        dict(
            sorted(
                backend_distribution.items()
            )
        ),

    "elapsed_seconds":
        elapsed,

    "throughput_rps":
        len(successful)
        / elapsed,

    "mean_latency_ms":
        (
            statistics.mean(
                latencies
            )
            if latencies
            else None
        ),

    "p50_latency_ms":
        percentile(
            latencies,
            50,
        ),

    "p95_latency_ms":
        percentile(
            latencies,
            95,
        ),

    "p99_latency_ms":
        percentile(
            latencies,
            99,
        ),

    "mean_scheduler_decision_ns":
        statistics.mean(
            decision_times
        ),

    "p95_scheduler_decision_ns":
        percentile(
            decision_times,
            95,
        ),

    "mean_server_inference_ns":
        (
            statistics.mean(
                server_inference
            )
            if server_inference
            else None
        ),

    "mean_execution_time_ns":
        (
            statistics.mean(
                server_execution
            )
            if server_execution
            else None
        ),

    "scheduler_decision":
        decision,
}


out = Path(
    args.output
)

out.parent.mkdir(
    parents=True,
    exist_ok=True,
)

out.write_text(
    json.dumps(
        summary,
        indent=2,
    )
    + "\n"
)


print(
    json.dumps(
        summary,
        indent=2,
    )
)
