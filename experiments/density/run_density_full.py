#!/usr/bin/env python3

import argparse
import csv
import json
import math
import os
import signal
import socket
import statistics
import subprocess
import time
import urllib.request
from pathlib import Path

import yaml
from scipy.stats import t as student_t


ROOT = Path(__file__).resolve().parents[2]

CONFIG_PATH = ROOT / "config/experiments.yaml"
MODELS_PATH = ROOT / "config/models.yaml"

RAW_DIR = ROOT / "results/raw/density"
PROCESSED_DIR = ROOT / "results/processed/density"

RAW_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# Supported density workloads
#
# All registered unified-ABI workloads used in the COMET-Wasm
# density experiments are supported here.
# ============================================================

MODEL_RUNTIME = {
    "logistic_regression": {
        "wasm": (
            "wasm/tenant_lr_real/target/"
            "wasm32-unknown-unknown/release/"
            "tenant_lr_real.wasm"
        ),
        "docker_image": "comet-lr-docker:v1",
    },

    "naive_bayes": {
        "wasm": (
            "wasm/tenant_nb_real/target/"
            "wasm32-unknown-unknown/release/"
            "tenant_nb_real.wasm"
        ),
        "docker_image": "comet-nb-docker:v1",
    },

    "decision_tree": {
        "wasm": (
            "wasm/tenant_dt_real/target/"
            "wasm32-unknown-unknown/release/"
            "tenant_dt_real.wasm"
        ),
        "docker_image": "comet-dt-docker:v1",
    },

    "kmeans": {
        "wasm": (
            "wasm/tenant_kmeans_real/target/"
            "wasm32-unknown-unknown/release/"
            "tenant_kmeans_real.wasm"
        ),
        "docker_image": "comet-kmeans-docker:v1",
    },

    "random_forest": {
        "wasm": (
            "wasm/tenant_rf_real/target/"
            "wasm32-unknown-unknown/release/"
            "tenant_rf_real.wasm"
        ),
        "docker_image": "comet-rf-docker:v1",
    },

    "svm": {
        "wasm": (
            "wasm/tenant_svm_real/target/"
            "wasm32-unknown-unknown/release/"
            "tenant_svm_real.wasm"
        ),
        "docker_image": "comet-svm-docker:v1",
    },

    "mlp": {
        "wasm": (
            "wasm/tenant_mlp_real/target/"
            "wasm32-unknown-unknown/release/"
            "tenant_mlp_real.wasm"
        ),
        "docker_image": "comet-mlp-docker:v1",
    },
}


def load_yaml(path):
    with path.open() as f:
        return yaml.safe_load(f)


CONFIG = load_yaml(CONFIG_PATH)
MODELS = load_yaml(MODELS_PATH)

EXP = CONFIG["experiment"]

MIN_REPS = int(EXP["repetitions"]["minimum"])
MAX_REPS = int(EXP["repetitions"]["maximum"])

CONFIDENCE_LEVEL = float(EXP["confidence_level"])
RELATIVE_CI_TARGET = float(EXP["relative_ci_target"])

DENSITY_CFG = EXP["density"]

DEFAULT_LEVELS = [
    int(x)
    for x in DENSITY_CFG["levels"]
]

WARMUP_REQUESTS = int(
    DENSITY_CFG["warmup_requests_per_unit"]
)

MEMORY_SAMPLES = int(
    DENSITY_CFG["memory_samples"]
)

MEMORY_SAMPLE_INTERVAL = float(
    DENSITY_CFG["memory_sample_interval_seconds"]
)

READINESS_TIMEOUT = float(
    DENSITY_CFG["readiness_timeout_seconds"]
)


# ============================================================
# CLI
# ============================================================

parser = argparse.ArgumentParser(
    description=(
        "COMET-Wasm CI-controlled physical "
        "tenant memory-density experiment"
    )
)

parser.add_argument(
    "--backend",
    required=True,
    choices=["wasmtime", "docker"],
)

parser.add_argument(
    "--model",
    required=True,
    choices=sorted(MODEL_RUNTIME),
)

