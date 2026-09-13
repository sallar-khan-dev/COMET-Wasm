import random


POLICIES = {
    "comet",
    "wasmtime_only",
    "docker_only",
    "random",
    "best_static",
}


def validate_policy(name):
    if name not in POLICIES:
        raise ValueError(
            f"Unknown policy: {name}. "
            f"Supported: {sorted(POLICIES)}"
        )


def candidate_map(scheduler_decision):
    return {
        item["backend"]: item
        for item in scheduler_decision.get(
            "candidates",
            []
        )
    }


def choose_fixed_backend(
    backend,
    scheduler_decision,
):
    candidates = candidate_map(
        scheduler_decision
    )

    candidate = candidates.get(
        backend
    )

    if candidate is None:
        return None

    if not candidate.get(
        "feasible",
        False,
    ):
        return None

    return backend


def choose_random_backend(
    scheduler_decision,
    rng,
):
    candidates = candidate_map(
        scheduler_decision
    )

    feasible = sorted(
        backend
        for backend, info
        in candidates.items()
        if info.get(
            "feasible",
            False,
        )
    )

    if not feasible:
        return None

    return rng.choice(
        feasible
    )


def choose_policy_backend(
    policy,
    scheduler_decision,
    *,
    static_backend=None,
    rng=None,
):
    validate_policy(policy)

    if policy == "comet":
        if not scheduler_decision.get(
            "admitted",
            False,
        ):
            return None

        return scheduler_decision.get(
            "selected_backend"
        )

    if policy == "wasmtime_only":
        return choose_fixed_backend(
            "wasmtime",
            scheduler_decision,
        )

    if policy == "docker_only":
        return choose_fixed_backend(
            "docker",
            scheduler_decision,
        )

    if policy == "random":
        if rng is None:
            rng = random.Random(42)

        return choose_random_backend(
            scheduler_decision,
            rng,
        )

    if policy == "best_static":
        if static_backend is None:
            raise ValueError(
                "best_static requires "
                "static_backend"
            )

        return choose_fixed_backend(
            static_backend,
            scheduler_decision,
        )

    raise AssertionError(
        "unreachable"
    )
