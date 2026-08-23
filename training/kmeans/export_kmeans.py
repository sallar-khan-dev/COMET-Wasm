#!/usr/bin/env python3

import json
from pathlib import Path

import pandas as pd
from sklearn.datasets import load_iris
from sklearn.cluster import KMeans

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "models" / "kmeans" / "iris"
OUT.mkdir(parents=True, exist_ok=True)

data = load_iris()
X = data.data.astype(float)

feature_names = [
    str(x).replace(" ", "_").replace("(", "").replace(")", "")
    for x in data.feature_names
]

clf = KMeans(
    n_clusters=3,
    n_init=10,
    random_state=42,
)

labels = clf.fit_predict(X)

model = {
    "model": "KMeans",
    "dataset": "iris",
    "task": "nearest_centroid_inference",

    "feature_names": feature_names,
    "n_clusters": int(clf.n_clusters),
    "n_features": int(X.shape[1]),

    "centroids": clf.cluster_centers_.astype(float).tolist(),

    "profile_hint": {
        "compute_class": "centroid_distance",
        "memory_class": "low_medium",
        "complexity": "O(k*d)",
        "samples": int(X.shape[0]),
    }
}

(OUT / "model.json").write_text(
    json.dumps(model, indent=2)
)

df = pd.DataFrame(X, columns=feature_names)
df["label"] = labels
df.to_csv(OUT / "samples.csv", index=False)

print("Saved:", OUT / "model.json")
print("Clusters:", clf.n_clusters)
print("Features:", X.shape[1])
print("Samples:", X.shape[0])
print("Centroid shape:", clf.cluster_centers_.shape)
