#!/usr/bin/env python3

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "research_enhancement/wp4_compute_crossover/generated"

GENERATORS = {
    "wasm": ROOT / "wasm/tenant_mlp_real/generate_mlp_lib.py",
    "docker": ROOT / "docker/mlp_server/generate_main.py",
}

for width in [64, 128, 256]:
    model = ROOT / f"models/wp4_scaled/mlp/mlp_width_{width}/model.json"
    data = json.loads(model.read_text())

    assert data["layer_sizes"] == [30, width, 1]

    for backend, generator in GENERATORS.items():
        target = OUT / f"mlp_width_{width}" / backend
        (target / "src").mkdir(parents=True, exist_ok=True)

        source = generator.read_text()

        old_model = (
            '(ROOT / "models/mlp/breast_cancer/model.json").read_text()'
        )

        new_model = f'Path({str(model)!r}).read_text()'

        assert old_model in source
        source = source.replace(old_model, new_model)

        assert "N_HIDDEN = 32" in source
        source = source.replace(
            "N_HIDDEN = 32",
            f"N_HIDDEN = {width}"
        )

        old_output = (
            'out = Path(__file__).parent / "src/lib.rs"'
            if backend == "wasm"
            else 'out = Path(__file__).parent / "src/main.rs"'
        )

        output_file = target / "src" / (
            "lib.rs" if backend == "wasm" else "main.rs"
        )

        assert old_output in source

        source = source.replace(
            old_output,
            f"out = Path({str(output_file)!r})"
        )

        generated_script = target / "generate.py"
        generated_script.write_text(source)

        subprocess.run(
            [sys.executable, str(generated_script)],
            check=True,
        )

        print(f"Generated {backend} width={width}: {output_file}")

print("\nAll six scaled MLP source files generated.")
