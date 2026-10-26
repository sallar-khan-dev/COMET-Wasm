import hashlib
import json
from pathlib import Path

import numpy as np

ROOT = Path("/home/sallar/wasiMultitenant")
MODEL = ROOT / "models/svm/breast_cancer/model.json"
INPUT = ROOT / "research_enhancement/v2_references/rf_breast_cancer_golden_v1.json"
OUTPUT = ROOT / "research_enhancement/v2_references/svm_breast_cancer_golden_v1.json"

model_bytes = MODEL.read_bytes()
model = json.loads(model_bytes)
source = json.loads(INPUT.read_text())

f32 = np.float32

mean = np.asarray(model["mean"], dtype=np.float32)
scale = np.asarray(model["scale"], dtype=np.float32)
svs = np.asarray(model["support_vectors"], dtype=np.float32)
coefs = np.asarray(model["dual_coef"], dtype=np.float32)
gamma = f32(model["gamma"])
intercept = f32(model["intercept"])

assert mean.shape == (30,)
assert scale.shape == (30,)
assert svs.shape == (91, 30)
assert coefs.shape == (91,)
assert np.all(scale != 0)

records = []
near_boundary = []

for record in source["records"]:
    features = np.asarray(record["features"], dtype=np.float32)
    assert features.shape == (30,)
    assert np.all(np.isfinite(features))

    decision = intercept

    # Scalar f32 operations reproduce the exported model's
    # mathematical evaluation order, without invoking either backend.
    for i in range(91):
        distance_sq = f32(0)

        for j in range(30):
            x = f32(f32(features[j] - mean[j]) / scale[j])
            diff = f32(x - svs[i, j])
            distance_sq = f32(distance_sq + f32(diff * diff))

        exponent = f32(-f32(gamma * distance_sq))
        kernel = f32(np.exp(exponent))
        decision = f32(decision + f32(coefs[i] * kernel))

    prediction = 1 if decision > 0 else 0

    if abs(float(decision)) < 0.001:
        near_boundary.append({
            "id": record["id"],
            "decision": float(decision)
        })

    records.append({
        "id": record["id"],
        "features": features.astype(float).tolist(),
        "prediction": prediction,
        "decision": float(decision)
    })

assert len(records) == 569
assert len({r["id"] for r in records}) == 569

output = {
    "model": "SVM_RBF",
    "dataset": "breast_cancer",
    "reference_method": "independent_numpy_float32_rbf",
    "reference_status": "GENERATED_NOT_BACKEND_VALIDATED",
    "model_sha256": hashlib.sha256(model_bytes).hexdigest(),
    "n_features": 30,
    "n_support_vectors": 91,
    "n_records": len(records),
    "near_boundary_count": len(near_boundary),
    "near_boundary_records": near_boundary,
    "records": records
}

OUTPUT.write_text(json.dumps(output, indent=2) + "\n")

print("====================================")
print("SVM GOLDEN REFERENCE GENERATED")
print("====================================")
print("Records:", len(records))
print("Support vectors:", len(svs))
print("Class 0:", sum(r["prediction"] == 0 for r in records))
print("Class 1:", sum(r["prediction"] == 1 for r in records))
print("Near-boundary records:", len(near_boundary))
print("Model SHA256:", output["model_sha256"])
print("Golden SHA256:", hashlib.sha256(OUTPUT.read_bytes()).hexdigest())
print("Output:", OUTPUT)
