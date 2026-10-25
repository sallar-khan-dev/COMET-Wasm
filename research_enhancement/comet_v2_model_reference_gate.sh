#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="${COMET_ROOT:-$HOME/wasiMultitenant}"
cd "$ROOT"
STAMP="$(date +%Y%m%d_%H%M%S)_$$"
OUT="$ROOT/research_enhancement/v2_reference_gate/$STAMP"
mkdir -p "$OUT"
export ROOT OUT
python3 - <<'PY'
import ast,csv,hashlib,json,os,pathlib,subprocess,sys
root=pathlib.Path(os.environ['ROOT']); out=pathlib.Path(os.environ['OUT'])
models=['lr','nb','dt','kmeans','rf','svm','mlp']
try:
 import yaml
 registry=yaml.safe_load((root/'config/models.yaml').read_text())['models']
except Exception as e:
 print('BLOCKER registry:',e); sys.exit(2)
rows=[]
for model in models:
 r=registry.get(model)
 if not r:
  rows.append({'model':model,'blocker':'missing model registry entry'});continue
 item={'model':model,'features':r.get('features'),'task':r.get('task'),'dataset':r.get('dataset')}
 for field in ('model_path','test_path','wasm_artifact','docker_image','correctness_result'):
  val=r.get(field,''); item[field]=val
  if field!='docker_image':
   p=root/val if val else None
   item[field+'_exists']=bool(p and p.is_file())
   if p and p.is_file():
    item[field+'_sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
    if field=='test_path':
     try:
      with p.open(newline='') as f:
       reader=csv.DictReader(f);item['test_columns']=reader.fieldnames;item['test_preview']=list(__import__('itertools').islice(reader,2))
     except Exception as e:item['test_read_error']=str(e)
 golden=list((root/'research_enhancement/v2_references').glob(f'{model}_*.json'))
 item['golden_files']=[str(p.relative_to(root)) for p in golden]
 item['trace_files']=[str(p.relative_to(root)) for p in (root/'research_enhancement/v2_workloads').glob(f'{model}_*.json')]
 rows.append(item)
(out/'model_audit.json').write_text(json.dumps(rows,indent=2))
print('MODEL REFERENCE AUDIT')
for r in rows:
 print(r['model'], 'features=',r.get('features'),'wasm=',r.get('wasm_artifact_exists'),'golden=',len(r.get('golden_files',[])),'traces=',len(r.get('trace_files',[])))
PY
# Preserve original trace generator; adjust only the LR-specific prediction restriction.
GEN="$ROOT/research_enhancement/v2_workloads/generate_trace.py"
if [[ -f "$GEN" ]]; then
  cp "$GEN" "$OUT/generate_trace_before.py"
  python3 - "$GEN" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]);s=p.read_text()
old='if record["expected_prediction"] not in (0, 1):\n            raise ValueError("Invalid LR expected prediction")'
new='if isinstance(record["expected_prediction"], bool) or not isinstance(record["expected_prediction"], int):\n            raise ValueError("Expected prediction must be an integer model output")'
if old in s:
 p.write_text(s.replace(old,new));print('PATCHED: generic integer prediction validation')
elif new in s:print('ALREADY PATCHED: generic prediction validation')
else:print('NOTICE: trace generator structure differs; left unchanged')
PY
  python3 -m py_compile "$GEN"
fi
# Only create traces where independently generated golden references already exist.
python3 - <<'PY'
import json,os,pathlib,subprocess,sys
root=pathlib.Path(os.environ['ROOT']);out=pathlib.Path(os.environ['OUT']);generator=root/'research_enhancement/v2_workloads/generate_trace.py'
for model in ('lr','nb','dt','kmeans','rf','svm','mlp'):
 refs=list((root/'research_enhancement/v2_references').glob(f'{model}_*.json'))
 for ref in refs:
  try:
   obj=json.loads(ref.read_text())
   if obj.get('schema_version')!='comet-v2-golden-v1' or obj.get('model')!=model:continue
   target=out/f'{model}_{ref.stem}_trace_135_seed42_t3.json'
   subprocess.run([sys.executable,str(generator),'--golden',str(ref),'--output',str(target),'--count','135','--seed','42','--tenants','3'],check=True)
   print('TRACE CREATED',target)
  except Exception as e:print('TRACE BLOCKED',model,ref.name,str(e))
PY
ARCHIVE="$HOME/comet_v2_model_reference_gate.tar.gz"
tar -czf "$ARCHIVE" -C "$OUT" .
echo "AUDIT_DIR=$OUT"
echo "ARCHIVE=$ARCHIVE"
echo 'NOTE: Dataset labels are not assumed to be model predictions. Missing golden references remain explicit blockers.'
