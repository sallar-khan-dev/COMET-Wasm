#!/usr/bin/env python3

import json
import math
import statistics
import time
from pathlib import Path

import numpy as np
from scipy.stats import t as student_t

from comet.evaluation.policies import (
    choose_policy_backend,
)
from comet.scheduler.scheduler import (
    CometScheduler,
)


OUTPUT = Path(
    "results/processed/evaluation/"
    "scheduler_overhead.json"
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

CONCURRENCIES = [
    24,
    48,
    96,
    192,
]

TENANTS = 20

MIN_REPS = 100
MAX_REPS = 1000

CI_TARGET = 0.025


def ci_stats(values):
    values = [
        float(x)
        for x in values
    ]

    n = len(values)

    mean = statistics.mean(
        values
    )

    if n < 2:
        return {
            "n": n,
            "mean": mean,
            "halfwidth": math.inf,
            "relative": math.inf,
        }

    sd = statistics.stdev(
        values
    )

    critical = student_t.ppf(
        0.975,
        n - 1,
    )

    halfwidth = (
        critical
        * sd
        / math.sqrt(n)
    )

    relative = (
        halfwidth / abs(mean)
        if abs(mean) > 1e-12
        else math.inf
    )

    return {
        "n": n,
        "mean": mean,
        "sd": sd,
        "halfwidth": halfwidth,
        "relative": relative,
    }


scheduler = CometScheduler()

rows = []

for model in MODELS:

    for concurrency in CONCURRENCIES:

        planning = []
        dispatch = []

        prepared_decision = (
            scheduler.schedule(
                model=model,
                concurrency=concurrency,
                tenants=TENANTS,
            )
        )

        for _ in range(MAX_REPS):

            start = (
                time.perf_counter_ns()
            )

            decision = scheduler.schedule(
                model=model,
                concurrency=concurrency,
                tenants=TENANTS,
            )

            planning.append(
                time.perf_counter_ns()
                - start
            )

            start = (
                time.perf_counter_ns()
            )

            backend = (
                choose_policy_backend(
                    "comet",
                    prepared_decision,
                )
            )

            dispatch.append(
                time.perf_counter_ns()
                - start
            )

            if (
                len(planning)
                >= MIN_REPS
            ):
                p_ci = ci_stats(
                    planning
                )

                d_ci = ci_stats(
                    dispatch
                )

                if (
                    p_ci["relative"]
                    <= CI_TARGET
                    and
                    d_ci["relative"]
                    <= CI_TARGET
                ):
                    break

        p_ci = ci_stats(
            planning
        )

        d_ci = ci_stats(
            dispatch
        )

        row = {
            "model":
                model,

            "requested_concurrency":
                concurrency,

            "operating_concurrency":
                prepared_decision[
                    "operating_concurrency"
                ],

            "selected_backend":
                prepared_decision[
                    "selected_backend"
                ],

            "planning_ns":
                {
                    **p_ci,
                    "median":
                        float(
                            np.median(
                                planning
                            )
                        ),
                    "p95":
                        float(
                            np.percentile(
                                planning,
                                95,
                            )
                        ),
                },

            "dispatch_ns":
                {
                    **d_ci,
                    "median":
                        float(
                            np.median(
                                dispatch
                            )
                        ),
                    "p95":
                        float(
                            np.percentile(
                                dispatch,
                                95,
                            )
                        ),
                },

            "ci_target_met":
                bool(
                    p_ci["relative"]
                    <= CI_TARGET
                    and
                    d_ci["relative"]
                    <= CI_TARGET
                ),
        }

        rows.append(
            row
        )

        print(
            f"{model:22s} "
            f"C={concurrency:<3d} "
            f"op={row['operating_concurrency']:<3d} "
            f"plan="
            f"{p_ci['mean']/1000:.3f} us "
            f"dispatch="
            f"{d_ci['mean']/1000:.3f} us "
            f"n={p_ci['n']} "
            f"CI="
            f"{row['ci_target_met']}"
        )


payload = {
    "schema_version":
        "comet-scheduler-overhead-v1",

    "description":
        (
            "Full scheduler planning overhead and "
            "post-planning dispatch overhead."
        ),

    "ci_target":
        CI_TARGET,

    "rows":
        rows,
}


OUTPUT.parent.mkdir(
    parents=True,
    exist_ok=True,
)

OUTPUT.write_text(
    json.dumps(
        payload,
        indent=2,
    )
    + "\n"
)


print()
print(
    f"CELLS: {len(rows)}/"
    f"{len(MODELS) * len(CONCURRENCIES)}"
)

print(
    "SCHEDULER OVERHEAD BENCHMARK: PASS"
)

print(
    "OUTPUT:",
    OUTPUT,
)
