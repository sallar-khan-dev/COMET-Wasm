import csv
import hashlib
import json
import random
from pathlib import Path

from comet.evaluation.metrics import (
    selected_candidate,
    summarize_records,
)
from comet.evaluation.policies import (
    POLICIES,
    choose_policy_backend,
)
from comet.evaluation.scenarios import (
    generate_request_stream,
    load_scenarios,
)
from comet.evaluation.static_policy import (
    determine_best_static_backend,
)
from comet.scheduler.scheduler import (
    CometScheduler,
)


OUTPUT_DIR = Path(
    "results/processed/evaluation"
)

POLICY_ORDER = [
    "comet",
    "wasmtime_only",
    "docker_only",
    "random",
    "best_static",
]


def stream_hash(stream):
    payload = json.dumps(
        stream,
        sort_keys=True,
    ).encode()

    return hashlib.sha256(
        payload
    ).hexdigest()[:16]


def run_scenario(
    scheduler,
    scenario,
    policy,
    *,
    static_backend,
    seed,
):
    stream = generate_request_stream(
        scenario,
        seed=seed,
    )

    digest = stream_hash(
        stream
    )

    rng = random.Random(
        seed
    )

    decision_cache = {}

    records = []

    for request in stream:

        model = request[
            "model_id"
        ]

        cache_key = (
            model,
            request["concurrency"],
            request["tenants"],
            request[
                "memory_budget_mib"
            ],
            request["sla_p95_ms"],
        )

        if cache_key not in decision_cache:

            decision_cache[
                cache_key
            ] = scheduler.schedule(
                model=model,
                concurrency=request[
                    "concurrency"
                ],
                tenants=request[
                    "tenants"
                ],
                memory_budget_mib=request[
                    "memory_budget_mib"
                ],
                sla_p95_ms=request[
                    "sla_p95_ms"
                ],
            )

        decision = decision_cache[
            cache_key
        ]

        backend = (
            choose_policy_backend(
                policy,
                decision,
                static_backend=
                    static_backend,
                rng=rng,
            )
        )

        candidate = selected_candidate(
            decision,
            backend,
        )

        admitted = (
            backend is not None
            and candidate is not None
            and candidate[
                "feasible"
            ]
        )

        records.append({
            "request_id":
                request["request_id"],

            "model_id":
                model,

            "admitted":
                admitted,

            "backend":
                backend,

            "predicted_p95_ms":
                (
                    candidate[
                        "predicted_p95_ms"
                    ]
                    if admitted
                    else None
                ),

            "predicted_p99_ms":
                (
                    candidate[
                        "p99_latency_ms"
                    ]
                    if admitted
                    else None
                ),

            "predicted_memory_mib":
                (
                    candidate[
                        "predicted_memory_mib"
                    ]
                    if admitted
                    else None
                ),

            "predicted_throughput_rps":
                (
                    candidate[
                        "throughput_rps"
                    ]
                    if admitted
                    else None
                ),

            "ci_target_met":
                (
                    candidate[
                        "ci_target_met"
                    ]
                    if admitted
                    else None
                ),
        })

    summary = summarize_records(
        records
    )

    return {
        "scenario_id":
            scenario[
                "scenario_id"
            ],

        "policy":
            policy,

        "stream_hash":
            digest,

        "seed":
            seed,

        "concurrency":
            scenario[
                "concurrency"
            ],

        "tenants":
            scenario[
                "tenants"
            ],

        "memory_budget_mib":
            scenario.get(
                "memory_budget_mib"
            ),

        "sla_p95_ms":
            scenario.get(
                "sla_p95_ms"
            ),

        **summary,
    }


def main():
    OUTPUT_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    data = load_scenarios()

    seed = int(
        data.get(
            "seed",
            42,
        )
    )

    scheduler = CometScheduler()

    static = (
        determine_best_static_backend()
    )

    static_backend = static[
        "selected_backend"
    ]

    results = []

    print("=" * 120)
    print(
        "COMET-Wasm PROFILE-REPLAY "
        "SIMULATION SANITY EVALUATION"
    )
    print("=" * 120)

    print(
        "Best-static backend:",
        static_backend,
    )

    print()

    for scenario in data[
        "scenarios"
    ]:

        scenario_results = []

        for policy in POLICY_ORDER:

            assert policy in POLICIES

            result = run_scenario(
                scheduler,
                scenario,
                policy,
                static_backend=
                    static_backend,
                seed=seed,
            )

            results.append(
                result
            )

            scenario_results.append(
                result
            )

            print(
                f"{result['scenario_id']:22s} "
                f"{policy:15s} "
                f"admit="
                f"{result['admission_rate']:.3f} "
                f"backend="
                f"{result['backend_distribution']} "
                f"p95="
                f"{result['predicted_mean_p95_ms']} "
                f"mem="
                f"{result['predicted_mean_memory_mib']}"
            )

        hashes = {
            r["stream_hash"]
            for r in scenario_results
        }

        assert len(hashes) == 1, (
            "Policies did not receive "
            "identical request streams"
        )

        print(
            "  STREAM MATCH:",
            next(iter(hashes)),
        )
        print()

    output = {
        "schema_version":
            "comet-evaluation-simulation-v1",

        "evaluation_type":
            "profile_replay_sanity_only",

        "warning":
            (
                "This simulation reuses empirical "
                "characterization profiles used by "
                "the scheduler and must not be treated "
                "as final comparative evidence."
            ),

        "best_static":
            static,

        "results":
            results,
    }

    json_path = (
        OUTPUT_DIR
        / "simulation_sanity.json"
    )

    json_path.write_text(
        json.dumps(
            output,
            indent=2,
            sort_keys=False,
        )
        + "\n"
    )

    csv_path = (
        OUTPUT_DIR
        / "simulation_sanity.csv"
    )

    fields = [
        "scenario_id",
        "policy",
        "stream_hash",
        "seed",
        "concurrency",
        "tenants",
        "memory_budget_mib",
        "sla_p95_ms",
        "requests",
        "admitted",
        "rejected",
        "admission_rate",
        "rejection_rate",
        "backend_distribution",
        "predicted_mean_p95_ms",
        "predicted_mean_p99_ms",
        "predicted_mean_memory_mib",
        "predicted_mean_throughput_rps",
        "ci_target_met_fraction",
    ]

    with csv_path.open(
        "w",
        newline="",
    ) as f:

        writer = csv.DictWriter(
            f,
            fieldnames=fields,
        )

        writer.writeheader()

        for row in results:
            export = dict(row)

            export[
                "backend_distribution"
            ] = json.dumps(
                export[
                    "backend_distribution"
                ],
                sort_keys=True,
            )

            writer.writerow(
                export
            )

    assert len(results) == (
        len(
            data["scenarios"]
        )
        * len(POLICY_ORDER)
    )

    print("=" * 120)
    print(
        f"RESULT CELLS: "
        f"{len(results)}/"
        f"{len(data['scenarios']) * len(POLICY_ORDER)}"
    )
    print(
        "PROFILE-REPLAY SIMULATION: PASS"
    )
    print(
        "JSON:",
        json_path,
    )
    print(
        "CSV:",
        csv_path,
    )


if __name__ == "__main__":
    main()
