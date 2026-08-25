#!/usr/bin/env python3

import csv
import json
import statistics
import subprocess
import time
import urllib.request
from pathlib import Path

# ============================================================
# COMET-Wasm Docker Naive Bayes Density Pilot
# ============================================================

ROOT = Path(__file__).resolve().parents[2]

IMAGE = "comet-nb-docker:v1"
NAME_PREFIX = "comet-nb-density"
BASE_PORT = 8300

CONTAINER_LEVELS = [1, 5, 10, 20]
REPETITIONS = 5
MEMORY_SAMPLES = 5

STARTUP_WAIT_SECONDS = 0.2
MEMORY_SAMPLE_INTERVAL = 0.1

DATA_PATH = (
    ROOT
    / "models"
    / "naive_bayes"
    / "breast_cancer"
    / "test_samples.csv"
)

OUT_DIR = ROOT / "results" / "raw" / "density"
OUT_DIR.mkdir(parents=True, exist_ok=True)

CSV_PATH = OUT_DIR / "docker_nb_density_pilot.csv"
JSON_PATH = OUT_DIR / "docker_nb_density_pilot.json"


# ============================================================
# Utility functions
# ============================================================

def run(cmd, check=True):
    return subprocess.run(
        cmd,
        check=check,
        capture_output=True,
        text=True,
    )


def container_name(index):
    return f"{NAME_PREFIX}-{index}"


def container_port(index):
    return BASE_PORT + index


def get_container_names(count):
    return [
        container_name(i)
        for i in range(count)
    ]


# ============================================================
# Load one real NB test sample
# ============================================================

with DATA_PATH.open() as f:
    row = next(csv.DictReader(f))

FEATURES = [
    float(v)
    for k, v in row.items()
    if k != "label"
]

EXPECTED_LABEL = int(row["label"])


# ============================================================
# Docker lifecycle
# ============================================================

def remove_existing():
    result = run(
        [
            "docker",
            "ps",
            "-aq",
            "--filter",
            f"name={NAME_PREFIX}-",
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
            ["docker", "rm", "-f", *ids],
            check=False,
        )


def start_containers(count):
    for i in range(count):

        name = container_name(i)
        port = container_port(i)

        result = run(
            [
                "docker",
                "run",
                "-d",
                "--rm",
                "--name",
                name,
                "-p",
                f"{port}:8085",
                IMAGE,
            ],
            check=False,
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"Failed to start {name}:\n"
                f"{result.stderr}"
            )


def stop_containers(count):
    names = get_container_names(count)

    if names:
        run(
            ["docker", "rm", "-f", *names],
            check=False,
        )


# ============================================================
# HTTP helpers
# ============================================================

def infer(port):
    payload = json.dumps(
        {"features": FEATURES}
    ).encode()

    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/infer",
        data=payload,
        headers={
            "Content-Type": "application/json"
        },
        method="POST",
    )

    with urllib.request.urlopen(
        req,
        timeout=5,
    ) as response:

        return json.loads(
            response.read()
        )


def wait_ready(count):
    deadline = time.time() + 30

    pending = set(range(count))

    while pending and time.time() < deadline:

        completed = []

        for i in pending:
            try:
                result = infer(
                    container_port(i)
                )

                if "prediction" in result:
                    completed.append(i)

            except Exception:
                pass

        for i in completed:
            pending.remove(i)

        if pending:
            time.sleep(
                STARTUP_WAIT_SECONDS
            )

    if pending:
        raise RuntimeError(
            "Containers failed readiness check: "
            + ", ".join(
                container_name(i)
                for i in sorted(pending)
            )
        )


def warm(count):
    for i in range(count):

        result = infer(
            container_port(i)
        )

        if (
            int(result["prediction"])
            != EXPECTED_LABEL
        ):
            raise RuntimeError(
                f"Wrong prediction from "
                f"{container_name(i)}: "
                f"{result}"
            )


# ============================================================
# Memory measurement
# ============================================================

def memory(container):
    """
    Read process memory from inside the container.

    PID 1 is the native NB inference server process inside
    each COMET Docker container.

    This avoids host /proc/<pid>/smaps_rollup permission
    restrictions while retaining RSS/PSS/private-memory
    measurements.
    """

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
            f"Unable to read memory for "
            f"{container}:\n"
            f"{result.stderr}"
        )

    values = {}

    for line in result.stdout.splitlines():

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

    if "Rss" not in values:
        raise RuntimeError(
            f"Rss not found for {container}"
        )

    rss_kib = values.get(
        "Rss",
        0,
    )

    pss_kib = values.get(
        "Pss",
        0,
    )

    private_kib = (
        values.get(
            "Private_Clean",
            0,
        )
        +
        values.get(
            "Private_Dirty",
            0,
        )
    )

    return {
        "rss_mib":
            rss_kib / 1024.0,

        "pss_mib":
            pss_kib / 1024.0,

        "private_mib":
            private_kib / 1024.0,
    }


