import json
import random
from pathlib import Path


DEFAULT_SCENARIO_FILE = Path(
    "config/evaluation/"
    "scenarios.json"
)


def load_scenarios(
    path=DEFAULT_SCENARIO_FILE,
):
    data = json.loads(
        Path(path).read_text()
    )

    return data


def get_scenario(
    scenario_id,
    path=DEFAULT_SCENARIO_FILE,
):
    data = load_scenarios(
        path
    )

    for scenario in data[
        "scenarios"
    ]:
        if (
            scenario[
                "scenario_id"
            ]
            == scenario_id
        ):
            return scenario

    raise KeyError(
        f"Unknown scenario: "
        f"{scenario_id}"
    )


def generate_request_stream(
    scenario,
    seed=42,
):
    models = list(
        scenario["models"]
    )

    total = int(
        scenario["requests"]
    )

    if not models:
        raise ValueError(
            "Scenario requires "
            "at least one model"
        )

    rng = random.Random(
        seed
    )

    stream = [
        models[
            i % len(models)
        ]
        for i in range(total)
    ]

    rng.shuffle(
        stream
    )

    return [
        {
            "request_id": i,
            "model_id": model,
            "concurrency":
                int(
                    scenario[
                        "concurrency"
                    ]
                ),
            "tenants":
                int(
                    scenario[
                        "tenants"
                    ]
                ),
            "memory_budget_mib":
                scenario.get(
                    "memory_budget_mib"
                ),
            "sla_p95_ms":
                scenario.get(
                    "sla_p95_ms"
                ),
        }
        for i, model
        in enumerate(stream)
    ]
