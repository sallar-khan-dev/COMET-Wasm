#!/usr/bin/env python3

import csv
import json
import math
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

MODEL_PATH = ROOT / "models/mlp/breast_cancer/model.json"
DATA_PATH = ROOT / "models/mlp/breast_cancer/test_samples.csv"
OUT_PATH = ROOT / "results/correctness/mlp.json"

BACKENDS = {
    "wasmtime": "http://localhost:8070/infer",
    "docker": "http://localhost:8093/infer",
}

m = json.loads(MODEL_PATH.read_text())

mean = m["mean"]
scale = m["scale"]

w1 = m["weights"][0]
w2 = m["weights"][1]

b1 = m["biases"][0]
b2 = m["biases"][1]


def python_reference(features):
    """
    Execute the exported MLP using the same operations as the
    Wasm and Docker implementations.

    Architecture:
        30 inputs
          ↓
        32 ReLU hidden neurons
          ↓
        1 logistic output
    """

    # StandardScaler transformation
    x = [
        (features[i] - mean[i]) / scale[i]
        for i in range(len(features))
    ]

    # Hidden layer: ReLU(XW + b)
    hidden = []

    for h in range(32):
        z = b1[h]

        for i in range(30):
            z += x[i] * w1[i][h]

        hidden.append(
            z if z > 0.0 else 0.0
        )

    # Output layer
    out = b2[0]

    for h in range(32):
        out += hidden[h] * w2[h][0]

    # Logistic activation
    probability = 1.0 / (1.0 + math.exp(-out))

    # sklearn binary classification threshold
    return 1 if probability >= 0.5 else 0


def backend_predict(url, features):
    """
    Send one inference request to a serving backend.
    """

    body = json.dumps({
        "features": features
    }).encode()

    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json"
        },
        method="POST"
    )

    with urllib.request.urlopen(
        req,
        timeout=5
    ) as response:

        result = json.loads(
            response.read()
        )

    return int(result["prediction"])


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

        # Reference implementation
        py = python_reference(features)

        # Wasmtime implementation
        wasm = backend_predict(
            BACKENDS["wasmtime"],
            features
        )

        # Docker implementation
        docker = backend_predict(
            BACKENDS["docker"],
            features
        )

        # Accuracy counters
        if py == expected:
            correct["python_reference"] += 1

        if wasm == expected:
            correct["wasmtime"] += 1

        if docker == expected:
            correct["docker"] += 1

        # Wasmtime vs Docker
        if wasm != docker:
            failures["wasmtime_vs_docker"].append({
                "sample": total,
                "expected": expected,
                "wasmtime": wasm,
                "docker": docker,
            })

        # Python vs Wasmtime
        if py != wasm:
            failures["python_vs_wasmtime"].append({
                "sample": total,
                "expected": expected,
                "python": py,
                "wasmtime": wasm,
            })

        # Python vs Docker
        if py != docker:
            failures["python_vs_docker"].append({
                "sample": total,
                "expected": expected,
                "python": py,
                "docker": docker,
            })


result = {
    "model": "mlp",
    "dataset": "breast_cancer",
    "architecture": [30, 32, 1],
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
            all(
                len(v) == 0
                for v in failures.values()
            ),
    },

    "failures": failures,
}


# Make sure output directory exists
OUT_PATH.parent.mkdir(
    parents=True,
    exist_ok=True
)

# Save reproducible correctness result
OUT_PATH.write_text(
    json.dumps(
        result,
        indent=2
    )
)


print("===== COMET-Wasm MLP Correctness Validation =====")
print()
print(
    json.dumps(
        result,
        indent=2
    )
)


if result["equivalence"]["all_backends_equivalent"]:
    print()
    print("MLP CROSS-BACKEND VALIDATION: PASS")
else:
    print()
    print("MLP CROSS-BACKEND VALIDATION: FAIL")
    raise SystemExit(1)
