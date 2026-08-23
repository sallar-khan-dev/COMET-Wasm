#!/usr/bin/env python3

import csv
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

MODEL = ROOT / "models/kmeans/iris/model.json"
DATA = ROOT / "models/kmeans/iris/samples.csv"
OUT = ROOT / "results/correctness/kmeans.json"

m = json.loads(MODEL.read_text())

centroids = m["centroids"]
feature_names = m["feature_names"]

BACKENDS = {
    "wasmtime": "http://localhost:8040/infer",
    "docker": "http://localhost:8089/infer",
}

def python_reference(features):
    best_cluster = 0
    best_distance = float("inf")

    for c, centroid in enumerate(centroids):
        distance = sum(
            (x - mu) ** 2
            for x, mu in zip(features, centroid)
        )

        if distance < best_distance:
            best_distance = distance
            best_cluster = c

    return best_cluster

def backend_predict(url, features):
    payload = json.dumps({
        "features": features
    }).encode()

    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    with urllib.request.urlopen(req, timeout=5) as r:
        return int(json.loads(r.read())["prediction"])

total = 0

agreement_with_exported_label = {
    "python_reference": 0,
    "wasmtime": 0,
    "docker": 0,
}

failures = {
    "wasmtime_vs_docker": [],
    "python_vs_wasmtime": [],
    "python_vs_docker": [],
}

with DATA.open(newline="") as f:

    reader = csv.DictReader(f)

    for row in reader:

        total += 1

        features = [
            float(row[name])
            for name in feature_names
        ]

        exported_label = int(row["label"])

        py = python_reference(features)
        wasm = backend_predict(
            BACKENDS["wasmtime"], features
        )
        docker = backend_predict(
            BACKENDS["docker"], features
        )

        agreement_with_exported_label["python_reference"] += (
            py == exported_label
        )

        agreement_with_exported_label["wasmtime"] += (
            wasm == exported_label
        )

        agreement_with_exported_label["docker"] += (
            docker == exported_label
        )

        if wasm != docker:
            failures["wasmtime_vs_docker"].append({
                "sample": total,
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
    "model": "kmeans",
    "dataset": "iris",
    "samples": total,

    "agreement_with_exported_cluster_assignment": {
        name: count / total
        for name, count in
        agreement_with_exported_label.items()
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

OUT.write_text(json.dumps(result, indent=2))

print(json.dumps(result, indent=2))

if not result["equivalence"]["all_backends_equivalent"]:
    raise SystemExit(1)
