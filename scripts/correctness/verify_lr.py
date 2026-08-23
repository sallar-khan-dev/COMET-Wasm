#!/usr/bin/env python3

import csv
import json
import math
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

MODEL_PATH = ROOT / "models/logistic_regression/iris_lr/model.json"
DATA_PATH = ROOT / "models/logistic_regression/iris_lr/test_samples.csv"
OUT_PATH = ROOT / "results/correctness/logistic_regression.json"

BACKENDS = {
    "wasmtime": "http://localhost:8010/infer",
    "docker": "http://localhost:8086/infer",
}

model = json.loads(MODEL_PATH.read_text())

weights = model["weights"]
bias = model["bias"]
mean = model["mean"]
scale = model["scale"]


def python_reference(features):
    z = bias

    for i, x in enumerate(features):
        x_scaled = (x - mean[i]) / scale[i]
        z += weights[i] * x_scaled

    probability = 1.0 / (1.0 + math.exp(-z))
    return 1 if probability >= 0.5 else 0


def backend_predict(url, features):
    payload = {
        "f1": features[0],
        "f2": features[1],
        "f3": features[2],
        "f4": features[3],
    }

    body = json.dumps(payload).encode("utf-8")

    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urllib.request.urlopen(request, timeout=5) as response:
        result = json.loads(response.read().decode("utf-8"))

    return int(result["prediction"])


total = 0
python_correct = 0
wasmtime_correct = 0
docker_correct = 0

backend_disagreements = []
python_wasm_disagreements = []
python_docker_disagreements = []

with DATA_PATH.open(newline="") as f:
    reader = csv.DictReader(f)

    for row in reader:
        total += 1

        features = [
            float(row["sepal_length"]),
            float(row["sepal_width"]),
            float(row["petal_length"]),
            float(row["petal_width"]),
        ]

        expected = int(row["label"])

        py_pred = python_reference(features)
        wasm_pred = backend_predict(BACKENDS["wasmtime"], features)
        docker_pred = backend_predict(BACKENDS["docker"], features)

        python_correct += py_pred == expected
        wasmtime_correct += wasm_pred == expected
        docker_correct += docker_pred == expected

        if wasm_pred != docker_pred:
            backend_disagreements.append({
                "sample": total,
                "expected": expected,
                "wasmtime": wasm_pred,
                "docker": docker_pred,
            })

        if py_pred != wasm_pred:
            python_wasm_disagreements.append({
                "sample": total,
                "python": py_pred,
                "wasmtime": wasm_pred,
            })

        if py_pred != docker_pred:
            python_docker_disagreements.append({
                "sample": total,
                "python": py_pred,
                "docker": docker_pred,
            })


result = {
    "model": "logistic_regression",
    "dataset": "iris",
    "samples": total,

    "accuracy": {
        "python_reference": python_correct / total,
        "wasmtime": wasmtime_correct / total,
        "docker": docker_correct / total,
    },

    "equivalence": {
        "wasmtime_vs_docker_failures": len(backend_disagreements),
        "python_vs_wasmtime_failures": len(python_wasm_disagreements),
        "python_vs_docker_failures": len(python_docker_disagreements),
        "all_backends_equivalent":
            len(backend_disagreements) == 0
            and len(python_wasm_disagreements) == 0
            and len(python_docker_disagreements) == 0,
    },

    "failures": {
        "wasmtime_vs_docker": backend_disagreements,
        "python_vs_wasmtime": python_wasm_disagreements,
        "python_vs_docker": python_docker_disagreements,
    },
}

OUT_PATH.write_text(json.dumps(result, indent=2))

print(json.dumps(result, indent=2))

if not result["equivalence"]["all_backends_equivalent"]:
    raise SystemExit(1)
