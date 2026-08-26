#!/usr/bin/env python3

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]

CONFIG = ROOT / "config/models.yaml"


def load_registry():

    data = yaml.safe_load(
        CONFIG.read_text()
    )

    if "models" not in data:
        raise RuntimeError(
            "config/models.yaml does not contain 'models:'"
        )

    return data["models"]


def get_model(name):

    models = load_registry()

    if name not in models:
        raise KeyError(
            f"Unknown model: {name}. "
            f"Available: {sorted(models)}"
        )

    m = dict(models[name])

    required = [
        "task",
        "dataset",
        "features",
        "model_path",
        "test_path",
        "workload_class",
        "wasm_artifact",
        "docker_image",
        "correctness_result",
    ]

    missing = [
        key
        for key in required
        if key not in m
    ]

    if missing:
        raise RuntimeError(
            f"{name}: missing registry fields: {missing}"
        )

    m["name"] = name

    m["model_path_abs"] = (
        ROOT / m["model_path"]
    )

    m["test_path_abs"] = (
        ROOT / m["test_path"]
    )

    m["wasm_artifact_abs"] = (
        ROOT / m["wasm_artifact"]
    )

    m["correctness_result_abs"] = (
        ROOT / m["correctness_result"]
    )

    return m


def supported_models():

    return sorted(
        load_registry().keys()
    )
