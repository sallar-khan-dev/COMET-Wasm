#!/usr/bin/env python3

import csv
import json
import math
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

MODEL_PATH = ROOT / "models/svm/breast_cancer/model.json"
DATA_PATH = ROOT / "models/svm/breast_cancer/test_samples.csv"
OUT_PATH = ROOT / "results/correctness/svm.json"

BACKENDS = {
    "wasmtime": "http://localhost:8060/infer",
    "docker": "http://localhost:8092/infer",
}

m = json.loads(MODEL_PATH.read_text())

mean = m["mean"]
scale = m["scale"]

support_vectors = m["support_vectors"]
dual_coef = m["dual_coef"]

gamma = m["gamma"]
intercept = m["intercept"]


def python_reference(features):

    scaled = [
        (features[i] - mean[i]) / scale[i]
        for i in range(len(features))
    ]

    decision = intercept

    for coef, sv in zip(
        dual_coef,
        support_vectors
    ):

        distance_sq = sum(
            (x - s) ** 2
            for x, s in zip(scaled, sv)
        )

        kernel = math.exp(
            -gamma * distance_sq
        )

        decision += coef * kernel

    return 1 if decision > 0 else 0


def backend_predict(url, features):

    body = json.dumps({
        "features": features
    }).encode()

    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json"
        },
        method="POST",
    )

    with urllib.request.urlopen(
        req,
        timeout=5
    ) as r:

        return int(
            json.loads(r.read())["prediction"]
        )


total = 0

correct = {
    "python_reference": 0,
    "wasmtime": 0,
    "docker": 0,
}

failures = {
    "wasmtime_vs_docker": [],
    "python_vs_wasmtime": [],
    "python_vs_docker": [],
}


with DATA_PATH.open(newline="") as f:

    reader = csv.DictReader(f)

    for row in reader:

        total += 1

        features = [
            float(row[name])
            for name in m["feature_names"]
        ]

        expected = int(row["label"])

        py = python_reference(features)

        wasm = backend_predict(
            BACKENDS["wasmtime"],
            features
        )

        docker = backend_predict(
            BACKENDS["docker"],
            features
        )

        correct["python_reference"] += (
            py == expected
        )

        correct["wasmtime"] += (
            wasm == expected
        )

        correct["docker"] += (
            docker == expected
        )

        if wasm != docker:
            failures[
                "wasmtime_vs_docker"
            ].append({
                "sample": total,
                "expected": expected,
                "wasmtime": wasm,
                "docker": docker,
            })

        if py != wasm:
            failures[
                "python_vs_wasmtime"
            ].append({
                "sample": total,
                "python": py,
                "wasmtime": wasm,
            })

        if py != docker:
            failures[
                "python_vs_docker"
            ].append({
                "sample": total,
                "python": py,
                "docker": docker,
            })


result = {

    "model": "svm_rbf",

    "dataset": "breast_cancer",

    "samples": total,

    "accuracy": {
        name: count / total
        for name, count
        in correct.items()
    },

    "equivalence": {

        "wasmtime_vs_docker_failures":
            len(
                failures[
                    "wasmtime_vs_docker"
                ]
            ),

        "python_vs_wasmtime_failures":
            len(
                failures[
                    "python_vs_wasmtime"
                ]
            ),

        "python_vs_docker_failures":
            len(
                failures[
                    "python_vs_docker"
                ]
            ),

        "all_backends_equivalent":
            all(
                len(v) == 0
                for v in failures.values()
            ),
    },

    "failures": failures,
}

OUT_PATH.write_text(
    json.dumps(
        result,
        indent=2
    )
)

print(
    json.dumps(
        result,
        indent=2
    )
)

if not result[
    "equivalence"
][
    "all_backends_equivalent"
]:
    raise SystemExit(1)
