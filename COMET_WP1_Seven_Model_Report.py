#!/usr/bin/env python3

import csv
import json
import statistics
from pathlib import Path
from collections import defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path("/home/sallar/wasiMultitenant")
BASE = ROOT / "research_enhancement/automated_supervisor_workplan"

SOURCES = {
    "LR_RF": BASE / "wp1_matched_correction/20261112_180510_2192337",
    "FIVE": BASE / "wp1_five_model_formal/20261112_231004_2309146"
}

OUT = ROOT / "results/processed/wp1_seven_model_20261113"
OUT.mkdir(parents=True, exist_ok=True)

MODELS = ["lr", "nb", "dt", "kmeans", "rf", "svm", "mlp"]
BACKENDS = ["wasmtime", "docker"]
RATES = [100, 300, 600, 1200, 2400]

runs = defaultdict(list)
source_states = {}

for source, folder in SOURCES.items():
    path = folder / "state.json"

    if not path.exists():
        raise SystemExit(f"Missing checkpoint: {path}")

    state = json.loads(path.read_text())
    source_states[source] = state

    for r in state["WP1"]["runs"]:
        key = (
            r["model"],
            r["backend"],
            int(r["offered_rps"])
        )
        runs[key].append(r)

def mean_metric(items, key):
    values = [
        float(x[key]) for x in items
        if isinstance(x.get(key), (int, float))
    ]
    return statistics.mean(values) if values else None

rows = []

for model in MODELS:
    for backend in BACKENDS:
        for rate in RATES:

            sample = runs[(model, backend, rate)]

            if not sample:
                raise SystemExit(
                    f"Missing configuration: {model}/{backend}/{rate}"
                )

            offered = sum(x.get("offered", 0) or 0 for x in sample)
            success = sum(x.get("success", 0) or 0 for x in sample)

            row = {
                "model": model,
                "backend": backend,
                "offered_rps": rate,
                "repetitions": len(sample),
                "offered_requests": offered,
                "successful_requests": success,
                "success_pct": 100 * success / offered if offered else None,
                "mean_p50_ms": mean_metric(sample, "p50_ms"),
                "mean_p95_ms": mean_metric(sample, "p95_ms"),
                "mean_p99_ms": mean_metric(sample, "p99_ms"),
                "mean_scheduling_p99_ms": mean_metric(
                    sample, "sched_p99_ms"
                ),
                "mean_goodput_rps": statistics.mean(
                    (x.get("success", 0) or 0) / 15
                    for x in sample
                ),
                "correctness_pass_runs": sum(
                    x.get("correctness_pass") is True for x in sample
                )
            }

            rows.append(row)

# Save complete 70-configuration table.
csv_path = OUT / "WP1_Seven_Model_Results.csv"

with csv_path.open("w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
    writer.writeheader()
    writer.writerows(rows)

# Save repetition-count summary.
with (OUT / "WP1_Repetition_Counts.csv").open("w", newline="") as f:
    writer = csv.writer(f)
    writer.writerow(["model", "wasmtime", "docker", "total"])

    for model in MODELS:
        w = sum(
            len(runs[(model, "wasmtime", rate)])
            for rate in RATES
        )
        d = sum(
            len(runs[(model, "docker", rate)])
            for rate in RATES
        )
        writer.writerow([model, w, d, w + d])

def plot_metric(metric, title, ylabel, filename):

    fig, axes = plt.subplots(2, 4, figsize=(17, 9))

    for i, model in enumerate(MODELS):
        ax = axes.flat[i]

        for backend, style in [
            ("wasmtime", "o-"),
            ("docker", "s--")
        ]:
            selected = [
                next(
                    x for x in rows
                    if x["model"] == model
                    and x["backend"] == backend
                    and x["offered_rps"] == rate
                )
                for rate in RATES
            ]

            ax.plot(
                RATES,
                [x[metric] for x in selected],
                style,
                label=backend
            )

        ax.set_title(model.upper())
        ax.set_xlabel("Offered RPS")
        ax.set_ylabel(ylabel)
        ax.set_xticks(RATES)
        ax.tick_params(axis="x", rotation=45)
        ax.grid(alpha=0.3)
        ax.legend()

    axes.flat[7].axis("off")
    fig.suptitle(title, fontsize=16)
    fig.tight_layout()

    fig.savefig(OUT / (filename + ".png"), dpi=200)
    fig.savefig(OUT / (filename + ".svg"))
    plt.close(fig)

plot_metric(
    "mean_p95_ms",
    "COMET-Wasm: Seven-Model P95 Latency",
    "P95 Latency (ms)",
    "WP1_P95_Latency"
)

plot_metric(
    "mean_goodput_rps",
    "COMET-Wasm: Seven-Model Successful Throughput",
    "Successful Requests/s",
    "WP1_Goodput"
)

plot_metric(
    "success_pct",
    "COMET-Wasm: Seven-Model Request Success",
    "Success (%)",
    "WP1_Success_Rate"
)

plot_metric(
    "repetitions",
    "COMET-Wasm: Independent Repetitions",
    "Number of Repetitions",
    "WP1_Repetitions"
)

metadata = {
    "models": MODELS,
    "backends": BACKENDS,
    "offered_rates": RATES,
    "configurations": len(rows),
    "total_repetitions": sum(len(v) for v in runs.values()),
    "sources": {k: str(v) for k, v in SOURCES.items()},
    "methodology": (
        "All collected repetitions are retained. "
        "Maximum sampling budget is 60. "
        "Precision-unmet observations are not discarded."
    ),
    "interpretation": (
        "Displayed latency values are means of independent-run "
        "percentiles, not pooled request-level percentiles. "
        "Goodput is calculated as successful requests divided "
        "by the configured 15-second measurement window. "
        "Formal confidence interval results remain in the "
        "original experiment checkpoints and reviews."
    )
}

(OUT / "WP1_Provenance.json").write_text(
    json.dumps(metadata, indent=2) + "\n"
)

print("\n========================================")
print("COMET-WASM SEVEN-MODEL REPORT GENERATED")
print("========================================")
print("Configurations:", len(rows))
print("Independent repetitions:", metadata["total_repetitions"])
print("Output directory:", OUT)

for model in MODELS:
    print(
        model.upper(),
        sum(
            len(runs[(model, backend, rate)])
            for backend in BACKENDS for rate in RATES
        ),
        "repetitions"
    )
