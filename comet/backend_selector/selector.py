from comet.backend_selector.feasibility import check_feasibility
from comet.scoring.suitability import suitability_score


def select_backend(
    candidates,
    *,
    all_profiles,
    concurrency,
    weights,
    tenants,
    memory_budget_mib=None,
    sla_p95_ms=None,
    maximum_error_rate=0.0,
):
    evaluated = []

    for candidate in candidates:
        feasibility = check_feasibility(
            candidate["profile"],
            candidate["operating_point"],
            tenants=tenants,
            memory_budget_mib=memory_budget_mib,
            sla_p95_ms=sla_p95_ms,
            maximum_error_rate=maximum_error_rate,
        )

        score_data = suitability_score(
            candidate["profile"],
            candidate["operating_point"],
            all_profiles=all_profiles,
            concurrency=concurrency,
            tenants=tenants,
            weights=weights,
        )

        evaluated.append({
            **candidate,
            "feasibility": feasibility,
            **score_data,
        })

    feasible = [
        item
        for item in evaluated
        if item["feasibility"]["feasible"]
    ]

    winner = (
        max(
            feasible,
            key=lambda item: item["score"],
        )
        if feasible
        else None
    )

    return {
        "selected": winner,
        "evaluated": evaluated,
    }