parser.add_argument(
    "--levels",
    nargs="*",
    type=int,
    default=None,
    help=(
        "Optional density levels. "
        "Default comes from config/experiments.yaml"
    ),
)

parser.add_argument(
    "--fresh",
    action="store_true",
    help="Discard any previous raw results for this run.",
)

args = parser.parse_args()

BACKEND = args.backend
MODEL_NAME = args.model
LEVELS = args.levels or DEFAULT_LEVELS


# ============================================================
# Model configuration
# ============================================================

if MODEL_NAME not in MODELS["models"]:
    raise RuntimeError(
        f"{MODEL_NAME} missing from config/models.yaml"
    )

model_cfg = MODELS["models"][MODEL_NAME]

TEST_PATH = ROOT / model_cfg["test_path"]

runtime_cfg = MODEL_RUNTIME[MODEL_NAME]

WASM_PATH = ROOT / runtime_cfg["wasm"]
DOCKER_IMAGE = runtime_cfg["docker_image"]


if not TEST_PATH.exists():
    raise RuntimeError(
        f"Test data missing: {TEST_PATH}"
    )

if BACKEND == "wasmtime" and not WASM_PATH.exists():
    raise RuntimeError(
        f"Wasm artifact missing: {WASM_PATH}"
    )


# ============================================================
# One real workload input
# ============================================================

with TEST_PATH.open() as f:
    sample = next(csv.DictReader(f))


FEATURES = [
    float(v)
    for k, v in sample.items()
    if k not in ("label", "target")
]


# ============================================================
# Output paths
# ============================================================

STEM = f"{BACKEND}_{MODEL_NAME}_density_full"

RAW_CSV = RAW_DIR / f"{STEM}.csv"

SUMMARY_JSON = (
    PROCESSED_DIR
    / f"{STEM}_summary.json"
)


# ============================================================
# Ports / process names
# ============================================================

WASMTIME_PORT = 8100

DOCKER_BASE_PORT = 8300

DOCKER_PREFIX = (
    f"comet-density-{MODEL_NAME}"
)

SERVER = (
    ROOT
    / "serving"
    / "multitenant_server"
    / "target"
    / "release"
    / "comet_multitenant_server"
)


# ============================================================
# Generic helpers
# ============================================================

def run(cmd, check=True):
    return subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=check,
    )


def port_free(port):
    with socket.socket(
        socket.AF_INET,
        socket.SOCK_STREAM
    ) as s:
        return (
            s.connect_ex(
                ("127.0.0.1", port)
            )
            != 0
        )


def post_json(url, body):
    payload = json.dumps(body).encode()

    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json"
        },
        method="POST",
    )

    with urllib.request.urlopen(
        req,
        timeout=10
    ) as r:
        return json.loads(
            r.read()
        )


# ============================================================
# Wasmtime lifecycle
# ============================================================

def start_wasmtime(level):

    if not port_free(WASMTIME_PORT):
        raise RuntimeError(
            f"Port {WASMTIME_PORT} is already in use"
        )

    proc = subprocess.Popen(
        [
            str(SERVER),
            MODEL_NAME,
            str(WASM_PATH),
            str(level),
            str(WASMTIME_PORT),
        ],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )

    return proc


def stop_wasmtime(proc):

    if proc.poll() is not None:
        return

    proc.send_signal(
        signal.SIGTERM
    )

    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def wait_wasmtime_ready(proc):

    deadline = (
        time.time()
        + READINESS_TIMEOUT
    )

    while time.time() < deadline:

        if proc.poll() is not None:
            raise RuntimeError(
                "Wasmtime server exited "
                "during startup"
            )

        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:"
                f"{WASMTIME_PORT}/health",
                timeout=1,
            ) as r:

                if r.status == 200:
                    return

        except Exception:
            pass

        time.sleep(0.05)

    raise RuntimeError(
        "Wasmtime readiness timeout"
    )


def infer_wasmtime(tenant_id):

    return post_json(
        f"http://127.0.0.1:"
        f"{WASMTIME_PORT}/infer",
        {
            "tenant_id": tenant_id,
            "features": FEATURES,
        }
    )


