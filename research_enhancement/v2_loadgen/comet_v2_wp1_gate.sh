#!/usr/bin/env bash
# COMET-Wasm WP1 supervisor gate: read-only evidence capture + bounded optional existing heavy smoke runner.
set -Eeuo pipefail
ROOT="${COMET_ROOT:-$HOME/wasiMultitenant}"
OUT="$ROOT/research_enhancement/v2_wp1_gate/$(date +%Y%m%d_%H%M%S)_$$"
mkdir -p "$OUT"
exec > >(tee "$OUT/run.log") 2>&1
trap 'echo "ERROR at line $LINENO; see $OUT/run.log"' ERR
cd "$ROOT"
echo "WP1 evidence directory: $OUT"
for cmd in python3 git docker ss ps curl sha256sum find; do command -v "$cmd" >/dev/null || { echo "Missing tool: $cmd"; exit 2; }; done
{
  date -Is; hostname; uname -a; git rev-parse HEAD; git branch --show-current; git status --short
} > "$OUT/reproducibility.txt"
{
  lscpu; free -h; cat /proc/self/status | grep -E 'Cpus_allowed_list|Mems_allowed_list'
} > "$OUT/host_resources.txt"
echo '=== EXISTING INFERENCE EVIDENCE ==='
python3 - "$ROOT" "$OUT" <<'PY'
import sys,json,pathlib,csv,statistics
root,out=map(pathlib.Path,sys.argv[1:]); models=['lr','nb','dt','kmeans','rf','svm','mlp']
wasm=root/'wasm'; docker=root/'docker'
rows=[]
for m in models:
 p=wasm/f'tenant_{m}_real/target/wasm32-unknown-unknown/release/tenant_{m}_real.wasm'
 d=docker/f'{m}_server/Dockerfile'
 rows.append({'model':m,'wasm_module':str(p) if p.is_file() else '', 'dockerfile':str(d) if d.is_file() else '', 'wasm_present':p.is_file(),'dockerfile_present':d.is_file()})
with (out/'seven_model_inventory.csv').open('w',newline='') as f:
 w=csv.DictWriter(f,fieldnames=rows[0]);w.writeheader();w.writerows(rows)
for row in rows:print('MODEL',row['model'],'wasm=',row['wasm_present'],'dockerfile=',row['dockerfile_present'])
base=root/'research_enhancement/v2_inference_pilot'
runs=[]
if base.exists():
 for p in base.glob('*/**/*.summary.json'):
  try:
   x=json.loads(p.read_text());runs.append({'file':str(p),'offered':x.get('offered_requests'), 'successful':x.get('successful_requests'), 'failed':x.get('failed_requests'), 'dropped':x.get('dropped_requests'),'timeout':x.get('timed_out_requests'),'p95_ms':x.get('p95_latency_ms')})
  except (ValueError,OSError):pass
(out/'prior_lr_summaries.json').write_text(json.dumps(runs,indent=2))
print('Existing LR summary files:',len(runs))
PY
printf '\n=== DOCKER CONTAINERS / NETWORK ===\n'
docker ps --no-trunc > "$OUT/docker_ps.txt" 2>&1 || true
docker ps --format '{{.ID}} {{.Names}} {{.Image}} {{.Ports}}' | tee "$OUT/docker_list.txt" || true
# Inspect only running containers; no changes to them.
while read -r cid rest; do
 [[ -n "$cid" ]] || continue
 docker inspect "$cid" --format '{{json .}}' >> "$OUT/docker_inspect.jsonl" 2>/dev/null || true
done < "$OUT/docker_list.txt"
docker network ls > "$OUT/docker_networks.txt" 2>&1 || true
printf '\n=== THREADS / CPU AFFINITY / PROCESS STATUS ===\n'
ps -eo pid,ppid,user,nlwp,psr,comm,args --sort=pid > "$OUT/processes.txt"
python3 - "$OUT" <<'PY'
import pathlib,sys,csv
out=pathlib.Path(sys.argv[1]);patterns=('comet_common_ingress','comet_native_lr','docker_lr_server','docker_rf_server','docker_svm_server','comet_v2_loadgen')
rows=[]
for p in pathlib.Path('/proc').iterdir():
 if not p.name.isdigit():continue
 try:
  cmd=(p/'cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace')
  if not any(x in cmd for x in patterns):continue
  status={}
  for line in (p/'status').read_text().splitlines():
   if ':' in line:
    k,v=line.split(':',1);status[k]=v.strip()
  pss=''
  try:
   for line in (p/'smaps_rollup').read_text().splitlines():
    if line.startswith('Pss:'):pss=line.split()[1];break
  except (OSError,PermissionError):pass
  rows.append({'pid':p.name,'name':status.get('Name',''),'threads':status.get('Threads',''),'cpus_allowed':status.get('Cpus_allowed_list',''),'pss_kib':pss,'cmd':cmd[:350]})
 except (OSError,PermissionError):continue
