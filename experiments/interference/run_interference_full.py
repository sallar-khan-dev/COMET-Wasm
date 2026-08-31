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
import urllib.request
from pathlib import Path

from scipy.stats import t as student_t


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
    / "interference"
    / "load_client_interference.py"
)

PYTHON = (
    ROOT
    / ".venv"
    / "bin"
    / "python"
)


# ============================================================
# Frozen protocol
# ============================================================

PHYSICAL_UNITS = 20
CONCURRENCY = 32
REQUESTS = 5000

MIN_REPS = 20
MAX_REPS = 60

CI_TARGET = 0.025

COOLDOWN_SECONDS = 1.0

SERVER_CPUSET = ",".join(
    str(i)
    for i in range(
        0,
        128,
        2,
    )
)

CLIENT_CPUSET = ",".join(
    str(i)
    for i in range(
        1,
        128,
        2,
    )
)

WASM_PORT_A = 8100
WASM_PORT_B = 8200

DOCKER_PORT_A = 8300
DOCKER_PORT_B = 8500


PAIRS = {
    "nb_nb": (
        "naive_bayes",
        "naive_bayes",
    ),

    "lr_lr": (
        "logistic_regression",
        "logistic_regression",
    ),

    "lr_svm": (
        "logistic_regression",
        "svm",
    ),

    "kmeans_rf": (
        "kmeans",
        "random_forest",
    ),

    "dt_mlp": (
        "decision_tree",
        "mlp",
    ),

    "svm_mlp": (
        "svm",
        "mlp",
    ),
}


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
    "--pair",
    required=True,
    choices=sorted(PAIRS),
)

parser.add_argument(
    "--fresh",
    action="store_true",
)

parser.add_argument(
    "--smoke",
    action="store_true",
    help=(
        "Lifecycle/client smoke test only. "
        "Does not create scientific result files."
    ),
)

args = parser.parse_args()

BACKEND = args.backend
PAIR_NAME = args.pair

MODEL_A, MODEL_B = (
    PAIRS[PAIR_NAME]
)

CFG_A = get_model(
    MODEL_A
)

CFG_B = get_model(
    MODEL_B
)


# ============================================================
# Output
# ============================================================

RAW_DIR = (
    ROOT
    / "results"
    / "raw"
    / "interference"
)

PROC_DIR = (
    ROOT
    / "results"
    / "processed"
    / "interference"
)

RAW_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

PROC_DIR.mkdir(
    parents=True,
    exist_ok=True,
)


PAIR_RAW = (
    RAW_DIR
    / (
        f"{BACKEND}_{PAIR_NAME}_"
        "interference_full.csv"
    )
)

PAIR_SUMMARY = (
    PROC_DIR
    / (
        f"{BACKEND}_{PAIR_NAME}_"
        "interference_full_summary.json"
    )
)


# ============================================================
# Statistics
# ============================================================

def ci_stats(
    values,
):

    values = [
        float(x)
        for x in values
    ]

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
# Helpers
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


def wait_health(
    port,
    proc,
):

    deadline = (
        time.time()
        + 20
    )

    while time.time() < deadline:

        if proc.poll() is not None:

            raise RuntimeError(
                f"Wasmtime server on {port} exited"
            )

        try:

            with urllib.request.urlopen(
                f"http://127.0.0.1:"
                f"{port}/health",
                timeout=1,
            ) as r:

                if r.status == 200:
                    return

        except Exception:
            pass

        time.sleep(
            0.05
        )

    raise RuntimeError(
        f"Wasmtime readiness timeout "
        f"on port {port}"
    )


# ============================================================
# Wasmtime service lifecycle
# ============================================================

def start_wasm_service(
    model,
    cfg,
    port,
):

    proc = subprocess.Popen(
        [
            "taskset",
            "-c",
            SERVER_CPUSET,

            str(SERVER),

            model,

            str(
                cfg[
                    "wasm_artifact_abs"
                ]
            ),

            str(
                PHYSICAL_UNITS
            ),

            str(port),
        ],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )

    wait_health(
        port,
        proc,
    )

    return proc


def stop_proc(
    proc,
):

    if proc is None:
        return

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

def docker_prefix(
    slot,
):

    return (
        f"comet-interference-"
        f"{BACKEND}-{PAIR_NAME}-{slot}"
    )


def docker_name(
    slot,
    index,
):

    return (
        f"{docker_prefix(slot)}-"
        f"{index}"
    )


def docker_cleanup():

    for slot in [
        "a",
        "b",
    ]:

        result = run(
            [
                "docker",
                "ps",
                "-aq",
                "--filter",
                (
                    "name="
                    + docker_prefix(slot)
                ),
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
                    *ids,
                ],
                check=False,
            )


