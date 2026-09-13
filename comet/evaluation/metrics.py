from collections import Counter


def selected_candidate(
    scheduler_decision,
    backend,
):
    if backend is None:
        return None

    for candidate in scheduler_decision.get(
        "candidates",
        []
    ):
        if (
            candidate["backend"]
            == backend
        ):
            return candidate

    return None


def summarize_records(records):
    total = len(records)

    admitted = [
        r
        for r in records
        if r["admitted"]
    ]

    rejected = total - len(admitted)

    backend_counts = Counter(
        r["backend"]
        for r in admitted
    )

    def mean(field):
        values = [
            float(r[field])
            for r in admitted
            if r.get(field) is not None
        ]

        if not values:
            return None

        return sum(values) / len(values)

    return {
        "requests": total,

        "admitted":
            len(admitted),

        "rejected":
            rejected,

        "admission_rate":
            (
                len(admitted) / total
                if total
                else 0.0
            ),

        "rejection_rate":
            (
                rejected / total
                if total
                else 0.0
            ),

        "backend_distribution":
            dict(
                sorted(
                    backend_counts.items()
                )
            ),

        "predicted_mean_p95_ms":
            mean(
                "predicted_p95_ms"
            ),

        "predicted_mean_p99_ms":
            mean(
                "predicted_p99_ms"
            ),

        "predicted_mean_memory_mib":
            mean(
                "predicted_memory_mib"
            ),

        "predicted_mean_throughput_rps":
            mean(
                "predicted_throughput_rps"
            ),

        "ci_target_met_fraction":
            (
                sum(
                    bool(
                        r[
                            "ci_target_met"
                        ]
                    )
                    for r in admitted
                )
                / len(admitted)
                if admitted
                else None
            ),
    }
