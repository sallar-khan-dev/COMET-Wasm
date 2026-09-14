#!/usr/bin/env python3

import csv
import json
from pathlib import Path

from comet.scheduler.scheduler import CometScheduler


OUT_CSV = Path(
    "results/processed/evaluation/"
    "density_capacity_results.csv"
)

OUT_JSON = Path(
    "results/processed/evaluation/"
    "density_capacity_results.json"
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

BACKENDS = [
    "wasmtime",
    "docker",
]

TENANT_LEVELS = [20, 100, 200]

CONCURRENCY = 32
MEMORY_BUDGET_MIB = 100.0


scheduler = CometScheduler()

rows = []


def candidate_for(decision, backend):
    for candidate in decision["candidates"]:
        if candidate["backend"] == backend:
            return candidate

    raise RuntimeError(
        f"Missing backend candidate: {backend}"
    )


# ============================================================
# Evaluate only empirically measured density levels.
# No extrapolation beyond 200 tenants is permitted here.
# ============================================================

for model in MODELS:

    for tenants in TENANT_LEVELS:

        decision = scheduler.schedule(
            model=model,
            concurrency=CONCURRENCY,
            tenants=tenants,
            memory_budget_mib=MEMORY_BUDGET_MIB,
        )

        for backend in BACKENDS:

            candidate = candidate_for(
                decision,
                backend,
            )

            throughput = float(
                candidate["throughput_rps"]
            )

            memory = float(
                candidate["predicted_memory_mib"]
            )

            p95 = float(
                candidate["predicted_p95_ms"]
            )

            feasible = bool(
                candidate["feasible"]
            )

            # Density-normalised serving efficiency:
            # successful serving throughput per physical tenant.
            throughput_per_tenant = (
                throughput / tenants
                if feasible
                else None
            )

            rows.append({
                "model": model,
                "backend": backend,
                "concurrency": CONCURRENCY,
                "tenants": tenants,
                "memory_budget_mib":
                    MEMORY_BUDGET_MIB,
                "predicted_memory_mib":
                    memory,
                "predicted_p95_ms":
                    p95,
                "throughput_rps":
                    throughput,
                "memory_feasible":
                    memory <= MEMORY_BUDGET_MIB,
                "scheduler_feasible":
                    feasible,
                "throughput_per_tenant_rps":
                    throughput_per_tenant,
                "density_point_empirically_measured":
                    True,
            })


# ============================================================
# Highest TESTED tenant density satisfying 100 MiB.
# This is deliberately not an extrapolated maximum capacity.
# ============================================================

capacity = []

for model in MODELS:

    for backend in BACKENDS:

        subset = [
            row for row in rows
            if row["model"] == model
            and row["backend"] == backend
            and row["memory_feasible"]
        ]

        highest = (
            max(
                row["tenants"]
                for row in subset
            )
            if subset
            else 0
        )

        capacity.append({
            "model": model,
            "backend": backend,
            "memory_budget_mib":
                MEMORY_BUDGET_MIB,
            "highest_tested_feasible_tenants":
                highest,
            "tested_upper_bound_tenants":
                max(TENANT_LEVELS),
            "at_least_tested_upper_bound":
                highest == max(TENANT_LEVELS),
        })


# ============================================================
# Write CSV
# ============================================================

OUT_CSV.parent.mkdir(
    parents=True,
    exist_ok=True,
)

with OUT_CSV.open(
    "w",
    newline="",
) as fh:

    writer = csv.DictWriter(
        fh,
        fieldnames=list(
            rows[0].keys()
        ),
    )

    writer.writeheader()
    writer.writerows(rows)


payload = {
    "schema_version":
        "comet-density-capacity-v1",

    "methodology": {
        "characterization":
            "offline",

        "concurrency":
            CONCURRENCY,

        "memory_budget_mib":
            MEMORY_BUDGET_MIB,

        "tenant_levels":
            TENANT_LEVELS,

        "capacity_rule":
            (
                "Highest empirically tested tenant "
                "level satisfying the fixed memory "
                "budget; no capacity extrapolation "
                "beyond 200 tenants."
            ),

        "density_normalized_throughput":
            (
                "successful throughput_rps divided "
                "by physical tenant count"
            ),
    },

    "rows": rows,
    "capacity": capacity,
}

OUT_JSON.write_text(
    json.dumps(
        payload,
        indent=2,
    )
    + "\n"
)


print("=" * 78)
print(
    "COMET-WASM FIXED-BUDGET "
    "DENSITY/CAPACITY ANALYSIS"
)
print("=" * 78)

print(
    f"Concurrency: {CONCURRENCY}"
)
print(
    f"Memory budget: "
    f"{MEMORY_BUDGET_MIB:.1f} MiB"
)
print(
    f"Measured tenant levels: "
    f"{TENANT_LEVELS}"
)

print("\nHighest TESTED feasible density:")

for item in capacity:

    suffix = (
        " (>= tested maximum)"
        if item[
            "at_least_tested_upper_bound"
        ]
        else ""
    )

    print(
        f"  {item['model']:20s} "
        f"{item['backend']:8s} "
        f"{item['highest_tested_feasible_tenants']:3d}"
        f"{suffix}"
    )


print("\n100 MiB feasibility at 200 tenants:")

for model in MODELS:

    vals = {
        r["backend"]: r
        for r in rows
        if r["model"] == model
        and r["tenants"] == 200
    }

    print(
        f"  {model:20s} "
        f"W={vals['wasmtime']['predicted_memory_mib']:.3f} MiB "
        f"({'PASS' if vals['wasmtime']['memory_feasible'] else 'FAIL'})  "
        f"D={vals['docker']['predicted_memory_mib']:.3f} MiB "
        f"({'PASS' if vals['docker']['memory_feasible'] else 'FAIL'})"
    )


print("\nOutputs:")
print(f"  {OUT_CSV}")
print(f"  {OUT_JSON}")

print("\nPASS")