def start_docker_pool(
    slot,
    cfg,
    base_port,
):

    image = cfg[
        "docker_image"
    ]

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
                docker_name(
                    slot,
                    i,
                ),

                "-p",
                (
                    f"{base_port+i}:"
                    "8085"
                ),

                image,
            ],
            check=False,
        )

        if result.returncode != 0:

            docker_cleanup()

            raise RuntimeError(
                result.stderr
            )

    # Readiness via inference.
    deadline = (
        time.time()
        + 30
    )

    pending = set(
        range(
            PHYSICAL_UNITS
        )
    )

    features = [
        0.0
    ] * int(
        cfg["features"]
    )

    while (
        pending
        and time.time() < deadline
    ):

        done = []

        for i in pending:

            try:

                body = json.dumps({
                    "features":
                        features
                }).encode()

                req = urllib.request.Request(
                    (
                        "http://127.0.0.1:"
                        f"{base_port+i}/infer"
                    ),
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
            time.sleep(
                0.05
            )

    if pending:

        docker_cleanup()

        raise RuntimeError(
            "Docker readiness timeout"
        )


# ============================================================
# Execute client
# ============================================================

def run_client(
    model_a,
    port_a,
    model_b=None,
    port_b=None,
):

    with tempfile.NamedTemporaryFile(
        suffix=".json",
        delete=False,
    ) as tmp:

        output = tmp.name

    cmd = [
        "taskset",
        "-c",
        CLIENT_CPUSET,

        str(PYTHON),

        str(CLIENT),

        "--backend",
        BACKEND,

        "--model-a",
        model_a,

        "--port-a",
        str(port_a),

        "--physical-units",
        str(PHYSICAL_UNITS),

        "--concurrency",
        str(CONCURRENCY),

        "--requests",
        str(REQUESTS),

        "--output",
        output,
    ]

    if model_b is not None:

        cmd.extend([
            "--model-b",
            model_b,

            "--port-b",
            str(port_b),
        ])

    try:

        result = run(
            cmd,
            check=False,
        )

        if result.returncode != 0:

            raise RuntimeError(
                "Interference client failed:\n"
                + result.stdout
                + "\n"
                + result.stderr
            )

        return json.loads(
            Path(
                output
            ).read_text()
        )

    finally:

        Path(
            output
        ).unlink(
            missing_ok=True
        )


# ============================================================
# Solo baseline cache
# ============================================================

def solo_paths(
    model,
):

    raw = (
        RAW_DIR
        / (
            f"{BACKEND}_{model}_"
            "interference_solo.csv"
        )
    )

    summary = (
        PROC_DIR
        / (
            f"{BACKEND}_{model}_"
            "interference_solo_summary.json"
        )
    )

    return (
        raw,
        summary,
    )


SOLO_FIELDS = [
    "backend",
    "model",
    "repetition",
    "throughput_rps",
    "p95_latency_ms",
    "p99_latency_ms",
    "error_rate",
    "timestamp_unix",
]


def append_csv(
    path,
    fields,
    row,
):

    exists = path.exists()

    with path.open(
        "a",
        newline="",
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=fields,
        )

        if not exists:
            writer.writeheader()

        writer.writerow(
            row
        )


def load_csv(
    path,
):

    if not path.exists():
        return []

    with path.open() as f:

        return list(
            csv.DictReader(f)
        )


# ============================================================
# One solo repetition
# ============================================================

def solo_repetition(
    model,
    cfg,
):

    proc = None

    try:

        if BACKEND == "wasmtime":

            proc = start_wasm_service(
                model,
                cfg,
                WASM_PORT_A,
            )

            data = run_client(
                model,
                WASM_PORT_A,
            )

        else:

            docker_cleanup()

            start_docker_pool(
                "a",
                cfg,
                DOCKER_PORT_A,
            )

            data = run_client(
                model,
                DOCKER_PORT_A,
            )

        return data[
            "stream_a"
        ]

    finally:

        stop_proc(
            proc
        )

        if BACKEND == "docker":
            docker_cleanup()


# ============================================================
# Ensure solo baseline
# ============================================================

def ensure_solo(
    model,
    cfg,
):

    raw_path, summary_path = (
        solo_paths(
            model
        )
    )

    rows = load_csv(
        raw_path
    )

    values_p95 = [
        float(r["p95_latency_ms"])
        for r in rows
    ]

    values_thr = [
        float(r["throughput_rps"])
        for r in rows
    ]

    def stable():

        if len(rows) < MIN_REPS:
            return False

        return (
            ci_stats(
                values_p95
            )["relative"]
            <= CI_TARGET
            and
            ci_stats(
                values_thr
            )["relative"]
            <= CI_TARGET
        )

    if stable():

        print(
            f"Solo baseline cached: "
            f"{BACKEND}/{model}"
        )

    else:

        for rep in range(
            len(rows) + 1,
            MAX_REPS + 1,
        ):

            d = solo_repetition(
                model,
                cfg,
            )

            row = {
                "backend":
                    BACKEND,

                "model":
                    model,

                "repetition":
                    rep,

                "throughput_rps":
                    d[
                        "throughput_rps"
                    ],

                "p95_latency_ms":
                    d[
                        "p95_latency_ms"
                    ],

                "p99_latency_ms":
                    d[
                        "p99_latency_ms"
                    ],

                "error_rate":
                    d[
                        "error_rate"
                    ],

                "timestamp_unix":
                    time.time(),
            }

            append_csv(
                raw_path,
                SOLO_FIELDS,
                row,
            )

            rows.append(
                {
                    k: str(v)
                    for k, v
                    in row.items()
                }
            )

            values_p95.append(
                float(
                    d["p95_latency_ms"]
                )
            )

            values_thr.append(
                float(
                    d["throughput_rps"]
                )
            )

            p95_ci = ci_stats(
                values_p95
            )

            thr_ci = ci_stats(
                values_thr
            )

            print(
                f"SOLO {model} "
                f"rep={rep:02d} | "
                f"P95="
                f"{d['p95_latency_ms']:.3f} ms | "
                f"Thr="
                f"{d['throughput_rps']:.1f} | "
                f"CI P95="
                f"{p95_ci['relative']*100:.2f}% | "
                f"CI Thr="
                f"{thr_ci['relative']*100:.2f}%"
            )

            if (
                rep >= MIN_REPS
                and
                p95_ci["relative"]
                <= CI_TARGET
                and
                thr_ci["relative"]
                <= CI_TARGET
            ):

                break

            time.sleep(
                COOLDOWN_SECONDS
            )

    # Reload.
    rows = load_csv(
        raw_path
    )

    summary = {
        "backend":
            BACKEND,

        "model":
            model,

        "repetitions":
            len(rows),

        "physical_units":
            PHYSICAL_UNITS,

        "concurrency":
            CONCURRENCY,

        "requests_per_repetition":
            REQUESTS,

        "p95_latency_ms":
            ci_stats(
                [
                    float(
                        r[
                            "p95_latency_ms"
                        ]
                    )
                    for r in rows
                ]
            ),

        "throughput_rps":
            ci_stats(
                [
                    float(
                        r[
                            "throughput_rps"
                        ]
                    )
                    for r in rows
                ]
            ),

        "p99_latency_ms_mean":
            statistics.mean(
                [
                    float(
                        r[
                            "p99_latency_ms"
                        ]
                    )
                    for r in rows
                ]
            ),

        "error_rate_mean":
            statistics.mean(
                [
                    float(
                        r[
                            "error_rate"
                        ]
                    )
                    for r in rows
                ]
            ),
    }

    summary[
        "ci_pass"
    ] = bool(
        summary[
            "p95_latency_ms"
        ]["relative"]
        <= CI_TARGET
        and
        summary[
            "throughput_rps"
        ]["relative"]
        <= CI_TARGET
    )

    summary_path.write_text(
        json.dumps(
            summary,
            indent=2,
        )
    )

    return summary


# ============================================================
# Mixed repetition
# ============================================================

def mixed_repetition():

    proc_a = None
    proc_b = None

    try:

        if BACKEND == "wasmtime":

            proc_a = start_wasm_service(
                MODEL_A,
                CFG_A,
                WASM_PORT_A,
            )

            proc_b = start_wasm_service(
                MODEL_B,
                CFG_B,
                WASM_PORT_B,
            )

            data = run_client(
                MODEL_A,
                WASM_PORT_A,
                MODEL_B,
                WASM_PORT_B,
            )

        else:

            docker_cleanup()

            start_docker_pool(
                "a",
                CFG_A,
                DOCKER_PORT_A,
            )

            start_docker_pool(
                "b",
                CFG_B,
                DOCKER_PORT_B,
            )

            data = run_client(
                MODEL_A,
                DOCKER_PORT_A,
                MODEL_B,
                DOCKER_PORT_B,
            )

        return data

    finally:

        stop_proc(
            proc_a
        )

        stop_proc(
            proc_b
        )

        if BACKEND == "docker":
            docker_cleanup()


# ============================================================
# Pair persistence
# ============================================================

PAIR_FIELDS = [
    "backend",
    "pair",
    "model_a",
    "model_b",
    "repetition",

    "a_throughput_rps",
    "a_p95_latency_ms",
    "a_p99_latency_ms",
    "a_error_rate",

    "b_throughput_rps",
    "b_p95_latency_ms",
    "b_p99_latency_ms",
    "b_error_rate",

    "timestamp_unix",
]


# ============================================================
# Smoke
# ============================================================

if args.smoke:

    print(
        "Running lifecycle/client smoke test..."
    )

    data = mixed_repetition()

    print(
        json.dumps(
            data,
            indent=2,
        )
    )

    print(
        "INTERFERENCE SMOKE TEST: PASS"
    )

    raise SystemExit(0)


# ============================================================
# Fresh handling
# ============================================================

if args.fresh:

    PAIR_RAW.unlink(
        missing_ok=True
    )

    PAIR_SUMMARY.unlink(
        missing_ok=True
    )

    # Important:
    # Do NOT delete solo caches.
    # They are shared between pairs and generated
    # using the same frozen protocol.


# ============================================================
# Solo baselines
# ============================================================

print()
print("=" * 78)
print("COMET-Wasm INTERFERENCE EXPERIMENT")
print("=" * 78)

print(
    f"Backend: {BACKEND}"
)

print(
    f"Pair: {PAIR_NAME}"
)

print(
    f"Models: {MODEL_A} + {MODEL_B}"
)

print(
    "Physical units/model: 20"
)

print(
    "Concurrency/model: 32"
)

print(
    "Requests/model/repetition: 5000"
)

print(
    "Total mixed concurrency: 64"
)

print(
    "Total mixed requests/repetition: 10000"
)

print(
    "Primary CI metrics: P95 + throughput"
)

print()


solo_a = ensure_solo(
    MODEL_A,
    CFG_A,
)

solo_b = (
    solo_a
    if MODEL_A == MODEL_B
    else ensure_solo(
        MODEL_B,
        CFG_B,
    )
)


if not solo_a["ci_pass"]:

    print(
        f"WARNING: {MODEL_A} solo baseline reached "
        f"MAX_REPS={MAX_REPS} without satisfying "
        f"the 2.5% CI target. Continuing with the "
        f"measured dataset and flagging it transparently."
    )

if not solo_b["ci_pass"]:

    print(
        f"WARNING: {MODEL_B} solo baseline reached "
        f"MAX_REPS={MAX_REPS} without satisfying "
        f"the 2.5% CI target. Continuing with the "
        f"measured dataset and flagging it transparently."
    )


# ============================================================
# Mixed experiment
# ============================================================

rows = load_csv(
    PAIR_RAW
)


def column_values(
    name,
):

    return [
        float(
            r[name]
        )
        for r in rows
    ]


def mixed_stable():

    if len(rows) < MIN_REPS:
        return False

    metrics = [
        "a_p95_latency_ms",
        "a_throughput_rps",
        "b_p95_latency_ms",
        "b_throughput_rps",
    ]

    return all(
        ci_stats(
            column_values(
                metric
            )
        )["relative"]
        <= CI_TARGET

        for metric in metrics
    )


if mixed_stable():

    print(
        "Existing mixed dataset already "
        "satisfies CI."
    )

else:

    for rep in range(
        len(rows) + 1,
        MAX_REPS + 1,
    ):

        data = (
            mixed_repetition()
        )

        a = data[
            "stream_a"
        ]

        b = data[
            "stream_b"
        ]

        row = {
            "backend":
                BACKEND,

            "pair":
                PAIR_NAME,

            "model_a":
                MODEL_A,

            "model_b":
                MODEL_B,

            "repetition":
                rep,

            "a_throughput_rps":
                a[
                    "throughput_rps"
                ],

            "a_p95_latency_ms":
                a[
                    "p95_latency_ms"
                ],

            "a_p99_latency_ms":
                a[
                    "p99_latency_ms"
                ],

            "a_error_rate":
                a[
                    "error_rate"
                ],

            "b_throughput_rps":
                b[
                    "throughput_rps"
                ],

            "b_p95_latency_ms":
                b[
                    "p95_latency_ms"
                ],

            "b_p99_latency_ms":
                b[
                    "p99_latency_ms"
                ],

            "b_error_rate":
                b[
                    "error_rate"
                ],

            "timestamp_unix":
                time.time(),
        }

        append_csv(
            PAIR_RAW,
            PAIR_FIELDS,
            row,
        )

        rows.append(
            {
                k: str(v)
                for k, v
                in row.items()
            }
        )

        a_p95 = ci_stats(
            column_values(
                "a_p95_latency_ms"
            )
        )

        a_thr = ci_stats(
            column_values(
                "a_throughput_rps"
            )
        )

        b_p95 = ci_stats(
            column_values(
                "b_p95_latency_ms"
            )
        )

        b_thr = ci_stats(
            column_values(
                "b_throughput_rps"
            )
        )

        print(
            f"rep={rep:02d} | "
            f"A P95="
            f"{a['p95_latency_ms']:.3f} | "
            f"A Thr="
            f"{a['throughput_rps']:.1f} | "
            f"B P95="
            f"{b['p95_latency_ms']:.3f} | "
            f"B Thr="
            f"{b['throughput_rps']:.1f} | "
            f"CI="
            f"{a_p95['relative']*100:.2f}/"
            f"{a_thr['relative']*100:.2f}/"
            f"{b_p95['relative']*100:.2f}/"
            f"{b_thr['relative']*100:.2f}%"
        )

        if (
            rep >= MIN_REPS
            and mixed_stable()
        ):

            print(
                "Mixed CI targets satisfied."
            )

            break

        time.sleep(
            COOLDOWN_SECONDS
        )


# ============================================================
# Final summary
# ============================================================

rows = load_csv(
    PAIR_RAW
)


def summarize_stream(
    prefix,
    solo,
):

    p95 = ci_stats(
        column_values(
            f"{prefix}_p95_latency_ms"
        )
    )

    thr = ci_stats(
        column_values(
            f"{prefix}_throughput_rps"
        )
    )

    p99_mean = (
        statistics.mean(
            column_values(
                f"{prefix}_p99_latency_ms"
            )
        )
    )

    error_mean = (
        statistics.mean(
            column_values(
                f"{prefix}_error_rate"
            )
        )
    )

    solo_p95 = (
        solo[
            "p95_latency_ms"
        ]["mean"]
    )

    solo_thr = (
        solo[
            "throughput_rps"
        ]["mean"]
    )

    p95_degradation = (
        (
            p95["mean"]
            - solo_p95
        )
        / solo_p95
        * 100.0
    )

    throughput_degradation = (
        (
            solo_thr
            - thr["mean"]
        )
        / solo_thr
        * 100.0
    )

    return {
        "mixed_p95_latency_ms":
            p95,

        "mixed_throughput_rps":
            thr,

        "mixed_p99_latency_ms_mean":
            p99_mean,

        "mixed_error_rate_mean":
            error_mean,

        "solo_p95_latency_ms":
            solo_p95,

        "solo_throughput_rps":
            solo_thr,

        "p95_degradation_pct":
            p95_degradation,

        "throughput_degradation_pct":
            throughput_degradation,
    }


summary = {
    "backend":
        BACKEND,

    "pair":
        PAIR_NAME,

    "model_a":
        MODEL_A,

    "model_b":
        MODEL_B,

    "physical_units_per_model":
        PHYSICAL_UNITS,

    "concurrency_per_model":
        CONCURRENCY,

    "requests_per_model_per_repetition":
        REQUESTS,

    "total_mixed_concurrency":
        CONCURRENCY * 2,

    "total_mixed_requests_per_repetition":
        REQUESTS * 2,

    "repetitions":
        len(rows),

    "ci_target":
        CI_TARGET,

    "stream_a":
        summarize_stream(
            "a",
            solo_a,
        ),

    "stream_b":
        summarize_stream(
            "b",
            solo_b,
        ),
}


summary[
    "ci_pass"
] = bool(
    mixed_stable()
)


PAIR_SUMMARY.write_text(
    json.dumps(
        summary,
        indent=2,
    )
)


print()
print("=" * 78)
print("INTERFERENCE SUMMARY")
print("=" * 78)

print(
    f"n={summary['repetitions']}"
)

print(
    f"{MODEL_A}: "
    f"P95 degradation="
    f"{summary['stream_a']['p95_degradation_pct']:.2f}% | "
    f"Throughput degradation="
    f"{summary['stream_a']['throughput_degradation_pct']:.2f}%"
)

print(
    f"{MODEL_B}: "
    f"P95 degradation="
    f"{summary['stream_b']['p95_degradation_pct']:.2f}% | "
    f"Throughput degradation="
    f"{summary['stream_b']['throughput_degradation_pct']:.2f}%"
)

print(
    "CI pass:",
    summary["ci_pass"]
)

print(
    "Summary:",
    PAIR_SUMMARY
)

print()
print(
    "INTERFERENCE EXPERIMENT: COMPLETE"
)

