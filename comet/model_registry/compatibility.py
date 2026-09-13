from pathlib import Path

from comet.adapters.abi import (
    REQUIRED_WASM_EXPORTS,
)
from comet.adapters.wasm_probe import (
    WasmProbeError,
    probe_wasm,
)


def validate_compatibility(spec):
    checks = []
    errors = []
    warnings = []

    def check(
        name,
        passed,
        detail,
        *,
        fatal=True,
    ):
        passed = bool(passed)

        checks.append({
            "check": name,
            "passed": passed,
            "detail": detail,
        })

        if not passed:
            if fatal:
                errors.append(detail)
            else:
                warnings.append(detail)

    # -------------------------------------------------
    # Generic model structure
    # -------------------------------------------------

    check(
        "feature_count",
        int(spec.features) > 0,
        (
            f"Feature count valid: "
            f"{spec.features}"
            if int(spec.features) > 0
            else "Feature count must be > 0"
        ),
    )

    # -------------------------------------------------
    # Model artifact
    # -------------------------------------------------

    if spec.model_path:
        model_path = Path(
            spec.model_path
        )

        check(
            "model_artifact",
            model_path.exists(),
            (
                f"Model artifact found: "
                f"{model_path}"
                if model_path.exists()
                else
                f"Model artifact missing: "
                f"{model_path}"
            ),
        )

    # -------------------------------------------------
    # Reference / test data
    # -------------------------------------------------

    if spec.test_path:
        test_path = Path(
            spec.test_path
        )

        check(
            "test_data",
            test_path.exists(),
            (
                f"Test data found: "
                f"{test_path}"
                if test_path.exists()
                else
                f"Test data missing: "
                f"{test_path}"
            ),
        )

    wasm_probe_result = None

    # -------------------------------------------------
    # Wasmtime compatibility
    # -------------------------------------------------

    if "wasmtime" in spec.supported_backends:

        if not spec.wasm_artifact:
            check(
                "wasm_artifact",
                False,
                "Wasmtime backend requires "
                "a Wasm artifact",
            )

        else:
            wasm_path = Path(
                spec.wasm_artifact
            )

            exists = (
                wasm_path.exists()
            )

            check(
                "wasm_artifact",
                exists,
                (
                    f"Wasm artifact found: "
                    f"{wasm_path}"
                    if exists
                    else
                    f"Wasm artifact missing: "
                    f"{wasm_path}"
                ),
            )

            if exists:
                try:
                    wasm_probe_result = (
                        probe_wasm(
                            wasm_path
                        )
                    )

                    abi_ok = bool(
                        wasm_probe_result[
                            "comet_abi_v1_compatible"
                        ]
                    )

                    missing = (
                        wasm_probe_result[
                            "missing_exports"
                        ]
                    )

                    check(
                        "comet_wasm_abi_v1",
                        abi_ok,
                        (
                            "COMET Wasm ABI v1 "
                            "validated"
                            if abi_ok
                            else
                            "COMET Wasm ABI v1 "
                            "validation failed; "
                            f"missing={missing}"
                        ),
                    )

                except WasmProbeError as exc:
                    check(
                        "comet_wasm_abi_v1",
                        False,
                        str(exc),
                    )

    # -------------------------------------------------
    # Docker compatibility declaration
    # -------------------------------------------------

    if "docker" in spec.supported_backends:

        check(
            "docker_image",
            bool(spec.docker_image),
            (
                "Docker image identifier "
                f"provided: {spec.docker_image}"
                if spec.docker_image
                else
                "Docker backend requires "
                "a Docker image identifier"
            ),
        )

    # -------------------------------------------------
    # ABI version
    # -------------------------------------------------

    if (
        spec.abi_version
        != "comet-abi-v1"
    ):
        warnings.append(
            "Non-v1 COMET ABI declared; "
            "an adapter may be required"
        )

    return {
        "compatible":
            len(errors) == 0,

        "model_id":
            spec.model_id,

        "checks":
            checks,

        "errors":
            errors,

        "warnings":
            warnings,

        "required_wasm_exports":
            sorted(
                REQUIRED_WASM_EXPORTS
            ),

        "wasm_probe":
            wasm_probe_result,
    }
