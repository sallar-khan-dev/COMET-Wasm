from comet.profiles.normalizer import normalize
from comet.backend_selector.feasibility import estimate_memory_mib


def _bounds(values):
    values = [float(v) for v in values]

    if not values:
        raise ValueError("Cannot derive normalization bounds from empty population")

    return min(values), max(values)


def context_dimensions(
    profile,
    operating_point,
    *,
    all_profiles,
    concurrency,
    tenants,
):
    """
    Build context-aware desirability dimensions.

    Dynamic dimensions:
      - latency: empirical p95 at selected concurrency
      - throughput: empirical throughput at selected concurrency
      - memory: estimated PSS at requested tenant count

    Static empirical dimensions:
      - compute
      - startup
      - density
      - interference
    """

    key = str(int(concurrency))

    latency_population = []
    throughput_population = []
    memory_population = []

    for candidate in all_profiles:
        curve = candidate["performance_curve"]

        if key not in curve:
            raise KeyError(
                f"Missing concurrency {key} for "
                f"{candidate['model']}/{candidate['backend']}"
            )

        op = curve[key]

        latency_population.append(
            float(op["p95_latency_ms"]["mean"])
        )

        throughput_population.append(
            float(op["throughput_rps"]["mean"])
        )

        memory_population.append(
            estimate_memory_mib(
                candidate["raw"],
                tenants,
            )
        )

    lat_min, lat_max = _bounds(latency_population)
    thr_min, thr_max = _bounds(throughput_population)
    mem_min, mem_max = _bounds(memory_population)

    current_memory = estimate_memory_mib(
        profile["raw"],
        tenants,
    )

    dimensions = dict(profile["normalized"])

    dimensions["latency_efficiency"] = normalize(
        operating_point["p95_latency_ms"]["mean"],
        lat_min,
        lat_max,
        "low",
    )

    dimensions["throughput_efficiency"] = normalize(
        operating_point["throughput_rps"]["mean"],
        thr_min,
        thr_max,
        "high",
    )

    dimensions["memory_efficiency"] = normalize(
        current_memory,
        mem_min,
        mem_max,
        "low",
    )

    return dimensions


def suitability_score(
    profile,
    operating_point,
    *,
    all_profiles,
    concurrency,
    tenants,
    weights,
):
    dimensions = context_dimensions(
        profile,
        operating_point,
        all_profiles=all_profiles,
        concurrency=concurrency,
        tenants=tenants,
    )

    score = sum(
        float(weights[name])
        * float(dimensions[name])
        for name in weights
    )

    return {
        "score": float(score),
        "dimensions": dimensions,
    }
