#!/usr/bin/env python3

import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean, median

INPUT = Path(
    "results/processed/evaluation/live_heldout_canonical.csv"
)
OUT_CSV = Path(
    "results/processed/evaluation/comet_policy_comparison.csv"
)
OUT_JSON = Path(
    "results/processed/evaluation/comet_policy_comparison.json"
)

BASELINES = [
    "wasmtime_only",
    "docker_only",
    "random",
    "best_static",
]

MODELS = [
    "logistic_regression",
    "naive_bayes",
    "decision_tree",
    "kmeans",
    "random_forest",
    "svm",
    "mlp",
]

LEVELS = [24, 48, 96, 192]


def F(x):
    return float(x)


with INPUT.open(newline="") as f:
    rows = list(csv.DictReader(f))

if len(rows) != 140:
    raise RuntimeError(
        f"Expected 140 canonical cells, found {len(rows)}"
    )

index = {
    (
        r["model"],
        r["policy"],
        int(r["concurrency"]),
    ): r
    for r in rows
}

comparisons = []

for model in MODELS:
    for c in LEVELS:

        comet = index[(model, "comet", c)]

        cp95 = F(comet["p95_latency_ms"])
        crps = F(comet["throughput_rps"])

        for baseline in BASELINES:

            base = index[(model, baseline, c)]

            bp95 = F(base["p95_latency_ms"])
            brps = F(base["throughput_rps"])

            # Positive = COMET improvement.
            latency_improvement_pct = (
                (bp95 - cp95) / bp95 * 100.0
            )

            throughput_improvement_pct = (
                (crps - brps) / brps * 100.0
            )

            latency_ratio = cp95 / bp95
            throughput_ratio = crps / brps

            comparisons.append({
                "model": model,
                "concurrency": c,
                "baseline": baseline,

                "comet_p95_ms": cp95,
                "baseline_p95_ms": bp95,
                "latency_improvement_pct":
                    latency_improvement_pct,
                "latency_ratio":
                    latency_ratio,

                "comet_throughput_rps": crps,
                "baseline_throughput_rps": brps,
                "throughput_improvement_pct":
                    throughput_improvement_pct,
                "throughput_ratio":
                    throughput_ratio,

                "comet_ci_target_met":
                    comet["ci_target_met"],
                "baseline_ci_target_met":
                    base["ci_target_met"],

                "comet_backend":
                    comet["selected_backend_mode"],
                "baseline_backend":
                    base["selected_backend_mode"],
            })


OUT_CSV.parent.mkdir(parents=True, exist_ok=True)

with OUT_CSV.open("w", newline="") as f:
    writer = csv.DictWriter(
        f,
        fieldnames=list(comparisons[0].keys()),
    )
    writer.writeheader()
    writer.writerows(comparisons)


def classify(x, tolerance=1.0):
    """
    +/- 1% practical-equivalence band.
    Positive values favor COMET.
    """
    if x > tolerance:
        return "win"
    if x < -tolerance:
        return "loss"
    return "tie"


summary = {}

for baseline in BASELINES:

    vals = [
        x for x in comparisons
        if x["baseline"] == baseline
    ]

    lat = [
        x["latency_improvement_pct"]
        for x in vals
    ]

    thr = [
        x["throughput_improvement_pct"]
        for x in vals
    ]

    lat_class = Counter(
        classify(x) for x in lat
    )

    thr_class = Counter(
        classify(x) for x in thr
    )

    summary[baseline] = {
        "scenarios": len(vals),

        "latency": {
            "mean_improvement_pct": mean(lat),
            "median_improvement_pct": median(lat),
            "min_improvement_pct": min(lat),
            "max_improvement_pct": max(lat),
            "wins": lat_class["win"],
            "ties": lat_class["tie"],
            "losses": lat_class["loss"],
        },

        "throughput": {
            "mean_improvement_pct": mean(thr),
            "median_improvement_pct": median(thr),
            "min_improvement_pct": min(thr),
            "max_improvement_pct": max(thr),
            "wins": thr_class["win"],
            "ties": thr_class["tie"],
            "losses": thr_class["loss"],
        },
    }


