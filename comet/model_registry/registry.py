import json
from dataclasses import asdict
from pathlib import Path

from comet.model_registry.spec import ModelSpec


DEFAULT_REGISTRY = Path(
    "config/model_specs/registry.json"
)


class CometModelRegistry:
    def __init__(
        self,
        path=DEFAULT_REGISTRY,
    ):
        self.path = Path(path)
        self.path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        if self.path.exists():
            self.data = json.loads(
                self.path.read_text()
            )
        else:
            self.data = {
                "schema_version":
                    "comet-model-registry-v1",
                "models": {},
            }

    def save(self):
        self.path.write_text(
            json.dumps(
                self.data,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        )

    def register(
        self,
        spec: ModelSpec,
        overwrite=False,
    ):
        errors = spec.validate_structure()

        if errors:
            raise ValueError(
                "Invalid model specification: "
                + "; ".join(errors)
            )

        if (
            spec.model_id in self.data["models"]
            and not overwrite
        ):
            raise ValueError(
                f"Model already registered: "
                f"{spec.model_id}"
            )

        self.data["models"][
            spec.model_id
        ] = asdict(spec)

        self.save()

        return self.data["models"][
            spec.model_id
        ]

    def get(self, model_id):
        try:
            return self.data[
                "models"
            ][model_id]
        except KeyError:
            raise KeyError(
                f"Unknown COMET model: {model_id}"
            )

    def list_models(self):
        return [
            self.data["models"][key]
            for key in sorted(
                self.data["models"]
            )
        ]

    def model_ids(self):
        return sorted(
            self.data["models"]
        )
