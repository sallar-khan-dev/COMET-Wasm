#!/usr/bin/env python3

import csv
import json
import math
from collections import Counter
from pathlib import Path
from statistics import mean, stdev

try:
    from scipy.stats import t as student_t
except ImportError:
    student_t = None


RAW_DIR = Path("results/raw/evaluation/live_heldout")
SUMMARY_PATH = Path(
    "results/processed/evaluation/live_heldout_summary.json"
)

OUT_CSV = Path(
    "results/processed/evaluation/live_heldout_canonical.csv"
)

OUT_JSON = Path(
    "results/processed/evaluation/live_heldout_canonical.json"
)

MODELS = [
    "logistic_regression",
    "naive_bayes",
    "decision_tree",
    "kmeans",
    "random_forest",
    "svm",
    "mlp",
]

POLICIES = [
    "comet",
    "wasmtime_only",
    "docker_only",
    "random",
    "best_static",
]

LEVELS = [24, 48, 96, 192]


def ci95(values):
    vals = [float(x) for x in values]

    n = len(vals)
    mu = mean(vals)

    if n < 2:
        return {
            "mean": mu,
            "half_width": math.inf,
            "relative": math.inf,
        }

    se = stdev(vals) / math.sqrt(n)

    if student_t is not None:
        critical = student_t.ppf(0.975, n - 1)
    else:
        # Conservative fallback for environments without scipy.
        critical = 1.96

    hw = critical * se

    rel = (
        hw / abs(mu)
        if mu != 0
        else math.inf
    )

    return {
        "mean": mu,
        "half_width": hw,
        "relative": rel,
    }


def f(row, name, default=None):
    value = row.get(name, "")

    if value in ("", None):
        return default

    return float(value)


with SUMMARY_PATH.open() as fh:
    summary = json.load(fh)


summary_map = {}

for cell in summary["cells"]:
    key = (
        cell["model"],
        cell["policy"],
        int(cell["concurrency"]),
    )
    summary_map[key] = cell


records = []


