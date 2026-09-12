DEFAULT_WEIGHTS = {
    "latency_efficiency": 0.25,
    "throughput_efficiency": 0.20,
    "memory_efficiency": 0.20,
    "interference_resilience": 0.15,
    "startup_efficiency": 0.10,
    "compute_efficiency": 0.05,
    "density_efficiency": 0.05,
}


def validate_weights(weights):
    expected = set(DEFAULT_WEIGHTS)
    actual = set(weights)

    if actual != expected:
        raise ValueError(
            f"Weight dimensions mismatch. "
            f"Expected={sorted(expected)}, got={sorted(actual)}"
        )

    values = [float(weights[k]) for k in expected]

    if any(v < 0.0 for v in values):
        raise ValueError("Weights must be non-negative")

    total = sum(values)

    if abs(total - 1.0) > 1e-9:
        raise ValueError(
            f"Weights must sum to 1.0; got {total}"
        )

    return True
