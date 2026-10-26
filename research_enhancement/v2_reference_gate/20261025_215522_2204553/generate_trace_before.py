#!/usr/bin/env python3
"""Generate deterministic COMET-Wasm V2 inference traces."""

import argparse
import hashlib
import json
import math
import random
from pathlib import Path


def canonical_bytes(value):
    return (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ) + "\n"
    ).encode("utf-8")


def generate(golden, count, seed, tenants):
    if golden.get("schema_version") != "comet-v2-golden-v1":
        raise ValueError("Unsupported golden reference schema")

    if count <= 0 or tenants <= 0:
        raise ValueError("Count and tenants must be positive")

    records = golden["records"]

    if not records or golden["sample_count"] != len(records):
        raise ValueError("Invalid golden record count")

    if len({r["row_index"] for r in records}) != len(records):
        raise ValueError("Duplicate source row indices")

    feature_count = len(records[0]["features"])

    for record in records:
        features = record["features"]
        if len(features) != feature_count or not all(
            isinstance(x, (int, float)) and math.isfinite(x)
            for x in features
        ):
            raise ValueError("Invalid feature vector")
        prediction = record["expected_prediction"]
        if isinstance(prediction, bool) or not isinstance(prediction, int) or not (-2**31 <= prediction < 2**31):
            raise ValueError("Golden prediction must be an i32 integer")

    rng = random.Random(seed)
    indices = list(range(len(records)))
    requests = []

    while len(requests) < count:
        rng.shuffle(indices)

        for index in indices:
            if len(requests) >= count:
                break

            record = records[index]
            sequence = len(requests)

            requests.append({
                "request_id": f"v2-{sequence:08d}",
                "sequence": sequence,
                "tenant_slot": sequence % tenants,
                "model": golden["model"],
                "source_row_index": record["row_index"],
                "features": record["features"],
                "expected_prediction": record["expected_prediction"],
                "ground_truth_label": record["ground_truth_label"],
            })

    return {
        "schema_version": "comet-v2-trace-v1",
        "model": golden["model"],
        "dataset": golden["dataset"],
        "seed": seed,
        "request_count": count,
        "tenant_count": tenants,
        "golden_model_sha256": golden["model_sha256"],
        "golden_dataset_sha256": golden["dataset_sha256"],
        "requests": requests,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--golden", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--tenants", type=int, default=1)
    args = parser.parse_args()

    source = Path(args.golden)
    destination = Path(args.output)

    golden = json.loads(source.read_text())
    trace = generate(golden, args.count, args.seed, args.tenants)

    trace["golden_artifact_sha256"] = hashlib.sha256(
        source.read_bytes()
    ).hexdigest()

    payload = canonical_bytes(trace)

    destination.parent.mkdir(parents=True, exist_ok=True)

    with destination.open("xb") as f:
        f.write(payload)

    print(f"PASS: Created {destination}")
    print(f"Requests: {trace['request_count']}")
    print(f"Tenants: {trace['tenant_count']}")
    print(f"SHA-256: {hashlib.sha256(payload).hexdigest()}")


if __name__ == "__main__":
    main()
