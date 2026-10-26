#!/usr/bin/env python3
import hashlib
import json
import math
import struct
from pathlib import Path

from sklearn.datasets import load_iris

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "models/kmeans/iris/model.json"
OUTPUT = ROOT / "research_enhancement/v2_references/kmeans_iris_golden_v1.json"

def f32(x):
    return struct.unpack("<f", struct.pack("<f", float(x)))[0]

def sha256(data):
    return hashlib.sha256(data).hexdigest()

def canonical(obj):
    return (json.dumps(
        obj, sort_keys=True, separators=(",", ":"), allow_nan=False
    ) + "\n").encode()

model = json.loads(MODEL.read_text())
iris = load_iris()

centroids = model["centroids"]
dimension = int(model["n_features"])
clusters = int(model["n_clusters"])

assert len(centroids) == clusters
assert all(len(c) == dimension for c in centroids)
assert iris.data.shape[1] == dimension

records = []

for index, (features, label) in enumerate(zip(iris.data, iris.target)):
    x = [f32(v) for v in features]

    distances = []
    for centroid in centroids:
        distance = f32(0.0)
        for value, center in zip(x, centroid):
            delta = f32(value - f32(center))
            distance = f32(distance + f32(delta * delta))
        distances.append(distance)

    prediction = min(range(clusters), key=lambda c: distances[c])

    records.append({
        "row_index": index,
        "features": x,
        "expected_prediction": int(prediction),
        "ground_truth_label": int(label)
    })

dataset_payload = canonical({
    "dataset": "sklearn_iris",
    "features": [r["features"] for r in records],
    "labels": [r["ground_truth_label"] for r in records]
})

golden = {
    "schema_version": "comet-v2-golden-v1",
    "model": "kmeans",
    "dataset": "sklearn_iris",
    "sample_count": len(records),
    "model_sha256": sha256(MODEL.read_bytes()),
    "dataset_sha256": sha256(dataset_payload),
    "records": records
}

OUTPUT.write_bytes(canonical(golden))

assert len(records) == 150
assert all(math.isfinite(v) for r in records for v in r["features"])

print("PASS: K-Means Python reference generated")
print("Samples:", len(records))
print("Clusters:", clusters)
print("Features:", dimension)
print("Golden:", OUTPUT)
print("SHA256:", sha256(OUTPUT.read_bytes()))
print("NOTE: Python reference still requires Wasm parity validation")
