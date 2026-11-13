#!/usr/bin/env python3
import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / "research_enhancement/wp4_compute_crossover"
ORIGINAL = ROOT / "experiments/execution_time/run_execution_time_full.py"
RUNNER = BASE / "run_scaled_mlp.py"

source = ORIGINAL.read_text()

# Keep original methodology, but redirect model selection and output.
source = source.replace(
    'MODEL_CFG = get_model(MODEL_NAME)',
    '''MODEL_CFG = get_model("mlp")
if MODEL_NAME.startswith("mlp_width_"):
    width = int(MODEL_NAME.split("_")[-1])
    MODEL_CFG["wasm_artifact_abs"] = (
        ROOT / "research_enhancement/wp4_compute_crossover/generated"
        / f"mlp_width_{width}/wasm/target/wasm32-unknown-unknown/release/tenant_mlp_real.wasm"
    )
    MODEL_CFG["docker_image"] = f"comet-wp4-mlp-{width}:latest"
'''
)

if source == ORIGINAL.read_text():
    raise RuntimeError("Runner modification failed")

RUNNER.write_text(source)

print("Generated:", RUNNER)
print("WP4 runner prepared.")
