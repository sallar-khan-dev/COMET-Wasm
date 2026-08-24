#!/usr/bin/env python3

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

src = ROOT / "models/random_forest/breast_cancer/model.json"
dst = ROOT / "models/random_forest/breast_cancer/model_packed.json"

m = json.loads(src.read_text())

tree_offsets = [0]
children_left = []
children_right = []
feature = []
threshold = []
leaf_class = []

offset = 0

for tree in m["trees"]:
    n = tree["node_count"]

    for i in range(n):
        left = tree["children_left"][i]
        right = tree["children_right"][i]

        children_left.append(
            -1 if left == -1 else left + offset
        )

        children_right.append(
            -1 if right == -1 else right + offset
        )

        feature.append(tree["feature"][i])
        threshold.append(tree["threshold"][i])
        leaf_class.append(tree["leaf_class"][i])

    offset += n
    tree_offsets.append(offset)

packed = {
    "model": "RandomForestPacked",
    "dataset": m["dataset"],
    "task": m["task"],

    "feature_names": m["feature_names"],
    "classes": m["classes"],

    "mean": m["mean"],
    "scale": m["scale"],

    "n_estimators": m["n_estimators"],
    "total_nodes": offset,

    "tree_offsets": tree_offsets,

    "children_left": children_left,
    "children_right": children_right,
    "feature": feature,
    "threshold": threshold,
    "leaf_class": leaf_class,

    "metrics": m["metrics"],
    "profile_hint": m["profile_hint"],
}

dst.write_text(json.dumps(packed, indent=2))

print("Saved:", dst)
print("Trees:", packed["n_estimators"])
print("Total nodes:", packed["total_nodes"])
print("Tree offsets:", len(tree_offsets))
print("First offset:", tree_offsets[0])
print("Last offset:", tree_offsets[-1])
print("Packed JSON size:", dst.stat().st_size, "bytes")
