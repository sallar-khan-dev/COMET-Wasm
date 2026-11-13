#!/usr/bin/env bash
set -euo pipefail
cd /home/sallar/wasiMultitenant
BASE=research_enhancement/wp4_compute_crossover
fail(){ echo "FAIL: $*" >&2; exit 1; }
[ -f "$BASE/run_mlp_64_wasmtime.py" ] || fail 'MLP reference runner missing'
[ -x research_enhancement/v2_parity/all_models_wasmtime_runner/target/release/comet-all-parity ] || fail 'parity runner missing'
[ -x serving/multitenant_server/target/release/comet_multitenant_server ] || fail 'multitenant server missing'
.venv/bin/python - <<'PY'
from pathlib import Path
import json, yaml
root=Path.cwd(); base=root/'research_enhancement/wp4_compute_crossover'; cfg=yaml.safe_load((root/'config/models.yaml').read_text())['models']; assert 'rf' in cfg,'rf model missing from registry'; assert cfg['rf']['features']==30
for n in (100,200,400):
    name=f'rf_trees_{n}'; m=root/f'models/wp4_scaled/random_forest/{name}/model_packed.json'; w=base/f'generated/{name}/wasm/target/wasm32-unknown-unknown/release/tenant_rf_real.wasm'; assert m.is_file() and w.is_file(),name
    assert json.loads(m.read_text())['n_estimators']==n
    for backend in ('wasmtime','docker'):
        report=base/f'validation/{name}_{backend}.json'; assert report.is_file(),f'missing {report}'; data=json.loads(report.read_text()); assert data['status']=='PASS' and data['matched']==569 and data['mismatches']==0, f'parity failed: {report}'
print('Model artifacts and 6 parity reports: PASS')
PY
for n in 100 200 400; do docker image inspect "comet-wp4-rf-$n:latest" >/dev/null || fail "Docker image missing: $n"; done
echo 'Docker images: PASS'
.venv/bin/python - <<'PY'
from pathlib import Path
p=Path('research_enhancement/wp4_compute_crossover/run_mlp_64_wasmtime.py'); s=p.read_text()
for x in ('WARMUP_REQUESTS = 1000','REQUESTS_PER_REPETITION = 5000','MIN_REPS = 20','MAX_REPS = 60','RELATIVE_CI_TARGET = 0.025','MODEL_CFG = get_model(MODEL_NAME)','mlp_width_64/wasm/target/wasm32-unknown-unknown/release/tenant_mlp_real.wasm','comet-wp4-mlp-64:latest','width_64_execution_time_full'):
    assert x in s, f'unexpected runner: {x}'
assert 'MODEL_NAME,' in s and 'start_wasmtime' in s and 'start_docker' in s
print('Existing experiment runner signature: PASS')
PY
echo 'WP4 RF PREFLIGHT PASSED'
