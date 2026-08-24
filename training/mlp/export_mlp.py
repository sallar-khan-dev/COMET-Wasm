#!/usr/bin/env python3

import json
from pathlib import Path

import pandas as pd
from sklearn.datasets import load_breast_cancer
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.neural_network import MLPClassifier
from sklearn.metrics import accuracy_score, precision_recall_fscore_support

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "models/mlp/breast_cancer"
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

clf = MLPClassifier(
    hidden_layer_sizes=(32,),
    activation="relu",
    solver="adam",
    max_iter=500,
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

weights = [
    w.astype(float).tolist()
    for w in clf.coefs_
]

biases = [
    b.astype(float).tolist()
    for b in clf.intercepts_
]

model = {
    "model": "MLP",
    "dataset": "breast_cancer",
    "task": "binary_classification",

    "feature_names": feature_names,
    "classes": clf.classes_.astype(int).tolist(),

    "mean": scaler.mean_.astype(float).tolist(),
    "scale": scaler.scale_.astype(float).tolist(),

    "activation": clf.activation,
    "out_activation": clf.out_activation_,

    "layer_sizes": [
        int(X.shape[1]),
        32,
        1
    ],

    "weights": weights,
    "biases": biases,

    "metrics": {
        "accuracy": float(accuracy_score(y_test, pred)),
        "precision": float(p),
        "recall": float(r),
        "f1": float(f1),
    },

    "profile_hint": {
        "compute_class": "dense_neural",
        "memory_class": "medium",
        "complexity": "O(input*hidden + hidden*output)",
        "features": int(X.shape[1]),
        "hidden_units": 32,
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
print("Input features:", X.shape[1])
print("Hidden units:", 32)
print("Output units:", 1)
print("Weight matrix 1:",
      len(weights[0]), "x", len(weights[0][0]))
print("Weight matrix 2:",
      len(weights[1]), "x", len(weights[1][0]))
print("Train samples:", len(X_train))
print("Test samples:", len(X_test))
print(json.dumps(model["metrics"], indent=2))
