#!/usr/bin/env python3
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path("/home/sallar/wasiMultitenant")
WP4 = ROOT / "research_enhancement/wp4_compute_crossover"
GENERATED = WP4 / "generated"

ORIGINAL_MODEL = "models/random_forest/breast_cancer/model_packed.json"

SOURCES = {
    "wasm": ROOT / "wasm/tenant_rf_real/generate_rf_lib.py",
    "docker": ROOT / "docker/rf_server/generate_main.py",
}

for trees in (100, 200, 400):
    variant = f"rf_trees_{trees}"

    model_path = (
        ROOT / "models/wp4_scaled/random_forest"
        / variant / "model_packed.json"
    )

    if not model_path.is_file():
        raise FileNotFoundError(model_path)

    for backend, original_generator in SOURCES.items():
        destination = GENERATED / variant / backend
        destination.mkdir(parents=True, exist_ok=True)

        # Preserve original project configuration.
        original_project = original_generator.parent

        for filename in ("Cargo.toml", "Cargo.lock", "Dockerfile"):
            source_file = original_project / filename
            if source_file.exists():
                shutil.copy2(source_file, destination / filename)

        # Copy original generator and change only the model path.
        generator = original_generator.read_text()

        if ORIGINAL_MODEL not in generator:
            raise RuntimeError(
                f"Original model path not found in {original_generator}"
            )

        scaled_model = (
            f"models/wp4_scaled/random_forest/"
            f"{variant}/model_packed.json"
        )

        generator = generator.replace(
            ORIGINAL_MODEL,
            scaled_model
        )

        # The copied generator is nested four directories below ROOT.
        generator = generator.replace(
            'Path(__file__).resolve().parents[2]',
            'Path("/home/sallar/wasiMultitenant")'
        )

        copied_generator = destination / original_generator.name
        copied_generator.write_text(generator)

        (destination / "src").mkdir(exist_ok=True)

        subprocess.run(
            [sys.executable, str(copied_generator)],
            cwd=destination,
            check=True
        )

        output = (
            destination / "src"
            / ("lib.rs" if backend == "wasm" else "main.rs")
        )

        if not output.is_file():
            raise RuntimeError(f"Missing generated source: {output}")

        print(f"READY: {variant}, {backend}")

print("ALL SCALED RF RUST SOURCES GENERATED")
