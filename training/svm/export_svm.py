#!/usr/bin/env python3

import json
from pathlib import Path

import pandas as pd
from sklearn.datasets import load_breast_cancer
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC
from sklearn.metrics import (
    accuracy_score,
    precision_recall_fscore_support,
)

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "models/svm/breast_cancer"
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

clf = SVC(
    kernel="rbf",
    gamma="scale",
    C=1.0,
    probability=False,
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

model = {
    "model": "SVM_RBF",
    "dataset": "breast_cancer",
    "task": "binary_classification",

    "feature_names": feature_names,

    "classes": clf.classes_.astype(int).tolist(),

    "mean": scaler.mean_.astype(float).tolist(),
    "scale": scaler.scale_.astype(float).tolist(),

    "support_vectors": clf.support_vectors_.astype(float).tolist(),
    "dual_coef": clf.dual_coef_[0].astype(float).tolist(),
    "intercept": float(clf.intercept_[0]),
    "gamma": float(clf._gamma),

    "n_support": clf.n_support_.astype(int).tolist(),
    "n_support_total": int(clf.support_vectors_.shape[0]),

    "metrics": {
        "accuracy": float(accuracy_score(y_test, pred)),
        "precision": float(p),
        "recall": float(r),
        "f1": float(f1),
    },

    "profile_hint": {
        "compute_class": "kernel_compute_heavy",
        "memory_class": "medium_high",
        "complexity": "O(support_vectors*d)",
        "features": int(X.shape[1]),
        "support_vectors": int(clf.support_vectors_.shape[0]),
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
print("Support vectors:", clf.support_vectors_.shape[0])
print("Support vectors/class:", clf.n_support_.tolist())
print("Gamma:", clf._gamma)
print("Intercept:", clf.intercept_[0])
print("Train samples:", len(X_train))
print("Test samples:", len(X_test))
print(json.dumps(model["metrics"], indent=2))
