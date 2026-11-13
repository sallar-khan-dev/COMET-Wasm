import json
import csv
from pathlib import Path

ROOT = Path("/home/sallar/wasiMultitenant")
EXEC = ROOT / "results/processed/execution_time"
PERF = ROOT / "results/processed/performance"
OUT = ROOT / "results/processed/crossover"

MODELS = [
    "decision_tree",
    "kmeans",
    "logistic_regression",
    "mlp",
    "naive_bayes",
    "random_forest",
    "svm",
]

def load(path):
    with path.open() as f:
        return json.load(f)

def flatten(obj, prefix=""):
    result = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else k
            result.update(flatten(v, key))
    elif isinstance(obj, (int, float, str, bool)):
        result[prefix] = obj
    return result

rows = []

for model in MODELS:
    row = {"model": model}

    for backend in ["wasmtime", "docker"]:
        e = load(
            EXEC /
            f"{backend}_{model}_execution_time_full_summary.json"
        )
        p = load(
            PERF /
            f"{backend}_{model}_performance_full_summary.json"
        )

        for key, value in flatten(e).items():
            row[f"{backend}.execution.{key}"] = value

        for key, value in flatten(p).items():
            row[f"{backend}.performance.{key}"] = value

    rows.append(row)

columns = sorted(set().union(*(r.keys() for r in rows)))
columns.remove("model")
columns.insert(0, "model")

output = OUT / "wp4_baseline_existing_measurements.csv"

with output.open("w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=columns)
    writer.writeheader()
    writer.writerows(rows)

print(f"Saved: {output}")
print(f"Models: {len(rows)}")
print(f"Columns: {len(columns)}")