def warm_wasmtime(level):

    for worker in range(level):

        for _ in range(
            WARMUP_REQUESTS
        ):

            result = infer_wasmtime(
                worker
            )

            if (
                int(result["worker_id"])
                != worker
            ):
                raise RuntimeError(
                    "Wasmtime tenant-worker "
                    f"mapping error: {result}"
                )


def process_memory(pid):

    path = Path(
        f"/proc/{pid}/smaps_rollup"
    )

    values = {}

    for line in (
        path.read_text()
        .splitlines()
    ):

        parts = line.split()

        if (
            len(parts) >= 2
            and parts[0].endswith(":")
        ):

            try:
                values[
                    parts[0][:-1]
                ] = int(parts[1])

            except ValueError:
                pass

    return {
        "rss_mib":
            values.get(
                "Rss",
                0
            ) / 1024.0,

        "pss_mib":
            values.get(
                "Pss",
                0
            ) / 1024.0,

        "private_mib":
            (
                values.get(
                    "Private_Clean",
                    0
                )
                +
                values.get(
                    "Private_Dirty",
                    0
                )
            ) / 1024.0,
    }


# ============================================================
# Docker lifecycle
# ============================================================

def docker_name(index):

    return (
        f"{DOCKER_PREFIX}-{index}"
    )


def docker_port(index):

    return (
        DOCKER_BASE_PORT
        + index
    )


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
        for x
        in result.stdout.splitlines()
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


def start_docker(level):

    docker_cleanup()

    for i in range(level):

        port = docker_port(i)

        if not port_free(port):
            raise RuntimeError(
                f"Docker experiment port "
                f"{port} already in use"
            )

        result = run(
            [
                "docker",
                "run",
                "-d",
                "--rm",
                "--name",
                docker_name(i),
                "-p",
                f"{port}:8085",
                DOCKER_IMAGE,
            ],
            check=False,
        )

        if result.returncode != 0:
            docker_cleanup()

            raise RuntimeError(
                "Docker start failed:\n"
                + result.stderr
            )


def infer_docker(index):

    return post_json(
        f"http://127.0.0.1:"
        f"{docker_port(index)}/infer",
        {
            "features": FEATURES
        }
    )


def wait_docker_ready(level):

    pending = set(
        range(level)
    )

    deadline = (
        time.time()
        + READINESS_TIMEOUT
    )

    while (
        pending
        and time.time() < deadline
    ):

        completed = []

        for i in pending:

            try:
                result = infer_docker(i)

                if "prediction" in result:
                    completed.append(i)

            except Exception:
                pass

        for i in completed:
            pending.remove(i)

        if pending:
            time.sleep(0.05)

    if pending:
        docker_cleanup()

        raise RuntimeError(
            "Docker readiness timeout. "
            "Unavailable containers: "
            + str(sorted(pending))
        )


def warm_docker(level):

    for index in range(level):

        for _ in range(
            WARMUP_REQUESTS
        ):
            infer_docker(index)


def docker_memory(container):

    result = run(
        [
            "docker",
            "exec",
            container,
            "cat",
            "/proc/1/smaps_rollup",
        ],
        check=False,
    )

    if result.returncode != 0:

        raise RuntimeError(
            "Unable to read memory for "
            f"{container}:\n"
            + result.stderr
        )

    values = {}

    for line in (
        result.stdout
        .splitlines()
    ):

        parts = line.split()

        if (
            len(parts) >= 2
            and parts[0].endswith(":")
        ):

            try:
                values[
                    parts[0][:-1]
                ] = int(parts[1])

            except ValueError:
                pass

    return {
        "rss_mib":
            values.get(
                "Rss",
                0
            ) / 1024.0,

        "pss_mib":
            values.get(
                "Pss",
                0
            ) / 1024.0,

        "private_mib":
            (
                values.get(
                    "Private_Clean",
                    0
                )
                +
                values.get(
                    "Private_Dirty",
                    0
                )
            ) / 1024.0,
    }


# ============================================================
# Memory snapshots
# ============================================================

