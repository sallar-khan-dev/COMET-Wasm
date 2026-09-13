import json
from pathlib import Path


DEFAULT_PROFILE_DB = Path(
    "results/processed/comet/"
    "characterization_profiles.json"
)


def determine_best_static_backend(
    path=DEFAULT_PROFILE_DB,
):
    data = json.loads(
        Path(path).read_text()
    )

    profiles = data[
        "profiles"
    ]

    by_backend = {}

    for profile in profiles:

        backend = profile[
            "backend"
        ]

        normalized = profile[
            "normalized"
        ]

        score = sum(
            float(v)
            for v in
            normalized.values()
        ) / len(normalized)

        by_backend.setdefault(
            backend,
            []
        ).append(
            score
        )

    means = {
        backend:
            sum(values)
            / len(values)

        for backend, values
        in by_backend.items()
    }

    selected = max(
        means,
        key=means.get,
    )

    return {
        "selected_backend":
            selected,

        "mean_normalized_score":
            means,

        "method":
            "global_pre_evaluation_"
            "mean_normalized_profile_score",
    }
