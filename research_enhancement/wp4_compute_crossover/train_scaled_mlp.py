#!/usr/bin/env python3

import json
from pathlib import Path

import numpy as np
from sklearn.datasets import load_breast_cancer
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.neural_network import MLPClassifier
from sklearn.metrics import accuracy_score

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "models/wp4_scaled/mlp"

OUT.mkdir(parents=True, exist_ok=True)

data = load_breast_cancer()

X = data.data.astype(float)
y = data.target.astype(int)

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

for width in [64, 128, 256]:

    clf = MLPClassifier(
        hidden_layer_sizes=(width,),
        activation="relu",
        solver="adam",
        max_iter=500,
        random_state=42,
    )

    clf.fit(X_train_s, y_train)

    predictions = clf.predict(X_test_s)

    model = {
        "model": "MLP",
        "dataset": "breast_cancer",
        "task": "binary_classification",
        "classes": clf.classes_.astype(int).tolist(),
        "mean": scaler.mean_.astype(float).tolist(),
        "scale": scaler.scale_.astype(float).tolist(),
        "activation": clf.activation,
        "out_activation": clf.out_activation_,
        "layer_sizes": [30, width, 1],
        "weights": [
            w.astype(float).tolist()
            for w in clf.coefs_
        ],
        "biases": [
            b.astype(float).tolist()
            for b in clf.intercepts_
        ],
        "metrics": {
            "accuracy": float(
                accuracy_score(y_test, predictions)
            )
        },
        "wp4": {
            "model_family": "mlp",
            "hidden_units": width,
            "random_state": 42
        }
    }

    destination = OUT / f"mlp_width_{width}"
    destination.mkdir(parents=True, exist_ok=True)

    (destination / "model.json").write_text(
        json.dumps(model, indent=2)
    )

    print(
        f"MLP width={width}, "
        f"accuracy={model['metrics']['accuracy']:.4f}, "
        f"saved={destination / 'model.json'}",
        flush=True,
    )

print("WP4 MLP model generation completed.")