def measure_wasmtime(pid):

    rss = []
    pss = []
    private = []

    for _ in range(
        MEMORY_SAMPLES
    ):

        m = process_memory(
            pid
        )

        rss.append(
            m["rss_mib"]
        )

        pss.append(
            m["pss_mib"]
        )

        private.append(
            m["private_mib"]
        )

        time.sleep(
            MEMORY_SAMPLE_INTERVAL
        )

    return {
        "rss_mib":
            statistics.mean(rss),

        "pss_mib":
            statistics.mean(pss),

        "private_mib":
            statistics.mean(private),
    }


def measure_docker(level):

    rss_snapshots = []
    pss_snapshots = []
    private_snapshots = []

    names = [
        docker_name(i)
        for i in range(level)
    ]

    for _ in range(
        MEMORY_SAMPLES
    ):

        rss_total = 0.0
        pss_total = 0.0
        private_total = 0.0

        for name in names:

            m = docker_memory(
                name
            )

            rss_total += (
                m["rss_mib"]
            )

            pss_total += (
                m["pss_mib"]
            )

            private_total += (
                m["private_mib"]
            )

        rss_snapshots.append(
            rss_total
        )

        pss_snapshots.append(
            pss_total
        )

        private_snapshots.append(
            private_total
        )

        time.sleep(
            MEMORY_SAMPLE_INTERVAL
        )

    return {
        "rss_mib":
            statistics.mean(
                rss_snapshots
            ),

        "pss_mib":
            statistics.mean(
                pss_snapshots
            ),

        "private_mib":
            statistics.mean(
                private_snapshots
            ),
    }


# ============================================================
# Confidence interval
# ============================================================

def ci_stats(values):

    n = len(values)

    if n == 0:
        return {
            "n": 0,
            "mean": 0.0,
            "sd": 0.0,
            "halfwidth": math.inf,
            "lower": None,
            "upper": None,
            "relative_halfwidth": math.inf,
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
            "lower": None,
            "upper": None,
            "relative_halfwidth": math.inf,
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
        "lower": mean - halfwidth,
        "upper": mean + halfwidth,
        "relative_halfwidth": relative,
    }


# ============================================================
# Raw result persistence / resume support
# ============================================================

