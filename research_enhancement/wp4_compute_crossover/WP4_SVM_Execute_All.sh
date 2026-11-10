#!/usr/bin/env bash
set -euo pipefail
cd /home/sallar/wasiMultitenant
BASE=research_enhancement/wp4_compute_crossover
export PYTHONUNBUFFERED=1

# Gate every experiment against already-generated correctness reports and artifacts.
.venv/bin/python - <<'PY'
from pathlib import Path
import json
root=Path.cwd(); base=root/'research_enhancement/wp4_compute_crossover'
for name in ('svm_c_0p03','svm_c_0p1','svm_c_0p3'):
    model=json.loads((root/f'models/wp4_scaled/svm/{name}/model.json').read_text())
    assert model['n_support_total'] > 91
    assert (base/f'generated/{name}/wasm/target/wasm32-unknown-unknown/release/tenant_svm_real.wasm').is_file()
    for backend in ('wasmtime','docker'):
        r=json.loads((base/f'validation/{name}_{backend}.json').read_text())
        assert r['status']=='PASS' and r['matched']==569 and r['mismatches']==0, (name,backend)
source=(base/'run_mlp_64_wasmtime.py').read_text()
for token in ('MODEL_CFG = get_model(MODEL_NAME)', 'mlp_width_64/wasm/target/wasm32-unknown-unknown/release/tenant_mlp_real.wasm', 'comet-wp4-mlp-64:latest', 'width_64_execution_time_full', 'MIN_REPS = 20', 'MAX_REPS = 60', 'RELATIVE_CI_TARGET = 0.025'):
    assert token in source, 'Existing runner changed: '+token
for name in ('svm_c_0p03','svm_c_0p1','svm_c_0p3'):
    for backend in ('wasmtime','docker'):
        text=source.replace('MODEL_CFG = get_model(MODEL_NAME)', 'MODEL_CFG = get_model("svm")\nMODEL_CFG["name"] = MODEL_NAME')
        text=text.replace('choices=supported_models(),', 'choices=supported_models() + ["svm_c_0p03", "svm_c_0p1", "svm_c_0p3"],')
        text=text.replace('mlp_width_64/wasm/target/wasm32-unknown-unknown/release/tenant_mlp_real.wasm', f'{name}/wasm/target/wasm32-unknown-unknown/release/tenant_svm_real.wasm')
        text=text.replace('comet-wp4-mlp-64:latest', f'comet-wp4-{name.replace("_", "-")}:latest')
        text=text.replace('width_64_execution_time_full', f'{name}_execution_time_full')
        output=base/f'run_{name}_{backend}.py'
        if output.exists():
            assert output.read_text() == text, f'Refusing overwrite of modified runner: {output}'
        else:
            output.write_text(text)
        compile(text,str(output),'exec')
        print('Prepared', output, flush=True)
print('SVM RUNNERS READY; ALL PARITY GATES PASSED', flush=True)
PY

mkdir -p results/logs
LOG=results/logs/wp4_svm_crossover_master.log
for name in svm_c_0p03 svm_c_0p1 svm_c_0p3; do
  for backend in wasmtime docker; do
    image="comet-wp4-${name//_/-}:latest"
    docker image inspect "$image" >/dev/null || { echo "Missing Docker image: $image"; exit 1; }
    echo "===== $name $backend $(date -Is) =====" | tee -a "$LOG"
    .venv/bin/python "$BASE/run_${name}_${backend}.py" --backend "$backend" --model "$name" 2>&1 | tee -a "$LOG"
  done
done
echo 'WP4 SVM PERFORMANCE RUNS COMPLETED' | tee -a "$LOG"
