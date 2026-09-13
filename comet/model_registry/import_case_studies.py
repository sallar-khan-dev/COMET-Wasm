#!/usr/bin/env python3

from experiments.common.model_registry import (
    get_model,
    supported_models,
)

from comet.model_registry.registry import (
    CometModelRegistry,
)

from comet.model_registry.spec import ModelSpec


DISPLAY_NAMES = {
    "logistic_regression":
        "Logistic Regression",
    "naive_bayes":
        "Gaussian Naive Bayes",
    "decision_tree":
        "Decision Tree",
    "kmeans":
        "K-Means",
    "random_forest":
        "Random Forest",
    "svm":
        "RBF-SVM",
    "mlp":
        "Multi-Layer Perceptron",
}


def main():
    registry = CometModelRegistry()

    for model_id in supported_models():
        old = get_model(model_id)

        spec = ModelSpec(
            model_id=model_id,
            display_name=DISPLAY_NAMES.get(
                model_id,
                model_id,
            ),
            task=old["task"],
            workload_class=old[
                "workload_class"
            ],
            features=int(old["features"]),
            model_format="comet_json",

            model_path=str(
                old["model_path_abs"]
            ),
            test_path=str(
                old["test_path_abs"]
            ),
            wasm_artifact=str(
                old["wasm_artifact_abs"]
            ),
            docker_image=old[
                "docker_image"
            ],

            supported_backends=[
                "wasmtime",
                "docker",
            ],

            source="validated_case_study",
            validation_status="validated",
            characterization_status="profiled",

            metadata={
                "dataset":
                    old["dataset"],
                "correctness_result":
                    str(
                        old[
                            "correctness_result_abs"
                        ]
                    ),
            },
        )

        registry.register(
            spec,
            overwrite=True,
        )

        print(
            f"REGISTERED: "
            f"{model_id}"
        )

    print(
        "\nTOTAL:",
        len(registry.model_ids()),
    )


if __name__ == "__main__":
    main()