# ---------------------------------------------------------
# COMET backend-selection audit
# ---------------------------------------------------------

comet_rows = [
    r for r in rows
    if r["policy"] == "comet"
]

selection = Counter()

for r in comet_rows:
    backend = r["selected_backend_mode"]

    if backend:
        selection[backend] += 1
    else:
        selection["legacy_unrecorded"] += 1


# Determine empirically better fixed backend for each scenario.
fixed_backend_match = Counter()
scenario_backend_audit = []

for model in MODELS:
    for c in LEVELS:

        comet = index[(model, "comet", c)]
        w = index[(model, "wasmtime_only", c)]
        d = index[(model, "docker_only", c)]

        wp95 = F(w["p95_latency_ms"])
        dp95 = F(d["p95_latency_ms"])

        wrps = F(w["throughput_rps"])
        drps = F(d["throughput_rps"])

        better_latency = (
            "wasmtime"
            if wp95 < dp95
            else "docker"
        )

        better_throughput = (
            "wasmtime"
            if wrps > drps
            else "docker"
        )

        selected = comet["selected_backend_mode"]

        # Four legacy LR COMET files lack the recorded field.
        # Scheduler configuration for these files is not
        # silently reconstructed here.
        if not selected:
            selected_status = "legacy_unrecorded"
        else:
            selected_status = selected

            if selected == better_latency:
                fixed_backend_match[
                    "latency_match"
                ] += 1

            if selected == better_throughput:
                fixed_backend_match[
                    "throughput_match"
                ] += 1

        scenario_backend_audit.append({
            "model": model,
            "concurrency": c,
            "comet_selected_backend":
                selected_status,
            "lower_p95_fixed_backend":
                better_latency,
            "higher_throughput_fixed_backend":
                better_throughput,
        })


payload = {
    "schema_version":
        "comet-policy-comparison-v1",

    "practical_tie_threshold_pct": 1.0,

    "scenario_count": 28,

    "comparison_count":
        len(comparisons),

    "summary": summary,

    "comet_backend_selection": dict(selection),

    "recorded_comet_backend_matches": {
        "latency_match":
            fixed_backend_match["latency_match"],
        "throughput_match":
            fixed_backend_match["throughput_match"],
        "recorded_scenarios":
            sum(
                1 for r in comet_rows
                if r["selected_backend_mode"]
            ),
    },

    "scenario_backend_audit":
        scenario_backend_audit,
}


with OUT_JSON.open("w") as f:
    json.dump(payload, f, indent=2)


print("=" * 78)
print("COMET-WASM HELD-OUT POLICY ANALYSIS")
print("=" * 78)

for baseline in BASELINES:

    s = summary[baseline]

    print(f"\nCOMET vs {baseline}")

    print(
        "  p95 latency:"
        f" mean={s['latency']['mean_improvement_pct']:.2f}%"
        f" median={s['latency']['median_improvement_pct']:.2f}%"
        f" W/T/L={s['latency']['wins']}/"
        f"{s['latency']['ties']}/"
        f"{s['latency']['losses']}"
    )

    print(
        "  throughput :"
        f" mean={s['throughput']['mean_improvement_pct']:.2f}%"
        f" median={s['throughput']['median_improvement_pct']:.2f}%"
        f" W/T/L={s['throughput']['wins']}/"
        f"{s['throughput']['ties']}/"
        f"{s['throughput']['losses']}"
    )


print("\nCOMET recorded backend selection:")
for k, v in selection.items():
    print(f"  {k}: {v}")


print("\nRecorded COMET selection agreement:")
print(
    "  lower-p95 fixed backend:",
    fixed_backend_match["latency_match"],
)
print(
    "  higher-throughput fixed backend:",
    fixed_backend_match["throughput_match"],
)
print(
    "  recorded COMET scenarios:",
    sum(
        1 for r in comet_rows
        if r["selected_backend_mode"]
    ),
)

print("\nOutputs:")
print(" ", OUT_CSV)
print(" ", OUT_JSON)

print("\nPASS")
