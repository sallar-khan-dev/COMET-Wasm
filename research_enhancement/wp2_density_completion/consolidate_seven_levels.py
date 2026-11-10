import csv
import math
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path("/home/sallar/wasiMultitenant")
SOURCE = ROOT / "results/raw/density"
OUT = ROOT / "results/processed/density"
OUT.mkdir(parents=True, exist_ok=True)

MODELS = [
    "logistic_regression", "naive_bayes", "decision_tree",
    "kmeans", "random_forest", "svm", "mlp"
]
BACKENDS = ["wasmtime", "docker"]
LEVELS = [1, 5, 10, 20, 50, 100, 200]
METRICS = ["rss_mib", "pss_mib", "private_mib"]

try:
    from scipy.stats import t
except ImportError:
    raise SystemExit("SciPy required. Run with .venv/bin/python.")

results = []
issues = []

for backend in BACKENDS:
    for model in MODELS:
        path = SOURCE / f"{backend}_{model}_density_full.csv"

        if not path.exists():
            issues.append(f"Missing: {path}")
            continue

        groups = defaultdict(list)

        with path.open(newline="") as f:
            reader = csv.DictReader(f)
            required = {"physical_tenants", "repetition", *METRICS}
            missing = required - set(reader.fieldnames or [])
            if missing:
                issues.append(f"{path.name}: missing columns {sorted(missing)}")
                continue

            for record in reader:
                try:
                    level = int(record["physical_tenants"])
                    rep = int(record["repetition"])
                    values = {m: float(record[m]) for m in METRICS}
                    if not all(math.isfinite(v) and v >= 0 for v in values.values()):
                        raise ValueError("invalid memory measurement")
                    groups[level].append((rep, values))
                except (ValueError, TypeError, KeyError) as exc:
                    issues.append(f"{path.name}: invalid record: {exc}")

        for level in LEVELS:
            observations = groups[level]
            reps = [rep for rep, _ in observations]
            n = len(observations)

            if n < 20:
                issues.append(f"{backend}/{model}/{level}: only {n} repetitions")
            if len(set(reps)) != n:
                issues.append(f"{backend}/{model}/{level}: duplicate repetition IDs")

            row = {
                "backend": backend,
                "model": model,
                "physical_tenants": level,
                "n": n,
            }

            for metric in METRICS:
                values = [v[metric] for _, v in observations]
                mean = statistics.mean(values) if values else float("nan")
                sd = statistics.stdev(values) if n > 1 else float("nan")
                half = (
                    t.ppf(0.975, n - 1) * sd / math.sqrt(n)
                    if n > 1 else float("nan")
                )
                row[f"{metric}_mean"] = mean
                row[f"{metric}_sd"] = sd
                row[f"{metric}_ci95_low"] = mean - half
                row[f"{metric}_ci95_high"] = mean + half
                row[f"{metric}_ci95_relative_pct"] = (
                    100 * half / mean if mean > 0 else float("nan")
                )

            results.append(row)

        unexpected = set(groups) - set(LEVELS)
        if unexpected:
            issues.append(f"{path.name}: unexpected levels {sorted(unexpected)}")

output = OUT / "density_seven_levels_statistical_summary.csv"

if results:
    with output.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=results[0].keys())
        writer.writeheader()
        writer.writerows(results)

report = OUT / "density_seven_levels_validation.txt"
report.write_text("\n".join(issues) if issues else "PASS: All 98 conditions validated.")

print(f"Conditions analysed: {len(results)}/98")
print(f"Validation issues: {len(issues)}")
print(f"Summary: {output}")
print(f"Validation: {report}")

for issue in issues[:30]:
    print("WARNING:", issue)
