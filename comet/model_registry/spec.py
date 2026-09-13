from dataclasses import dataclass, field
from typing import Any


SUPPORTED_TASKS = {
    "binary_classification",
    "multiclass_classification",
    "regression",
    "clustering_inference",
}

SUPPORTED_FORMATS = {
    "comet_json",
    "wasm",
    "onnx",
    "custom",
}

SUPPORTED_BACKENDS = {
    "wasmtime",
    "docker",
}


@dataclass
class ModelSpec:
    model_id: str
    display_name: str
    task: str
    workload_class: str
    features: int
    model_format: str

    model_path: str | None = None
    test_path: str | None = None
    wasm_artifact: str | None = None
    docker_image: str | None = None

    supported_backends: list[str] = field(
        default_factory=list
    )

    abi_version: str = "comet-abi-v1"
    input_type: str = "f32_vector"
    output_type: str = "class_id"

    source: str = "registered"
    validation_status: str = "unvalidated"
    characterization_status: str = "unprofiled"

    metadata: dict[str, Any] = field(
        default_factory=dict
    )

    def validate_structure(self):
        errors = []

        if not self.model_id:
            errors.append("model_id is required")

        if not self.display_name:
            errors.append("display_name is required")

        if self.task not in SUPPORTED_TASKS:
            errors.append(
                f"unsupported task: {self.task}"
            )

        if self.model_format not in SUPPORTED_FORMATS:
            errors.append(
                f"unsupported model format: "
                f"{self.model_format}"
            )

        if int(self.features) <= 0:
            errors.append(
                "features must be > 0"
            )

        unknown_backends = (
            set(self.supported_backends)
            - SUPPORTED_BACKENDS
        )

        if unknown_backends:
            errors.append(
                "unsupported backends: "
                + ", ".join(
                    sorted(unknown_backends)
                )
            )

        if not self.supported_backends:
            errors.append(
                "at least one backend is required"
            )

        return errors
