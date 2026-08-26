#!/usr/bin/env python3

import argparse
import csv
import json
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path


# ============================================================
# Repository root
# ============================================================

ROOT = Path(__file__).resolve().parents[2]

if str(ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(ROOT)
    )

from experiments.common.model_registry import get_model


# ============================================================
# CLI
# ============================================================

parser = argparse.ArgumentParser(
    description=(
        "COMET-Wasm unified cross-model "
        "correctness smoke runner"
    )
)

parser.add_argument(
    "--model",
    required=True,
)

parser.add_argument(
    "--backend",
    required=True,
    choices=[
        "wasmtime",
        "docker",
    ],
)

args = parser.parse_args()


# ============================================================
# Registry
# ============================================================

m = get_model(
    args.model
)

SUPPORTED_TASKS = {
    "binary_classification",
    "clustering_inference",
}

if m["task"] not in SUPPORTED_TASKS:
    raise RuntimeError(
        f"Unsupported task: {m['task']}"
    )


# ============================================================
# Load one sample
# ============================================================

with m["test_path_abs"].open(
    newline=""
) as f:

    row = next(
        csv.DictReader(f)
    )


# ============================================================
# Feature extraction
# ============================================================

if args.model == "kmeans":

    model_data = json.loads(
        m["model_path_abs"].read_text()
    )

    feature_names = model_data[
        "feature_names"
    ]

    centroids = model_data[
        "centroids"
    ]

    features = [
        float(row[name])
        for name in feature_names
    ]


    # --------------------------------------------------------
    # K-Means Python reference:
    # nearest exported centroid
    # --------------------------------------------------------

    best_cluster = 0
    best_distance = float(
        "inf"
    )

    for cluster_id, centroid in enumerate(
        centroids
    ):

        distance = sum(
            (
                x - mu
            ) ** 2
            for x, mu in zip(
                features,
                centroid
            )
        )

        if distance < best_distance:

            best_distance = distance
            best_cluster = cluster_id


    expected = best_cluster

    exported_label = int(
        row["label"]
    )

    if expected != exported_label:

        raise RuntimeError(
            "K-Means exported label does not "
            "match nearest-centroid reference. "
            f"Reference={expected}, "
            f"CSV label={exported_label}"
        )


else:

    features = [
        float(value)
        for key, value in row.items()
        if key != "label"
    ]

    expected = int(
        row["label"]
    )


if len(features) != int(
    m["features"]
):

    raise RuntimeError(
        f"{args.model}: feature-count mismatch. "
        f"Registry={m['features']}, "
        f"sample={len(features)}"
    )


# ============================================================
# HTTP inference
# ============================================================

def infer(
    url,
    backend,
):

    if backend == "wasmtime":

        payload = {
            "tenant_id": 0,
            "features": features,
        }

    else:

        payload = {
            "features": features,
        }


    request = urllib.request.Request(
        url,
        data=json.dumps(
            payload
        ).encode(),
        headers={
            "Content-Type":
                "application/json"
        },
        method="POST",
    )


    with urllib.request.urlopen(
        request,
        timeout=5,
    ) as response:

        if response.status != 200:

            raise RuntimeError(
                f"HTTP {response.status}"
            )

        result = json.loads(
            response.read()
        )


    if "prediction" not in result:

        raise RuntimeError(
            "Backend response does not "
            "contain 'prediction': "
            f"{result}"
        )


    return result


# ============================================================
# Wasmtime
# ============================================================

def run_wasmtime():

    server = (
        ROOT
        / "serving"
        / "multitenant_server"
        / "target"
        / "release"
        / "comet_multitenant_server"
    )

    if not server.exists():
        raise RuntimeError(
            f"Missing server: {server}"
        )


    if not m[
        "wasm_artifact_abs"
    ].exists():

        raise RuntimeError(
            "Missing Wasm artifact: "
            f"{m['wasm_artifact_abs']}"
        )


    subprocess.run(
        [
            "pkill",
            "-f",
            "comet_multitenant_server",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


    process = subprocess.Popen(
        [
            str(server),

            args.model,

            str(
                m[
                    "wasm_artifact_abs"
                ]
            ),

            "1",

            "8100",
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

            if process.poll() is not None:

                raise RuntimeError(
                    "Wasmtime server exited "
                    "before readiness."
                )


            try:

                with urllib.request.urlopen(
                    "http://127.0.0.1:8100/health",
                    timeout=0.2,
                ) as response:

                    if response.status == 200:
                        break

            except Exception:
                pass


            if time.time() > deadline:

                raise RuntimeError(
                    "Wasmtime readiness timeout."
                )


            time.sleep(
                0.01
            )


        return infer(
            "http://127.0.0.1:8100/infer",
            "wasmtime",
        )


    finally:

        if process.poll() is None:

            process.send_signal(
                signal.SIGTERM
            )

            try:

                process.wait(
                    timeout=5
                )

            except subprocess.TimeoutExpired:

                process.kill()
                process.wait()


# ============================================================
# Docker
# ============================================================

def run_docker():

    container_name = (
        "comet-crossmodel-"
        + args.model.replace(
            "_",
            "-"
        )
    )

    host_port = 8600


    subprocess.run(
        [
            "docker",
            "rm",
            "-f",
            container_name,
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


    docker_run = subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--rm",

            "--name",
            container_name,

            "-p",
            f"{host_port}:8085",

            m["docker_image"],
        ],
        text=True,
        capture_output=True,
    )


    if docker_run.returncode != 0:

        raise RuntimeError(
            "Docker launch failed:\n"
            + docker_run.stderr
        )


    try:

        deadline = (
            time.time()
            + 30
        )


        while True:

            try:

                return infer(
                    f"http://127.0.0.1:"
                    f"{host_port}/infer",
                    "docker",
                )

            except Exception as exc:

                if time.time() > deadline:

                    raise RuntimeError(
                        "Docker readiness timeout."
                    ) from exc

                time.sleep(
                    0.01
                )


    finally:

        subprocess.run(
            [
                "docker",
                "rm",
                "-f",
                container_name,
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


# ============================================================
# Execute
# ============================================================

if args.backend == "wasmtime":

    result = run_wasmtime()

else:

    result = run_docker()


prediction = int(
    result[
        "prediction"
    ]
)

correct = (
    prediction
    == expected
)


# ============================================================
# Output
# ============================================================

summary = {

    "model":
        args.model,

    "dataset":
        m["dataset"],

    "task":
        m["task"],

    "workload_class":
        m["workload_class"],

    "backend":
        args.backend,

    "features":
        int(
            m["features"]
        ),

    "expected":
        expected,

    "prediction":
        prediction,

    "correct":
        correct,
}


if args.model == "kmeans":

    summary[
        "expected_semantics"
    ] = (
        "nearest_exported_centroid"
    )

    summary[
        "exported_cluster_label"
    ] = exported_label


print(
    json.dumps(
        summary,
        indent=2
    )
)


if not correct:

    raise RuntimeError(
        f"{args.model}/{args.backend}: "
        f"prediction mismatch. "
        f"Expected {expected}, "
        f"got {prediction}."
    )


print()

print(
    "CROSS-MODEL SMOKE: PASS"
)
