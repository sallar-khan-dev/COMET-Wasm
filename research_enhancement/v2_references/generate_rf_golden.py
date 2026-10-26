import json
import hashlib
from pathlib import Path

import numpy as np
from sklearn.datasets import load_breast_cancer

ROOT = Path.cwd()
MODEL = ROOT / "models/random_forest/breast_cancer/model_packed.json"
OUTPUT = ROOT / "research_enhancement/v2_references/rf_breast_cancer_golden_v1.json"

m = json.loads(MODEL.read_text())
dataset = load_breast_cancer()

offsets = m["tree_offsets"]
left = m["children_left"]
right = m["children_right"]
feature = m["feature"]
threshold = m["threshold"]
leaf_class = m["leaf_class"]

mean = np.asarray(m["mean"], dtype=np.float32)
scale = np.asarray(m["scale"], dtype=np.float32)
threshold = np.asarray(threshold, dtype=np.float32)

assert len(mean) == len(scale) == 30
assert len(offsets) == m["n_estimators"] + 1
assert offsets[-1] == m["total_nodes"]

def predict(features):
    x = np.asarray(features, dtype=np.float32)
    votes = [0, 0]

    for tree in range(m["n_estimators"]):
        node = offsets[tree]

        while True:
            l, r = left[node], right[node]

            if l == -1 and r == -1:
                votes[leaf_class[node]] += 1
                break

            f = feature[node]
            if f < 0:
                votes[leaf_class[node]] += 1
                break

            standardized = np.float32(
                np.float32(x[f] - mean[f]) / scale[f]
            )

            node = l if standardized <= threshold[node] else r

    return 1 if votes[1] > votes[0] else 0

records = []

for index, (features, label) in enumerate(zip(dataset.data, dataset.target)):
    x = np.asarray(features, dtype=np.float32)
    records.append({
        "id": index,
        "features": [float(v) for v in x],
        "prediction": predict(x),
        "dataset_label": int(label)
    })

artifact = {
    "model": "RandomForestPacked",
    "dataset": "breast_cancer",
    "reference_method": "independent_python_float32_tree_traversal",
    "reference_status": "candidate_pending_wasm_and_docker_parity",
    "n_estimators": m["n_estimators"],
    "total_nodes": m["total_nodes"],
    "n_features": 30,
    "n_records": len(records),
    "model_sha256": hashlib.sha256(MODEL.read_bytes()).hexdigest(),
    "records": records
}

OUTPUT.write_text(json.dumps(artifact, indent=2) + "\n")

print("RF GOLDEN GENERATED")
print("Records:", len(records))
print("Model trees:", m["n_estimators"])
print("Golden file:", OUTPUT)
print("Golden SHA256:", hashlib.sha256(OUTPUT.read_bytes()).hexdigest())
