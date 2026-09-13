from pathlib import Path

from comet.model_registry.compatibility import (
    validate_compatibility,
)


def _profile_exists(
    model_id,
    backend,
    profile_db_path=
        "results/processed/comet/"
        "characterization_profiles.json",
):
    path = Path(profile_db_path)

    if not path.exists():
        return False

    import json

    data = json.loads(
        path.read_text()
    )

    profiles = data.get(
        "profiles",
        data if isinstance(data, list)
        else [],
    )

    for profile in profiles:
        if (
            profile.get("model")
            == model_id
            and
            profile.get("backend")
            == backend
        ):
            return True

    return False


def evaluate_readiness(
    spec,
    profile_db_path=
        "results/processed/comet/"
        "characterization_profiles.json",
):
    compatibility = (
        validate_compatibility(
            spec
        )
    )

    checks = []

    checks.append({
        "check": "compatibility",
        "passed":
            compatibility["compatible"],
    })

    validation_ok = (
        spec.validation_status
        == "validated"
    )

    checks.append({
        "check":
            "correctness_validation",
        "passed":
            validation_ok,
    })

    characterization_ok = (
        spec.characterization_status
        == "profiled"
    )

    checks.append({
        "check":
            "characterization",
        "passed":
            characterization_ok,
    })

    backend_profiles = {}

    for backend in (
        spec.supported_backends
    ):
        backend_profiles[
            backend
        ] = _profile_exists(
            spec.model_id,
            backend,
            profile_db_path,
        )

    profile_ok = (
        len(backend_profiles) > 0
        and
        all(
            backend_profiles.values()
        )
    )

    checks.append({
        "check":
            "empirical_profiles",
        "passed":
            profile_ok,
        "details":
            backend_profiles,
    })

    schedulable = all(
        bool(c["passed"])
        for c in checks
    )

    reasons = []

    if not compatibility[
        "compatible"
    ]:
        reasons.append(
            "model_not_compatible"
        )

    if not validation_ok:
        reasons.append(
            "correctness_not_validated"
        )

    if not characterization_ok:
        reasons.append(
            "characterization_incomplete"
        )

    if not profile_ok:
        reasons.append(
            "empirical_profile_missing"
        )

    return {
        "model_id":
            spec.model_id,

        "schedulable":
            schedulable,

        "checks":
            checks,

        "reasons":
            reasons,

        "compatibility":
            compatibility,

        "backend_profiles":
            backend_profiles,
    }