# ============================================================
# Experiment
# ============================================================

results = []

remove_existing()

try:

    for count in CONTAINER_LEVELS:

        print()
        print("=" * 60)
        print(
            f"CONTAINERS={count}"
        )
        print("=" * 60)

        for rep in range(
            1,
            REPETITIONS + 1,
        ):

            remove_existing()

            try:

                start_containers(count)

                wait_ready(count)

                warm(count)

                containers = (
                    get_container_names(
                        count
                    )
                )

                rss_samples = []
                pss_samples = []
                private_samples = []

                for _ in range(
                    MEMORY_SAMPLES
                ):

                    rss_total = 0.0
                    pss_total = 0.0
                    private_total = 0.0

                    for container in containers:

                        m = memory(
                            container
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

                    rss_samples.append(
                        rss_total
                    )

                    pss_samples.append(
                        pss_total
                    )

                    private_samples.append(
                        private_total
                    )

                    time.sleep(
                        MEMORY_SAMPLE_INTERVAL
                    )

                rss = statistics.mean(
                    rss_samples
                )

                pss = statistics.mean(
                    pss_samples
                )

                private = statistics.mean(
                    private_samples
                )

                result = {
                    "backend": "docker",
                    "model": "naive_bayes",
                    "containers": count,
                    "repetition": rep,
                    "rss_mib": rss,
                    "pss_mib": pss,
                    "private_mib": private,
                }

                results.append(
                    result
                )

                print(
                    f"rep={rep} "
                    f"RSS={rss:.3f} MiB "
                    f"PSS={pss:.3f} MiB "
                    f"Private={private:.3f} MiB"
                )

            finally:

                stop_containers(
                    count
                )

                time.sleep(0.5)

finally:

    remove_existing()


# ============================================================
# Save raw CSV
# ============================================================

with CSV_PATH.open(
    "w",
    newline="",
) as f:

    writer = csv.DictWriter(
        f,
        fieldnames=[
            "backend",
            "model",
            "containers",
            "repetition",
            "rss_mib",
            "pss_mib",
            "private_mib",
        ],
    )

    writer.writeheader()

    writer.writerows(
        results
    )


# ============================================================
# Calculate pilot summary
# ============================================================

summary = []

for count in CONTAINER_LEVELS:

    subset = [
        r
        for r in results
        if r["containers"] == count
    ]

    rss_values = [
        r["rss_mib"]
        for r in subset
    ]

    pss_values = [
        r["pss_mib"]
        for r in subset
    ]

    private_values = [
        r["private_mib"]
        for r in subset
    ]

    item = {
        "containers": count,

        "rss_mean_mib":
            statistics.mean(
                rss_values
            ),

        "pss_mean_mib":
            statistics.mean(
                pss_values
            ),

        "private_mean_mib":
            statistics.mean(
                private_values
            ),

        "pss_sd_mib":
            (
                statistics.stdev(
                    pss_values
                )
                if len(pss_values) > 1
                else 0.0
            ),
    }

    summary.append(
        item
    )


# ============================================================
# Save JSON
# ============================================================

output = {
    "experiment":
        "docker_nb_density_pilot",

    "backend":
        "docker",

    "model":
        "naive_bayes",

    "measurement_method":
        "container-local /proc/1/smaps_rollup",

    "repetitions":
        REPETITIONS,

    "memory_samples_per_repetition":
        MEMORY_SAMPLES,

    "container_levels":
        CONTAINER_LEVELS,

    "raw_results":
        results,

    "summary":
        summary,
}

JSON_PATH.write_text(
    json.dumps(
        output,
        indent=2,
    )
)


# ============================================================
# Print final summary
# ============================================================

print()
print("=" * 60)
print(
    "DOCKER PILOT SUMMARY"
)
print("=" * 60)

for item in summary:

    print(
        f"{item['containers']:>3} containers | "
        f"RSS={item['rss_mean_mib']:.3f} MiB | "
        f"PSS={item['pss_mean_mib']:.3f} MiB | "
        f"Private={item['private_mean_mib']:.3f} MiB | "
        f"SD(PSS)={item['pss_sd_mib']:.3f}"
    )

print()
print(
    f"CSV: {CSV_PATH}"
)

print(
    f"JSON: {JSON_PATH}"
)

print(
    "DOCKER NB DENSITY PILOT: COMPLETE"
)
