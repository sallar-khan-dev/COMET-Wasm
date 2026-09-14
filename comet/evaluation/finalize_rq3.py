#!/usr/bin/env python3

import csv
import json
from collections import Counter
from pathlib import Path
from statistics import mean

ROOT = Path(".")
RAW = ROOT / "results/raw/evaluation/live_heldout"
CANON = ROOT / "results/processed/evaluation/live_heldout_canonical.csv"
SIM = ROOT / "results/processed/evaluation/simulation_sanity.csv"

OUT_CSV = ROOT / "results/processed/evaluation/rq3_scheduler_results.csv"
OUT_JSON = ROOT / "results/processed/evaluation/rq3_scheduler_results.json"

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

POLICIES = [
    "comet",
    "wasmtime_only",
    "docker_only",
    "random",
    "best_static",
]


def f(x):
    return float(x)


# ============================================================
# Canonical live results
# ============================================================

with CANON.open(newline="") as fh:
    canonical = list(csv.DictReader(fh))

if len(canonical) != 140:
    raise RuntimeError(
        f"Expected 140 canonical cells, got {len(canonical)}"
    )

canon_map = {
    (r["model"], r["policy"], int(r["concurrency"])): r
    for r in canonical
}


# ============================================================
# Recover P99 from immutable raw repetitions
# ============================================================

rows_out = []

for model in MODELS:
    for policy in POLICIES:
        for c in LEVELS:

            path = RAW / f"{model}__{policy}__c{c}.csv"

            if not path.exists():
                raise FileNotFoundError(path)

            with path.open(newline="") as fh:
                raw_rows = list(csv.DictReader(fh))

            if not raw_rows:
                raise RuntimeError(f"Empty raw file: {path}")

            p99 = mean(
                f(r["p99_latency_ms"])
                for r in raw_rows
            )

            base = canon_map[(model, policy, c)]

            rows_out.append({
                "model": model,
                "policy": policy,
                "concurrency": c,
                "repetitions": len(raw_rows),
                "p95_latency_ms":
                    f(base["p95_latency_ms"]),
                "p99_latency_ms":
                    p99,
                "throughput_rps":
                    f(base["throughput_rps"]),
                "ci_target_met":
                    base["ci_target_met"],
                "selected_backend":
                    base["selected_backend_mode"],
            })


# ============================================================
# Placement accuracy
# Compare COMET's recorded selection with empirically better
# fixed backend in the held-out measurements.
# ============================================================

placement = []
latency_matches = 0
throughput_matches = 0
recorded = 0

for model in MODELS:
    for c in LEVELS:

        comet = canon_map[(model, "comet", c)]
        w = canon_map[(model, "wasmtime_only", c)]
        d = canon_map[(model, "docker_only", c)]

        selected = comet["selected_backend_mode"]

        better_latency = (
            "wasmtime"
            if f(w["p95_latency_ms"]) < f(d["p95_latency_ms"])
            else "docker"
        )

        better_throughput = (
            "wasmtime"
            if f(w["throughput_rps"]) > f(d["throughput_rps"])
            else "docker"
        )

        if selected:
            recorded += 1
            latency_matches += int(selected == better_latency)
            throughput_matches += int(
                selected == better_throughput
            )

        placement.append({
            "model": model,
            "concurrency": c,
            "comet_selected_backend":
                selected if selected else "legacy_unrecorded",
            "lower_p95_backend": better_latency,
            "higher_throughput_backend":
                better_throughput,
        })


# ============================================================
# Backend switching
#
# Current COMET evaluation makes one backend decision for each
# scenario/repetition. Count observed transitions only where
# backend provenance exists; do not reconstruct legacy files.
# ============================================================

switches = 0
switch_observations = 0

for model in MODELS:
    for c in LEVELS:

        path = RAW / f"{model}__comet__c{c}.csv"

        with path.open(newline="") as fh:
            records = list(csv.DictReader(fh))

        if (
            not records
            or "selected_backend" not in records[0]
        ):
            continue

        seq = [
            r["selected_backend"]
            for r in records
            if r.get("selected_backend")
        ]

        if not seq:
            continue

        switch_observations += 1

        switches += sum(
            a != b
            for a, b in zip(seq, seq[1:])
        )


# ============================================================
# Profile-replay constrained scenarios
# ============================================================

with SIM.open(newline="") as fh:
    simulation = list(csv.DictReader(fh))

scenario_names = {
    "memory_constrained",
    "latency_constrained",
    "combined_pressure",
}

constrained = [
    r for r in simulation
    if r.get("scenario_id") in scenario_names
]


# ============================================================
# Write live result table
# ============================================================

OUT_CSV.parent.mkdir(parents=True, exist_ok=True)

with OUT_CSV.open("w", newline="") as fh:
    writer = csv.DictWriter(
        fh,
        fieldnames=list(rows_out[0].keys()),
    )
    writer.writeheader()
    writer.writerows(rows_out)


payload = {
    "schema_version": "comet-rq3-results-v1",

    "methodology": {
        "characterization":
            "offline",
        "runtime_profile_refresh":
            False,
        "runtime_actions": [
            "feasibility_filtering",
            "backend_selection",
            "admission",
            "density_aware_placement",
        ],
    },

    "live_heldout": {
        "cells": len(rows_out),
        "models": len(MODELS),
        "policies": len(POLICIES),
        "concurrency_levels": LEVELS,
    },

    "placement_accuracy": {
        "recorded_scenarios": recorded,
        "latency_matches": latency_matches,
        "throughput_matches": throughput_matches,
        "latency_accuracy":
            latency_matches / recorded
            if recorded else None,
        "throughput_accuracy":
            throughput_matches / recorded
            if recorded else None,
        "audit": placement,
    },

    "backend_switching": {
        "recorded_scenario_sequences":
            switch_observations,
        "observed_switches":
            switches,
        "note":
            "Legacy LR COMET files without selected_backend "
            "are excluded rather than reconstructed.",
    },

    "profile_replay_constraints": constrained,

    "notes": [
        "Profile-replay results validate scheduler logic and "
        "are not live performance measurements.",
        "Adaptive online profile refresh is not implemented.",
        "Raw held-out repetitions remain immutable.",
    ],
}

OUT_JSON.write_text(
    json.dumps(payload, indent=2)
)

print("=" * 78)
print("COMET-WASM SRQ3 CONSOLIDATION")
print("=" * 78)

print(f"Live scheduler cells: {len(rows_out)}")

print("\nPlacement accuracy:")
print(
    f"  recorded scenarios: {recorded}/28"
)
print(
    f"  lower-P95 match: {latency_matches}/{recorded}"
)
print(
    f"  higher-throughput match: "
    f"{throughput_matches}/{recorded}"
)

print("\nBackend switching:")
print(
    f"  recorded scenario sequences: "
    f"{switch_observations}"
)
print(
    f"  observed switches: {switches}"
)

print("\nConstrained profile-replay rows:")
print(f"  {len(constrained)}")

print("\nOutputs:")
print(f"  {OUT_CSV}")
print(f"  {OUT_JSON}")

print("\nPASS")
