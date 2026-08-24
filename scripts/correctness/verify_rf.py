#!/usr/bin/env python3

import csv
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

MODEL_PATH = ROOT / "models/random_forest/breast_cancer/model_packed.json"
DATA_PATH = ROOT / "models/random_forest/breast_cancer/test_samples.csv"
OUT_PATH = ROOT / "results/correctness/random_forest.json"

BACKENDS = {
    "wasmtime": "http://localhost:8050/infer",
    "docker": "http://localhost:8091/infer",
}

m = json.loads(MODEL_PATH.read_text())

mean = m["mean"]
scale = m["scale"]

offsets = m["tree_offsets"]
left = m["children_left"]
right = m["children_right"]
feature = m["feature"]
threshold = m["threshold"]
leaf_class = m["leaf_class"]

def run_tree(tree_index, features):
    node = offsets[tree_index]

    while True:
        if left[node] == -1 and right[node] == -1:
            return int(leaf_class[node])

        f = feature[node]

        if f < 0:
            return int(leaf_class[node])

        x = (features[f] - mean[f]) / scale[f]

        if x <= threshold[node]:
            node = left[node]
        else:
            node = right[node]

def python_reference(features):
    votes = [0, 0]

    for t in range(m["n_estimators"]):
        pred = run_tree(t, features)
        votes[pred] += 1

    return 1 if votes[1] > votes[0] else 0

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
    "model": "random_forest",
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
