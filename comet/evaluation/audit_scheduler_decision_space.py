#!/usr/bin/env python3

from collections import Counter, defaultdict

from comet.scheduler.scheduler import CometScheduler


MODELS = [
    "logistic_regression",
    "naive_bayes",
    "decision_tree",
    "kmeans",
    "random_forest",
    "svm",
    "mlp",
]

CONCURRENCY_LEVELS = [
    1, 2, 4, 8, 16, 32, 64, 128, 256
]

TENANT_LEVELS = [
    20, 100, 200
]

# Existing evaluation constraints only.
CONSTRAINTS = [
    ("unconstrained", None, None),
    ("memory_100", 100.0, None),
    ("sla_4ms", None, 4.0),
    ("memory_100_sla_4ms", 100.0, 4.0),
]


scheduler = CometScheduler()

overall = Counter()
by_constraint = defaultdict(Counter)

docker_cases = []
rejected_cases = []


for model in MODELS:
    for concurrency in CONCURRENCY_LEVELS:
        for tenants in TENANT_LEVELS:
            for (
                constraint_name,
                memory_budget,
                sla,
            ) in CONSTRAINTS:

                result = scheduler.schedule(
                    model=model,
                    concurrency=concurrency,
                    tenants=tenants,
                    memory_budget_mib=memory_budget,
                    sla_p95_ms=sla,
                )

                backend = (
                    result["selected_backend"]
                    if result["admitted"]
                    else "rejected"
                )

                overall[backend] += 1
                by_constraint[
                    constraint_name
                ][backend] += 1

                if backend == "docker":
                    docker_cases.append({
                        "model": model,
                        "concurrency":
                            concurrency,
                        "tenants":
                            tenants,
                        "constraint":
                            constraint_name,
                        "memory_budget_mib":
                            memory_budget,
                        "sla_p95_ms":
                            sla,
                        "score":
                            result[
                                "selected_score"
                            ],
                    })

                if backend == "rejected":
                    rejected_cases.append({
                        "model": model,
                        "concurrency":
                            concurrency,
                        "tenants":
                            tenants,
                        "constraint":
                            constraint_name,
                    })


print("=" * 78)
print("COMET-WASM SCHEDULER DECISION-SPACE AUDIT")
print("=" * 78)

total = sum(overall.values())

print(f"\nTotal decisions: {total}")
print("Overall:")
for key in [
    "wasmtime",
    "docker",
    "rejected",
]:
    print(
        f"  {key:10s}: "
        f"{overall[key]}"
    )


print("\nBy existing constraint regime:")

for name, _, _ in CONSTRAINTS:

    counts = by_constraint[name]

    print(
        f"  {name:22s} "
        f"W={counts['wasmtime']:3d} "
        f"D={counts['docker']:3d} "
        f"R={counts['rejected']:3d}"
    )


print(
    f"\nDocker-selected cases: "
    f"{len(docker_cases)}"
)

for case in docker_cases[:50]:
    print(
        "  "
        f"{case['model']:20s} "
        f"C={case['concurrency']:3d} "
        f"T={case['tenants']:3d} "
        f"{case['constraint']}"
    )


if len(docker_cases) > 50:
    print(
        f"  ... plus "
        f"{len(docker_cases) - 50} more"
    )


print(
    f"\nRejected cases: "
    f"{len(rejected_cases)}"
)

print("\nAUDIT COMPLETE")
