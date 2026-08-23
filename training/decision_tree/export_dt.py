#!/usr/bin/env python3

import json
from pathlib import Path

import pandas as pd
from sklearn.datasets import load_breast_cancer
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.tree import DecisionTreeClassifier
from sklearn.metrics import (
    accuracy_score,
    precision_recall_fscore_support,
)

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "models" / "decision_tree" / "breast_cancer"
OUT.mkdir(parents=True, exist_ok=True)

data = load_breast_cancer()

X = data.data.astype(float)
y = data.target.astype(int)

feature_names = [
    str(x).replace(" ", "_").replace("(", "").replace(")", "")
    for x in data.feature_names
]

X_train, X_test, y_train, y_test = train_test_split(
    X,
    y,
    test_size=0.30,
    random_state=42,
    stratify=y,
)

scaler = StandardScaler()

X_train_s = scaler.fit_transform(X_train)
X_test_s = scaler.transform(X_test)

clf = DecisionTreeClassifier(
    max_depth=8,
    random_state=42,
)

clf.fit(X_train_s, y_train)

pred = clf.predict(X_test_s)

p, r, f1, _ = precision_recall_fscore_support(
    y_test,
    pred,
    average="binary",
    zero_division=0,
)

tree = clf.tree_

# Binary classifier: select class index with largest leaf count.
leaf_class = []

for node_values in tree.value:
    counts = node_values[0]
    leaf_class.append(int(counts.argmax()))

model = {
    "model": "DecisionTree",
    "dataset": "breast_cancer",
    "task": "binary_classification",

    "feature_names": feature_names,

    "mean": scaler.mean_.astype(float).tolist(),
    "scale": scaler.scale_.astype(float).tolist(),

    "children_left": tree.children_left.astype(int).tolist(),
    "children_right": tree.children_right.astype(int).tolist(),
    "feature": tree.feature.astype(int).tolist(),
    "threshold": tree.threshold.astype(float).tolist(),
    "leaf_class": leaf_class,

    "classes": clf.classes_.astype(int).tolist(),

    "tree": {
        "node_count": int(tree.node_count),
        "max_depth": int(tree.max_depth),
        "n_leaves": int(clf.get_n_leaves()),
    },

    "metrics": {
        "accuracy": float(accuracy_score(y_test, pred)),
        "precision": float(p),
        "recall": float(r),
        "f1": float(f1),
    },

    "profile_hint": {
        "compute_class": "branch_heavy",
        "memory_class": "medium",
        "complexity": "O(tree_depth)",
        "features": int(X.shape[1]),
        "train_samples": int(X_train.shape[0]),
        "test_samples": int(X_test.shape[0]),
    },
}

(OUT / "model.json").write_text(
    json.dumps(model, indent=2)
)

df = pd.DataFrame(X_test, columns=feature_names)
df["label"] = y_test
df.to_csv(OUT / "test_samples.csv", index=False)

print("Saved:", OUT / "model.json")
print("Features:", X.shape[1])
print("Nodes:", tree.node_count)
print("Depth:", tree.max_depth)
print("Leaves:", clf.get_n_leaves())
print("Train samples:", len(X_train))
print("Test samples:", len(X_test))
print(json.dumps(model["metrics"], indent=2))
