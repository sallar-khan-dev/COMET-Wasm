#!/usr/bin/env python3
import json
from pathlib import Path

import numpy as np
from sklearn.datasets import load_breast_cancer
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, precision_recall_fscore_support

ROOT = Path("/home/sallar/wasiMultitenant")
BASE = ROOT / "models/wp4_scaled/random_forest"

data = load_breast_cancer()
X = data.data.astype(float)
y = data.target.astype(int)

feature_names = [
    str(x).replace(" ", "_").replace("(", "").replace(")", "")
    for x in data.feature_names
]

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.30, random_state=42, stratify=y
)

scaler = StandardScaler()
X_train_s = scaler.fit_transform(X_train)
X_test_s = scaler.transform(X_test)

for n_trees in (100, 200, 400):
    OUT = BASE / f"rf_trees_{n_trees}"
    OUT.mkdir(parents=True, exist_ok=True)

    clf = RandomForestClassifier(
        n_estimators=n_trees,
        max_depth=8,
        random_state=42,
        n_jobs=1
    )
    clf.fit(X_train_s, y_train)
    pred = clf.predict(X_test_s)

    p, r, f1, _ = precision_recall_fscore_support(
        y_test, pred, average="binary", zero_division=0
    )

    trees = []
    for estimator in clf.estimators_:
        tree = estimator.tree_
        trees.append({
            "node_count": int(tree.node_count),
            "children_left": tree.children_left.astype(int).tolist(),
            "children_right": tree.children_right.astype(int).tolist(),
            "feature": tree.feature.astype(int).tolist(),
            "threshold": tree.threshold.astype(float).tolist(),
            "leaf_class": [
                int(values[0].argmax()) for values in tree.value
            ],
            "max_depth": int(tree.max_depth)
        })

    model = {
        "model": "RandomForest",
        "dataset": "breast_cancer",
        "task": "binary_classification",
        "feature_names": feature_names,
        "classes": clf.classes_.astype(int).tolist(),
        "mean": scaler.mean_.astype(float).tolist(),
        "scale": scaler.scale_.astype(float).tolist(),
        "n_estimators": len(trees),
        "trees": trees,
        "metrics": {
            "accuracy": float(accuracy_score(y_test, pred)),
            "precision": float(p),
            "recall": float(r),
            "f1": float(f1)
        },
        "profile_hint": {
            "compute_class": "tree_ensemble",
            "memory_class": "high",
            "complexity": "O(trees*depth)",
            "features": int(X.shape[1]),
            "trees": len(trees),
            "train_samples": int(X_train.shape[0]),
            "test_samples": int(X_test.shape[0])
        }
    }

    (OUT / "model.json").write_text(json.dumps(model, indent=2))

    # Pack trees into flattened arrays, matching the existing RF format.
    offsets = [0]
    left, right, feature, threshold, leaf = [], [], [], [], []
    offset = 0

    for tree in trees:
        n = tree["node_count"]
        for i in range(n):
            l = tree["children_left"][i]
            r = tree["children_right"][i]
            left.append(-1 if l == -1 else l + offset)
            right.append(-1 if r == -1 else r + offset)
            feature.append(tree["feature"][i])
            threshold.append(tree["threshold"][i])
            leaf.append(tree["leaf_class"][i])
        offset += n
        offsets.append(offset)

    packed = {
        "model": "RandomForestPacked",
        "dataset": model["dataset"],
        "task": model["task"],
        "feature_names": model["feature_names"],
        "classes": model["classes"],
        "mean": model["mean"],
        "scale": model["scale"],
        "n_estimators": len(trees),
        "total_nodes": offset,
        "tree_offsets": offsets,
        "children_left": left,
        "children_right": right,
        "feature": feature,
        "threshold": threshold,
        "leaf_class": leaf,
        "metrics": model["metrics"],
        "profile_hint": model["profile_hint"]
    }

    (OUT / "model_packed.json").write_text(
        json.dumps(packed, indent=2)
    )

    print(
        f"RF {n_trees}: accuracy={model['metrics']['accuracy']:.4f}, "
        f"nodes={offset}, packed={OUT / 'model_packed.json'}",
        flush=True
    )

print("ALL SCALED RANDOM FOREST MODELS GENERATED")