FIELDS = [
    "backend",
    "model",
    "physical_tenants",
    "repetition",
    "rss_mib",
    "pss_mib",
    "private_mib",
    "warmup_requests_per_unit",
    "memory_samples",
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

    exists = RAW_CSV.exists()

    with RAW_CSV.open(
        "a",
        newline=""
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=FIELDS,
        )

        if not exists:
            writer.writeheader()

        writer.writerow(row)


existing = load_existing()


# ============================================================
# One clean repetition
# ============================================================

def run_repetition(level):

    if BACKEND == "wasmtime":

        proc = start_wasmtime(
            level
        )

        try:
            wait_wasmtime_ready(
                proc
            )

            warm_wasmtime(
                level
            )

            return measure_wasmtime(
                proc.pid
            )

        finally:
            stop_wasmtime(
                proc
            )

            time.sleep(0.5)

    else:

        start_docker(
            level
        )

        try:

            wait_docker_ready(
                level
            )

            warm_docker(
                level
            )

            return measure_docker(
                level
            )

        finally:

            docker_cleanup()

            time.sleep(0.5)


# ============================================================
# Full experiment
# ============================================================

print()
print("=" * 72)
print("COMET-Wasm FULL DENSITY EXPERIMENT")
print("=" * 72)

print("Backend:", BACKEND)
print("Model:", MODEL_NAME)
print("Levels:", LEVELS)
print("Minimum repetitions:", MIN_REPS)
print("Maximum repetitions:", MAX_REPS)
print(
    "Relative 95% CI target:",
    f"{RELATIVE_CI_TARGET * 100:.2f}%"
)
print(
    "Warm-up requests/unit:",
    WARMUP_REQUESTS
)
print("Raw CSV:", RAW_CSV)
print()


final_summary = {}


try:

    for level in LEVELS:

        print()
        print("=" * 72)
        print(
            f"PHYSICAL TENANTS = {level}"
        )
        print("=" * 72)

        previous = [
            r for r in existing
            if (
                r["backend"] == BACKEND
                and r["model"] == MODEL_NAME
                and int(
                    r["physical_tenants"]
                ) == level
            )
        ]

        pss_values = [
            float(r["pss_mib"])
            for r in previous
        ]

        repetition = (
            max(
                [
                    int(r["repetition"])
                    for r in previous
                ],
                default=0,
            )
            + 1
        )

        if previous:
            print(
                f"Resuming with "
                f"{len(previous)} existing repetitions."
            )

        while True:

            current = ci_stats(
                pss_values
            )

            if (
                len(pss_values) >= MIN_REPS
                and current[
                    "relative_halfwidth"
                ] <= RELATIVE_CI_TARGET
            ):

                print(
                    "CI target already satisfied."
                )
                break

            if (
                len(pss_values)
                >= MAX_REPS
            ):
                print(
                    "Maximum repetitions reached."
                )
                break

            m = run_repetition(
                level
            )

            row = {
                "backend":
                    BACKEND,

                "model":
                    MODEL_NAME,

                "physical_tenants":
                    level,

                "repetition":
                    repetition,

                "rss_mib":
                    f"{m['rss_mib']:.9f}",

                "pss_mib":
                    f"{m['pss_mib']:.9f}",

                "private_mib":
                    f"{m['private_mib']:.9f}",

                "warmup_requests_per_unit":
                    WARMUP_REQUESTS,

                "memory_samples":
                    MEMORY_SAMPLES,

                "timestamp_unix":
                    f"{time.time():.6f}",
            }

            append_raw(
                row
            )

            pss_values.append(
                m["pss_mib"]
            )

            current = ci_stats(
                pss_values
            )

            print(
                f"rep={repetition:02d} | "
                f"PSS={m['pss_mib']:.3f} MiB | "
                f"mean={current['mean']:.3f} | "
                f"CI±={current['halfwidth']:.4f} | "
                f"relative="
                f"{current['relative_halfwidth']*100:.3f}%"
            )

            repetition += 1


        stats = ci_stats(
            pss_values
        )

        final_summary[
            str(level)
        ] = {
            "physical_tenants":
                level,

            "repetitions":
                stats["n"],

            "pss_mean_mib":
                stats["mean"],

            "pss_sd_mib":
                stats["sd"],

            "ci95_halfwidth_mib":
                stats["halfwidth"],

            "ci95_lower_mib":
                stats["lower"],

            "ci95_upper_mib":
                stats["upper"],

            "relative_ci_halfwidth":
                stats[
                    "relative_halfwidth"
                ],

            "ci_target_met":
                bool(
                    stats["n"]
                    >= MIN_REPS
                    and stats[
                        "relative_halfwidth"
                    ]
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

                    "confidence_level":
                        CONFIDENCE_LEVEL,

                    "relative_ci_target":
                        RELATIVE_CI_TARGET,

                    "minimum_repetitions":
                        MIN_REPS,

                    "maximum_repetitions":
                        MAX_REPS,

                    "density_levels":
                        LEVELS,

                    "summary":
                        final_summary,
                },
                indent=2,
            )
        )


finally:

    if BACKEND == "docker":
        docker_cleanup()


print()
print("=" * 72)
print("FULL DENSITY SUMMARY")
print("=" * 72)

for level in LEVELS:

    s = final_summary[
        str(level)
    ]

    print(
        f"{level:>3} tenants | "
        f"n={s['repetitions']:>2} | "
        f"PSS={s['pss_mean_mib']:.3f} MiB | "
        f"95% CI ±{s['ci95_halfwidth_mib']:.4f} | "
        f"rel={s['relative_ci_halfwidth']*100:.3f}% | "
        f"target="
        f"{'PASS' if s['ci_target_met'] else 'MAX-REPS'}"
    )

print()
print("Raw CSV:", RAW_CSV)
print("Summary JSON:", SUMMARY_JSON)
print()
print("FULL DENSITY EXPERIMENT: COMPLETE")
