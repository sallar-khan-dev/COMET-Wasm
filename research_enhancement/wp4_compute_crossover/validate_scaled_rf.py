#!/usr/bin/env python3
import hashlib
import json
import subprocess
import time
import urllib.request
import uuid
from pathlib import Path

import numpy as np
from sklearn.datasets import load_breast_cancer

ROOT = Path("/home/sallar/wasiMultitenant")
BASE = ROOT / "research_enhancement/wp4_compute_crossover"
REPORTS = BASE / "validation"
REPORTS.mkdir(parents=True, exist_ok=True)

RUNNER = (
    ROOT / "research_enhancement/v2_parity/"
    "all_models_wasmtime_runner/target/release/comet-all-parity"
)

if not RUNNER.is_file():
    raise FileNotFoundError(RUNNER)

dataset = load_breast_cancer()

def reference_prediction(m, features):
    x = np.asarray(features, dtype=np.float32)
    mean = np.asarray(m["mean"], dtype=np.float32)
    scale = np.asarray(m["scale"], dtype=np.float32)
    threshold = np.asarray(m["threshold"], dtype=np.float32)

    votes = [0, 0]

    for tree in range(m["n_estimators"]):
        node = m["tree_offsets"][tree]

        while True:
            left = m["children_left"][node]
            right = m["children_right"][node]

            if left == -1 and right == -1:
                votes[m["leaf_class"][node]] += 1
                break

            feature = m["feature"][node]

            if feature < 0:
                votes[m["leaf_class"][node]] += 1
                break

            z = np.float32(
                np.float32(x[feature] - mean[feature])
                / scale[feature]
            )

            node = (
                left if z <= threshold[node] else right
            )

    return 1 if votes[1] > votes[0] else 0


def docker_validate(trees, records):
    image = f"comet-wp4-rf-{trees}:latest"
    container = f"comet_wp4_rf_parity_{trees}_{uuid.uuid4().hex[:8]}"
    started = False

    try:
        subprocess.run(
            [
                "docker", "run", "-d",
                "--name", container,
                "-p", "127.0.0.1::8085",
                image
            ],
            check=True,
            stdout=subprocess.DEVNULL
        )
        started = True

        port_output = subprocess.check_output(
            ["docker", "port", container, "8085/tcp"],
            text=True
        ).strip()

        port = int(port_output.rsplit(":", 1)[-1])
        url = f"http://127.0.0.1:{port}/infer"

        matched = 0
        examples = []
        errors = 0

        for index, record in enumerate(records):
            request = urllib.request.Request(
                url,
                data=json.dumps({
                    "features": record["features"]
                }).encode(),
                headers={"Content-Type": "application/json"},
                method="POST"
            )

            response = None

            for attempt in range(40 if index == 0 else 1):
                try:
                    with urllib.request.urlopen(
                        request, timeout=10
                    ) as result:
                        response = json.loads(result.read())
                    break
                except Exception:
                    if index == 0 and attempt < 39:
                        time.sleep(0.25)
                    else:
                        errors += 1

            if response is None:
                continue

            prediction = int(response["prediction"])

            if prediction == record["prediction"]:
                matched += 1
            elif len(examples) < 25:
                examples.append({
                    "id": record["id"],
                    "expected": record["prediction"],
                    "actual": prediction
                })

        return {
            "status": (
                "PASS" if matched == len(records)
                and errors == 0 else "FAIL"
            ),
            "records": len(records),
            "matched": matched,
            "mismatches": len(records) - matched - errors,
            "errors": errors,
            "examples": examples,
            "image": image
        }

    finally:
        if started:
            subprocess.run(
                ["docker", "rm", "-f", container],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )


all_passed = True

for trees in (100, 200, 400):
    variant = f"rf_trees_{trees}"
    print(f"\n========== VALIDATING {variant} ==========", flush=True)

    model_path = (
        ROOT / "models/wp4_scaled/random_forest"
        / variant / "model_packed.json"
    )

    model = json.loads(model_path.read_text())

    assert model["n_estimators"] == trees
    assert len(model["mean"]) == 30
    assert model["tree_offsets"][-1] == model["total_nodes"]

    records = []

    for index, features in enumerate(dataset.data):
        x = np.asarray(features, dtype=np.float32)

        records.append({
            "id": index,
            "features": [float(v) for v in x],
            "prediction": reference_prediction(model, x)
        })

    golden_path = REPORTS / f"{variant}_golden.json"

    golden_path.write_text(json.dumps({
        "model": variant,
        "reference_method": "independent_python_float32_tree_traversal",
        "model_sha256": hashlib.sha256(
            model_path.read_bytes()
        ).hexdigest(),
        "n_records": len(records),
        "records": records
    }, indent=2) + "\n")

    wasm_path = (
        BASE / "generated" / variant / "wasm"
        / "target/wasm32-unknown-unknown/release/tenant_rf_real.wasm"
    )

    wasm_report_path = REPORTS / f"{variant}_wasmtime.json"

    subprocess.run(
        [
            str(RUNNER),
            str(wasm_path),
            str(golden_path),
            str(wasm_report_path)
        ],
        check=True,
        timeout=180
    )

    wasm_report = json.loads(wasm_report_path.read_text())
    docker_report = docker_validate(trees, records)

    docker_report_path = REPORTS / f"{variant}_docker.json"
    docker_report_path.write_text(
        json.dumps(docker_report, indent=2) + "\n"
    )

    print(
        f"{variant}: "
        f"Wasmtime={wasm_report['status']} "
        f"({wasm_report['matched']}/{len(records)}), "
        f"Docker={docker_report['status']} "
        f"({docker_report['matched']}/{len(records)})",
        flush=True
    )

    if (
        wasm_report["status"] != "PASS"
        or docker_report["status"] != "PASS"
    ):
        all_passed = False

print(
    "\nWP4 RF CORRECTNESS:",
    "PASS" if all_passed else "FAIL",
    flush=True
)

if not all_passed:
    raise SystemExit(1)
