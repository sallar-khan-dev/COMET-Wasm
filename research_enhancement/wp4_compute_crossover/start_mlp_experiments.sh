#!/usr/bin/env bash
set -euo pipefail

ROOT=/home/sallar/wasiMultitenant
WP4="$ROOT/research_enhancement/wp4_compute_crossover"
ORIGINAL="$ROOT/experiments/execution_time/run_execution_time_full.py"

mkdir -p "$ROOT/results/raw/wp4_crossover"
mkdir -p "$ROOT/results/processed/wp4_crossover"
mkdir -p "$ROOT/results/logs/wp4_crossover"

for WIDTH in 64 128 256; do
  for BACKEND in wasmtime docker; do

    echo "=================================================="
    echo "WP4 MLP width=$WIDTH backend=$BACKEND"
    echo "=================================================="

    SCRIPT="$WP4/run_mlp_${WIDTH}_${BACKEND}.py"

    WP4_WIDTH="$WIDTH" WP4_BACKEND="$BACKEND" \
    WP4_ROOT="$ROOT" WP4_ORIGINAL="$ORIGINAL" \
    WP4_SCRIPT="$SCRIPT" \
    "$ROOT/.venv/bin/python" - <<'PY'
import os
from pathlib import Path

width = int(os.environ["WP4_WIDTH"])
backend = os.environ["WP4_BACKEND"]
root = Path(os.environ["WP4_ROOT"])
source = Path(os.environ["WP4_ORIGINAL"]).read_text()
target = Path(os.environ["WP4_SCRIPT"])

# Preserve original model identity for the existing server.
# The model registry still supplies its test dataset and features.
old = 'MODEL_CFG = get_model(MODEL_NAME)'
new = f'''MODEL_CFG = get_model(MODEL_NAME)
MODEL_CFG["wasm_artifact_abs"] = (
    ROOT / "research_enhancement/wp4_compute_crossover/generated"
    / "mlp_width_{width}/wasm/target/wasm32-unknown-unknown/release/tenant_mlp_real.wasm"
)
MODEL_CFG["docker_image"] = "comet-wp4-mlp-{width}:latest"
'''

if source.count(old) != 1:
    raise RuntimeError("Model configuration replacement failed")
source = source.replace(old, new)

# Isolate results from WP3 and other WP4 variants.
# Replace directory definitions, not experiment statistics.
import re

for name, folder in [
    ("RAW_DIR", "raw/wp4_crossover"),
    ("PROCESSED_DIR", "processed/wp4_crossover"),
]:
    pattern = rf'^{name}\s*=\s*.*$'
    matches = list(re.finditer(pattern, source, re.MULTILINE))
    if len(matches) != 1:
        raise RuntimeError(
            f"Expected one single-line {name} assignment; "
            f"found {len(matches)}. No experiment launched."
        )

    source = re.sub(
        pattern,
        f'{name} = ROOT / "results/{folder}"',
        source,
        count=1,
        flags=re.MULTILINE,
    )

# Give every scaled experiment a unique output filename.
source = source.replace(
    'f"{BACKEND}_{MODEL_NAME}_execution_time_full.csv"',
    f'f"{{BACKEND}}_{{MODEL_NAME}}_width_{width}_execution_time_full.csv"',
)
source = source.replace(
    'f"{BACKEND}_{MODEL_NAME}_execution_time_full_summary.json"',
    f'f"{{BACKEND}}_{{MODEL_NAME}}_width_{width}_execution_time_full_summary.json"',
)

target.write_text(source)
compile(source, str(target), "exec")
print(f"Prepared {target}")
PY

    LOG="$ROOT/results/logs/wp4_crossover/mlp_${WIDTH}_${BACKEND}.log"

    "$ROOT/.venv/bin/python" -u "$SCRIPT" \
      --backend "$BACKEND" \
      --model mlp \
      --fresh \
      > "$LOG" 2>&1

    echo "COMPLETED: width=$WIDTH backend=$BACKEND"
  done
done

echo "ALL SIX WP4 MLP EXPERIMENTS COMPLETED"
