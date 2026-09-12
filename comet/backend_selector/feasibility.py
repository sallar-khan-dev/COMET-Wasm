def estimate_memory_mib(raw, tenants):
    """
    Piecewise-linear interpolation/extrapolation from the
    empirically measured 20/100/200-tenant PSS points.
    """
    tenants = int(tenants)

    if tenants < 1:
        raise ValueError("tenants must be >= 1")

    points = [
        (20, float(raw["pss_20_mib"])),
        (100, float(raw["pss_100_mib"])),
        (200, float(raw["pss_200_mib"])),
    ]

    if tenants <= 20:
        # Do not extrapolate below the first measured density.
        return points[0][1]

    if tenants <= 100:
        x0, y0 = points[0]
        x1, y1 = points[1]
    elif tenants <= 200:
        x0, y0 = points[1]
        x1, y1 = points[2]
    else:
        # Beyond the measured range, use the builder's
        # empirical growth slope and flag this later.
        return (
            points[2][1]
            + (tenants - 200)
            * float(raw["memory_growth_mib_per_tenant"])
        )

    fraction = (tenants - x0) / (x1 - x0)
    return y0 + fraction * (y1 - y0)


def check_feasibility(
    profile,
    operating_point,
    tenants,
    memory_budget_mib=None,
    sla_p95_ms=None,
    maximum_error_rate=0.0,
):
    raw = profile["raw"]

    predicted_memory = estimate_memory_mib(
        raw,
        tenants,
    )

    predicted_p95 = float(
        operating_point["p95_latency_ms"]["mean"]
    )

    predicted_error = float(
        operating_point["error_rate_mean"]
    )

    reasons = []

    if (
        memory_budget_mib is not None
        and predicted_memory > float(memory_budget_mib)
    ):
        reasons.append("memory_budget_exceeded")

    if (
        sla_p95_ms is not None
        and predicted_p95 > float(sla_p95_ms)
    ):
        reasons.append("p95_sla_violated")

    if predicted_error > float(maximum_error_rate):
        reasons.append("error_rate_exceeded")

    return {
        "feasible": not reasons,
        "reasons": reasons,
        "predicted_memory_mib": predicted_memory,
        "predicted_p95_ms": predicted_p95,
        "predicted_error_rate": predicted_error,
        "memory_extrapolated": int(tenants) > 200,
    }