with (out/'process_resources.csv').open('w',newline='') as f:
 w=csv.DictWriter(f,fieldnames=['pid','name','threads','cpus_allowed','pss_kib','cmd']);w.writeheader();w.writerows(rows)
for r in rows:print('PROCESS',r['pid'],r['name'],'threads',r['threads'],'cpu_set',r['cpus_allowed'],'pss_kib',r['pss_kib'])
PY
printf '\n=== MODEL GOLDEN / TRACES / EXISTING RUNNERS ===\n'
find research_enhancement experiments -maxdepth 5 -type f \( -iname '*golden*' -o -iname '*trace*' -o -iname '*smoke*.py' -o -iname '*smoke*.sh' \) 2>/dev/null | sort > "$OUT/reference_and_runner_candidates.txt"
cat "$OUT/reference_and_runner_candidates.txt" | head -100
printf '\n=== INGRESS / WORKER / BACKEND CODE HINTS ===\n'
grep -RnE 'COMET_INGRESS_WORKERS|COMET_WASM_WORKERS|worker_threads|tokio::main|8085|8086|docker' serving/common_ingress/src serving/native_lr_server/src docker/{lr,rf,svm}_server/src 2>/dev/null | head -160 > "$OUT/serving_code_hints.txt" || true
printf '\n=== HTTP CONNECTIVITY (GET ONLY; 405 IS NORMAL FOR POST /infer) ===\n'
for port in 8085 8086 8200; do
 code=$(curl --max-time 2 -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$port/infer" || true)
 echo "port=$port GET_/infer_HTTP=$code"
done | tee "$OUT/connectivity.txt"
# Do not run unverified RF/SVM commands. An explicitly provided existing smoke command can be used
# after user review, and is bounded by timeout. It must be an absolute executable path (no shell eval).
if [[ "${COMET_RUN_HEAVY_SMOKE:-0}" == 1 ]]; then
  if [[ -z "${COMET_HEAVY_SMOKE_EXEC:-}" || ! -x "${COMET_HEAVY_SMOKE_EXEC:-/nonexistent}" ]]; then
    echo 'Heavy smoke requested but COMET_HEAVY_SMOKE_EXEC is not an executable; refusing to guess interface.'
    exit 3
  fi
  echo "Running supplied existing heavy smoke executable for max 120 seconds: $COMET_HEAVY_SMOKE_EXEC"
  timeout 120 "$COMET_HEAVY_SMOKE_EXEC" > "$OUT/heavy_smoke.log" 2>&1
fi
python3 - "$OUT" <<'PY'
import json,pathlib,sys,csv
p=pathlib.Path(sys.argv[1]); models=list(csv.DictReader((p/'seven_model_inventory.csv').open()))
lines=['# WP1 supervisor gate — evidence-based status','', 'This script is an audit, not a completed WP1 validation.','', '## Model inventory']
for m in models:lines.append(f"- {m['model']}: Wasm present={m['wasm_present']}; Dockerfile present={m['dockerfile_present']}")
lines+=['','## Outstanding mandatory gates','- RF or SVM real varied-input golden-checked open-loop pilot: NOT VERIFIED BY THIS SCRIPT.','- Docker internal bridge path (rather than published loopback port): inspect docker_inspect.jsonl; NOT AUTOMATICALLY VALIDATED.','- Matched and verified worker counts, CPU affinity, context switches: review process_resources.csv and serving_code_hints.txt.','- Generator/gateway headroom ABOVE fastest real backend: NOT YET DEMONSTRATED by 600 RPS no-op.','- Sustained corrected latency-throughput curves: NOT YET VALIDATED.','- Full seven-model expansion only after WP1 acceptance gate.','- Statistical acceptance for full campaign: independent repetitions, 95% CI relative half-width <= 2.5%, appropriate tail-metric intervals; not satisfied by two-repetition smoke tests.','', 'No source, containers, or services were modified by this script.']
(p/'WP1_STATUS.md').write_text('\n'.join(lines)+'\n')
PY
sha256sum "$OUT"/* 2>/dev/null > "$OUT/file_checksums.sha256" || true
printf '\nCOMPLETE: %s\n' "$OUT"
echo 'Share WP1_STATUS.md, docker_list.txt, process_resources.csv, and reference_and_runner_candidates.txt.'
