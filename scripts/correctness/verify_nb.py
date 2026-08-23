#!/usr/bin/env python3

import csv
import json
import math
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

MODEL_PATH = ROOT / "models/naive_bayes/breast_cancer/model.json"
DATA_PATH = ROOT / "models/naive_bayes/breast_cancer/test_samples.csv"
OUT_PATH = ROOT / "results/correctness/naive_bayes.json"

BACKENDS = {
    "wasmtime": "http://localhost:8020/infer",
    "docker": "http://localhost:8087/infer",
}

m = json.loads(MODEL_PATH.read_text())

mean = m["mean"]
scale = m["scale"]
prior = m["class_prior"]
theta = m["theta"]
var = m["var"]
classes = m["classes"]


def python_reference(features):
    best_class = None
    best_score = -float("inf")

    for c in range(len(classes)):
        score = math.log(prior[c])

        for i, raw_x in enumerate(features):
            x = (raw_x - mean[i]) / scale[i]

            score += -0.5 * (
                math.log(2.0 * math.pi * var[c][i])
                + ((x - theta[c][i]) ** 2) / var[c][i]
            )

        if score > best_score:
            best_score = score
            best_class = classes[c]

    return int(best_class)


def backend_predict(url, features):
    body = json.dumps({"features": features}).encode()

    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    with urllib.request.urlopen(req, timeout=5) as r:
        return int(json.loads(r.read())["prediction"])


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
        wasm = backend_predict(BACKENDS["wasmtime"], features)
        docker = backend_predict(BACKENDS["docker"], features)

        correct["python_reference"] += py == expected
        correct["wasmtime"] += wasm == expected
        correct["docker"] += docker == expected

        if wasm != docker:
            failures["wasmtime_vs_docker"].append({
                "sample": total,
                "expected": expected,
                "wasmtime": wasm,
                "docker": docker,
            })

        if py != wasm:
            failures["python_vs_wasmtime"].append({
                "sample": total,
                "python": py,
                "wasmtime": wasm,
            })

        if py != docker:
            failures["python_vs_docker"].append({
                "sample": total,
                "python": py,
                "docker": docker,
            })


result = {
    "model": "gaussian_naive_bayes",
    "dataset": "breast_cancer",
    "samples": total,

    "accuracy": {
        name: count / total
        for name, count in correct.items()
    },

    "equivalence": {
        "wasmtime_vs_docker_failures":
            len(failures["wasmtime_vs_docker"]),

        "python_vs_wasmtime_failures":
            len(failures["python_vs_wasmtime"]),

        "python_vs_docker_failures":
            len(failures["python_vs_docker"]),

        "all_backends_equivalent":
            all(len(v) == 0 for v in failures.values()),
    },

    "failures": failures,
}

OUT_PATH.write_text(json.dumps(result, indent=2))

print(json.dumps(result, indent=2))

if not result["equivalence"]["all_backends_equivalent"]:
    raise SystemExit(1)