for model in MODELS:

    for policy in POLICIES:

        for concurrency in LEVELS:

            path = RAW_DIR / (
                f"{model}__{policy}__c{concurrency}.csv"
            )

            if not path.exists():
                raise RuntimeError(
                    f"Missing raw cell: {path}"
                )

            with path.open(newline="") as fh:
                rows = list(csv.DictReader(fh))

            if not rows:
                raise RuntimeError(
                    f"Empty raw cell: {path}"
                )

            repetitions = len(rows)

            p95 = ci95([
                f(r, "p95_latency_ms")
                for r in rows
            ])

            throughput = ci95([
                f(r, "throughput_rps")
                for r in rows
            ])

            mean_latency = ci95([
                f(r, "mean_latency_ms")
                for r in rows
            ])

            p50 = ci95([
                f(r, "p50_latency_ms")
                for r in rows
            ])

            p99 = ci95([
                f(r, "p99_latency_ms")
                for r in rows
            ])

            admission = mean([
                f(r, "admission_rate", 0.0)
                for r in rows
            ])

            correctness = mean([
                f(r, "correctness_rate", 0.0)
                for r in rows
            ])

            successful_requests = sum(
                int(float(
                    r.get("successful_requests", 0)
                ))
                for r in rows
            )

            request_errors = sum(
                int(float(
                    r.get("request_errors", 0)
                ))
                for r in rows
            )

            scheduler_ns = [
                f(
                    r,
                    "mean_scheduler_decision_ns",
                    None,
                )
                for r in rows
            ]

            scheduler_ns = [
                x for x in scheduler_ns
                if x is not None
                and math.isfinite(x)
            ]

            scheduler_mean_ns = (
                mean(scheduler_ns)
                if scheduler_ns
                else None
            )

            # Backend audit.
            backend_values = [
                r.get(
                    "selected_backend",
                    "",
                ).strip()
                for r in rows
                if r.get(
                    "selected_backend",
                    "",
                ).strip()
            ]

            backend_counts = Counter(
                backend_values
            )

            if backend_values:
                selected_backend_mode = (
                    backend_counts.most_common(1)[0][0]
                )

                selected_backend_wasmtime_reps = (
                    backend_counts.get(
                        "wasmtime",
                        0,
                    )
                )

                selected_backend_docker_reps = (
                    backend_counts.get(
                        "docker",
                        0,
                    )
                )

                backend_audit_status = "recorded"

            else:
                selected_backend_mode = ""
                selected_backend_wasmtime_reps = 0
                selected_backend_docker_reps = 0
                backend_audit_status = (
                    "legacy_schema_missing"
                )

            key = (
                model,
                policy,
                concurrency,
            )

            scell = summary_map.get(key)

            if scell is None:
                raise RuntimeError(
                    f"Missing summary cell: {key}"
                )

            # Recompute precision directly from raw repetitions.
            recomputed_ci_target_met = (
                repetitions >= summary[
                    "min_repetitions"
                ]
                and p95["relative"]
                <= summary[
                    "relative_ci_target"
                ]
                and throughput["relative"]
                <= summary[
                    "relative_ci_target"
                ]
            )

            summary_ci_target_met = bool(
                scell["ci_target_met"]
            )

            if (
                recomputed_ci_target_met
                != summary_ci_target_met
            ):
                raise RuntimeError(
                    "CI convergence mismatch for "
                    f"{key}: raw="
                    f"{recomputed_ci_target_met}, "
                    "summary="
                    f"{summary_ci_target_met}"
                )

            stop_reason = (
                "precision_target_met"
                if summary_ci_target_met
                else "max_repetitions"
            )

            record = {
                "model": model,
                "policy": policy,
                "concurrency": concurrency,

                "repetitions": repetitions,
                "ci_target_met":
                    summary_ci_target_met,
                "stop_reason": stop_reason,

                "admission_rate_mean":
                    admission,
                "correctness_rate_mean":
                    correctness,

                "successful_requests_total":
                    successful_requests,
                "request_errors_total":
                    request_errors,

                "mean_latency_ms":
                    mean_latency["mean"],

                "p50_latency_ms":
                    p50["mean"],

                "p95_latency_ms":
                    p95["mean"],
                "p95_ci95_half_width_ms":
                    p95["half_width"],
                "p95_relative_ci":
                    p95["relative"],

                "p99_latency_ms":
                    p99["mean"],

                "throughput_rps":
                    throughput["mean"],
                "throughput_ci95_half_width_rps":
                    throughput["half_width"],
                "throughput_relative_ci":
                    throughput["relative"],

                "mean_scheduler_decision_ns":
                    scheduler_mean_ns,

                "selected_backend_mode":
                    selected_backend_mode,
                "selected_backend_wasmtime_reps":
                    selected_backend_wasmtime_reps,
                "selected_backend_docker_reps":
                    selected_backend_docker_reps,
                "backend_audit_status":
                    backend_audit_status,

                "raw_file":
                    str(path),
            }

            records.append(record)


if len(records) != 140:
    raise RuntimeError(
        f"Expected 140 records, got "
        f"{len(records)}"
    )


OUT_CSV.parent.mkdir(
    parents=True,
    exist_ok=True,
)

fields = list(records[0].keys())

with OUT_CSV.open(
    "w",
    newline="",
) as fh:

    writer = csv.DictWriter(
        fh,
        fieldnames=fields,
    )

    writer.writeheader()
    writer.writerows(records)


payload = {
    "schema_version":
        "comet-live-heldout-canonical-v1",

    "source_summary":
        str(SUMMARY_PATH),

    "source_raw_directory":
        str(RAW_DIR),

    "cell_count":
        len(records),

    "metadata": {
        k: summary.get(k)
        for k in [
            "heldout_concurrencies",
            "physical_units",
            "tenants",
            "requests_per_repetition",
            "min_repetitions",
            "max_repetitions",
            "confidence",
            "relative_ci_target",
            "best_static_backend",
        ]
    },

    "cells": records,
}

with OUT_JSON.open("w") as fh:
    json.dump(
        payload,
        fh,
        indent=2,
    )


conv = Counter(
    r["ci_target_met"]
    for r in records
)

stops = Counter(
    r["stop_reason"]
    for r in records
)

backend_status = Counter(
    r["backend_audit_status"]
    for r in records
)


print("=" * 72)
print("COMET-WASM HELD-OUT CONSOLIDATION")
print("=" * 72)

print("Canonical cells:", len(records))
print(
    "CI target met:",
    conv.get(True, 0),
)
print(
    "CI target not met:",
    conv.get(False, 0),
)

print("\nStop reasons:")
for k, v in stops.items():
    print(f"  {k}: {v}")

print("\nBackend audit:")
for k, v in backend_status.items():
    print(f"  {k}: {v}")

print("\nOutputs:")
print(" ", OUT_CSV)
print(" ", OUT_JSON)

print("\nPASS")
