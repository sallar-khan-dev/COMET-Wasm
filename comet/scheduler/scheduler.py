import json
from copy import deepcopy
from pathlib import Path

from comet.backend_selector.selector import select_backend
from comet.scheduler.admission import validate_request
from comet.scheduler.placement import placement_plan
from comet.scoring.weights import (
    DEFAULT_WEIGHTS,
    validate_weights,
)


DEFAULT_PROFILE_DB = Path(
    "results/processed/comet/"
    "characterization_profiles.json"
)


class CometScheduler:
    def __init__(
        self,
        profile_db=DEFAULT_PROFILE_DB,
        weights=None,
    ):
        self.profile_db_path = Path(profile_db)

        if not self.profile_db_path.exists():
            raise FileNotFoundError(
                f"Profile database not found: "
                f"{self.profile_db_path}"
            )

        self.database = json.loads(
            self.profile_db_path.read_text()
        )

        self.profiles = self.database["profiles"]

        self.available_concurrency = sorted(
            int(x)
            for x in self.database[
                "performance_concurrency_levels"
            ]
        )

        self.models = sorted({
            profile["model"]
            for profile in self.profiles
        })

        self.backends = sorted({
            profile["backend"]
            for profile in self.profiles
        })

        self.weights = (
            deepcopy(DEFAULT_WEIGHTS)
            if weights is None
            else deepcopy(weights)
        )

        validate_weights(self.weights)

    def nearest_concurrency(self, requested):
        requested = int(requested)

        selected = min(
            self.available_concurrency,
            key=lambda value: (
                abs(value - requested),
                value,
            ),
        )

        return {
            "requested": requested,
            "selected": selected,
            "exact": requested == selected,
        }

    def profiles_for_model(self, model):
        matches = [
            profile
            for profile in self.profiles
            if profile["model"] == model
        ]

        if not matches:
            raise ValueError(
                f"Unknown model '{model}'. "
                f"Available models: {self.models}"
            )

        return matches

    def schedule(
        self,
        model,
        concurrency,
        tenants=1,
        memory_budget_mib=None,
        sla_p95_ms=None,
        maximum_error_rate=0.0,
        weights=None,
    ):
        validate_request(
            model,
            concurrency,
            tenants,
        )

        if model not in self.models:
            raise ValueError(
                f"Unknown model '{model}'. "
                f"Available models: {self.models}"
            )

        active_weights = (
            deepcopy(self.weights)
            if weights is None
            else deepcopy(weights)
        )

        validate_weights(active_weights)

        operating = self.nearest_concurrency(
            concurrency
        )

        selected_c = operating["selected"]

        candidates = []

        for profile in self.profiles_for_model(model):

            op = profile[
                "performance_curve"
            ][str(selected_c)]

            candidates.append({
                "backend": profile["backend"],
                "profile": profile,
                "operating_point": op,
            })

        selection = select_backend(
            candidates,
            all_profiles=self.profiles,
            concurrency=selected_c,
            weights=active_weights,
            tenants=tenants,
            memory_budget_mib=memory_budget_mib,
            sla_p95_ms=sla_p95_ms,
            maximum_error_rate=maximum_error_rate,
        )

        winner = selection["selected"]

        evaluated = []

        for item in selection["evaluated"]:

            evaluated.append({
                "backend":
                    item["backend"],

                "score":
                    item["score"],

                "feasible":
                    item[
                        "feasibility"
                    ]["feasible"],

                "rejection_reasons":
                    item[
                        "feasibility"
                    ]["reasons"],

                "predicted_p95_ms":
                    item[
                        "feasibility"
                    ]["predicted_p95_ms"],

                "predicted_memory_mib":
                    item[
                        "feasibility"
                    ]["predicted_memory_mib"],

                "predicted_error_rate":
                    item[
                        "feasibility"
                    ]["predicted_error_rate"],

                "memory_extrapolated":
                    item[
                        "feasibility"
                    ]["memory_extrapolated"],

                "throughput_rps":
                    item[
                        "operating_point"
                    ]["throughput_rps"]["mean"],

                "p99_latency_ms":
                    item[
                        "operating_point"
                    ]["p99_latency_ms"]["mean"],

                "ci_target_met":
                    item[
                        "operating_point"
                    ]["ci_target_met"],

                "dimensions":
                    item["dimensions"],
            })

        if winner is None:

            return {
                "admitted": False,
                "model": model,
                "requested_concurrency":
                    int(concurrency),
                "operating_concurrency":
                    selected_c,
                "exact_operating_point":
                    operating["exact"],
                "tenants":
                    int(tenants),
                "selected_backend": None,
                "placement": None,
                "constraints": {
                    "memory_budget_mib":
                        memory_budget_mib,
                    "sla_p95_ms":
                        sla_p95_ms,
                    "maximum_error_rate":
                        maximum_error_rate,
                },
                "weights":
                    active_weights,
                "candidates":
                    evaluated,
                "reason":
                    "no_feasible_backend",
            }

        backend = winner["backend"]

        return {
            "admitted": True,
            "model": model,
            "requested_concurrency":
                int(concurrency),
            "operating_concurrency":
                selected_c,
            "exact_operating_point":
                operating["exact"],
            "tenants":
                int(tenants),
            "selected_backend":
                backend,
            "selected_score":
                winner["score"],
            "placement":
                placement_plan(
                    backend,
                    tenants,
                ),
            "constraints": {
                "memory_budget_mib":
                    memory_budget_mib,
                "sla_p95_ms":
                    sla_p95_ms,
                "maximum_error_rate":
                    maximum_error_rate,
            },
            "weights":
                active_weights,
            "candidates":
                evaluated,
            "reason":
                "highest_score_among_feasible_backends",
        }


def main():
    scheduler = CometScheduler()

    result = scheduler.schedule(
        model="logistic_regression",
        concurrency=32,
        tenants=20,
    )

    print(
        json.dumps(
            result,
            indent=2,
            sort_keys=False,
        )
    )


if __name__ == "__main__":
    main()
