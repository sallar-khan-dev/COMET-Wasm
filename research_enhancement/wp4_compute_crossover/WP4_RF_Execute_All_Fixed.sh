#!/usr/bin/env bash
set -euo pipefail
cd /home/sallar/wasiMultitenant
BASE=research_enhancement/wp4_compute_crossover
bash "$BASE/WP4_RF_Preflight_Fixed.sh"
python - <<'PY'
from pathlib import Path
root=Path.cwd(); base=root/'research_enhancement/wp4_compute_crossover'
source=(base/'run_mlp_64_wasmtime.py').read_text()
old='MODEL_CFG = get_model(MODEL_NAME)'
assert source.count(old)==1
for n in (100,200,400):
    for backend in ('wasmtime','docker'):
        text=source
        text=text.replace(old, 'MODEL_CFG = get_model("mlp")\nMODEL_CFG["name"] = MODEL_NAME\nrf_test = ROOT / "models/random_forest/breast_cancer/test_samples.csv"\nif rf_test.is_file():\n    MODEL_CFG["test_path_abs"] = rf_test')
        text=text.replace('mlp_width_64/wasm/target/wasm32-unknown-unknown/release/tenant_mlp_real.wasm',f'rf_trees_{n}/wasm/target/wasm32-unknown-unknown/release/tenant_rf_real.wasm')
        text=text.replace('comet-wp4-mlp-64:latest',f'comet-wp4-rf-{n}:latest')
        text=text.replace('width_64_execution_time_full',f'trees_{n}_execution_time_full')
        # Original server accepts model name as an opaque string, and validates feature count via registry-backed test samples.
        text=text.replace('choices=supported_models(),','choices=supported_models() + ["rf_trees_100", "rf_trees_200", "rf_trees_400"],')
        path=base/f'run_rf_{n}_{backend}.py'
        if path.exists():
            assert path.read_text()==text, f'Refusing to overwrite existing modified script: {path}'
        else: path.write_text(text)
        compile(text,str(path),'exec')
        print('Prepared',path)
PY
mkdir -p results/logs
LOG=results/logs/wp4_rf_crossover_master.log
for n in 100 200 400; do
  for backend in wasmtime docker; do
    echo "===== RF $n $backend $(date -Is) =====" | tee -a "$LOG"
    PYTHONUNBUFFERED=1 .venv/bin/python "$BASE/run_rf_${n}_${backend}.py" --backend "$backend" --model "rf_trees_${n}" 2>&1 | tee -a "$LOG"
  done
done
echo 'WP4 RF PERFORMANCE RUNS COMPLETED' | tee -a "$LOG"
