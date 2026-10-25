#!/usr/bin/env bash
# Bounded, real LR inference smoke pilot. Does not modify source or Docker containers.
set -Eeuo pipefail
ROOT="${COMET_ROOT:-$HOME/wasiMultitenant}"
LOAD="$ROOT/research_enhancement/v2_loadgen"
ING="$ROOT/serving/common_ingress"
TRACE="$ROOT/research_enhancement/v2_workloads/lr_iris_trace_135_seed42_t3.json"
GOLDEN="$ROOT/research_enhancement/v2_references/lr_iris_golden_v1.json"
OUT="$ROOT/research_enhancement/v2_inference_pilot/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUT"
exec > >(tee -a "$OUT/pilot.log") 2>&1
ING_PID=''; MON_PID=''
cleanup(){
  if [[ -n "$MON_PID" ]]; then kill "$MON_PID" 2>/dev/null || :; wait "$MON_PID" 2>/dev/null || :; MON_PID=''; fi
  if [[ -n "$ING_PID" ]]; then kill "$ING_PID" 2>/dev/null || :; wait "$ING_PID" 2>/dev/null || :; ING_PID=''; fi
}
trap cleanup EXIT
trap 'echo "ERROR near line $LINENO; partial output: $OUT"' ERR
for f in "$TRACE" "$GOLDEN" "$LOAD/target/release/comet_v2_loadgen" "$ING/target/release/comet_common_ingress"; do
  [[ -f "$f" ]] || { echo "Missing required file: $f"; exit 1; }
done
for cmd in python3 curl sha256sum flock; do command -v "$cmd" >/dev/null || { echo "Missing $cmd"; exit 1; }; done
exec 9>"$ROOT/research_enhancement/.comet_v2_lr_pilot.lock"
flock -n 9 || { echo 'Another LR pilot owns this lock'; exit 1; }
python3 - <<'PY'
import socket
s=socket.socket()
try:s.bind(('127.0.0.1',8200))
except OSError:raise SystemExit('Port 8200 already occupied: refusing to disturb existing ingress')
finally:s.close()
PY
printf 'Output: %s\n' "$OUT"
(cd "$ROOT" && { git rev-parse HEAD; git status --short; }) > "$OUT/git_state.txt"
sha256sum "$TRACE" "$GOLDEN" "$LOAD/target/release/comet_v2_loadgen" "$ING/target/release/comet_common_ingress" > "$OUT/checksums.txt"
{ date -Is; hostname; lscpu | grep -E 'CPU\(s\):|NUMA node\(s\):' || :; } > "$OUT/host.txt"
# Existing Docker LR service is not ours. We only connect to it; never restart or stop it.
BACKENDS=(wasmtime docker)
if [[ -z "${COMET_LR_WASM_PATH:-}" || ! -f "${COMET_LR_WASM_PATH:-/nonexistent}" ]]; then
  echo 'Wasmtime LR module not supplied via COMET_LR_WASM_PATH; skipping Wasmtime (not fabricating results).'
  BACKENDS=(docker)
fi
# Each run uses the same 135-request 3-tenant golden-checked trace.
# 20/100/300 RPS are short correctness/performance smoke points, not a saturation study.
for backend in "${BACKENDS[@]}"; do
  if [[ "$backend" == docker ]]; then
    if ! curl -sS --max-time 2 -o /dev/null http://127.0.0.1:8085/infer; then
      echo 'Docker LR port 8085 unreachable; skipping Docker backend.'
      continue
    fi
  fi
  python3 - "$OUT/routes_${backend}.json" "$backend" <<'PY'
import json,sys
p,backend=sys.argv[1:]
route={'backend':backend,'model':'lr'}
if backend=='docker':route['url']='http://127.0.0.1:8085/infer'
with open(p,'w') as f:json.dump({str(i):dict(route) for i in range(3)},f,indent=2)
PY
  echo "===== BACKEND: $backend ====="
  COMET_INGRESS_WORKERS=2 COMET_WASM_WORKERS=2 \
    "$ING/target/release/comet_common_ingress" "$OUT/routes_${backend}.json" > "$OUT/ingress_${backend}.log" 2>&1 &
  ING_PID=$!
  READY=0
  for _ in $(seq 1 40); do
    if ! kill -0 "$ING_PID" 2>/dev/null; then break; fi
    if curl -fsS --max-time 1 http://127.0.0.1:8200/health >/dev/null 2>&1; then READY=1; break; fi
    sleep .25
  done
  if [[ "$READY" != 1 ]]; then
    echo "Ingress failed for $backend; see $OUT/ingress_${backend}.log"
    cleanup
    continue
  fi
  # Sample process PSS from smaps_rollup and CPU ticks from /proc/PID/stat.
  ( echo "timestamp_ns,pid,pss_kib,rss_kib,utime_ticks,stime_ticks"
    while kill -0 "$ING_PID" 2>/dev/null; do
      python3 - "$ING_PID" <<'PY'
import sys,time,pathlib
pid=sys.argv[1]
try:
 p=pathlib.Path('/proc')/pid
 vals={}
 for line in (p/'smaps_rollup').read_text().splitlines():
  if line.startswith(('Pss:','Rss:')):
   key,value,*_=line.split();vals[key.rstrip(':')]=int(value)
 stat=(p/'stat').read_text().split(') ',1)[1].split()
 print(f"{time.time_ns()},{pid},{vals.get('Pss','')},{vals.get('Rss','')},{stat[11]},{stat[12]}",flush=True)
except (OSError,ValueError,IndexError):pass
PY
      sleep .1
    done ) > "$OUT/ingress_${backend}_pss_cpu.csv" &
  MON_PID=$!
  for rps in 20 100 300; do
    for rep in 1 2; do
      prefix="$OUT/${backend}_${rps}rps_rep${rep}"
      echo "Running real LR: backend=$backend offered_rps=$rps repetition=$rep"
      if ! COMET_LOADGEN_WORKERS=2 "$LOAD/target/release/comet_v2_loadgen" \
        "$TRACE" "$GOLDEN" http http://127.0.0.1:8200/infer "$backend" "$rps" 3000 32 "$prefix" \
        > "${prefix}.stdout.log" 2>&1; then
        echo "FAIL: $backend $rps rep$rep; see ${prefix}.stdout.log"
      fi
    done
  done
  cleanup
  sleep .3
done
python3 - "$OUT" <<'PY'
import json,pathlib,sys,csv
out=pathlib.Path(sys.argv[1]); rows=[]
for p in sorted(out.glob('*.summary.json')):
 try:s=json.loads(p.read_text())
 except Exception as e:print('BAD SUMMARY',p,e);continue
 print('SUMMARY',p.name,json.dumps(s,sort_keys=True)[:1500]);rows.append({'file':p.name,'summary':s})
(out/'pilot_index.json').write_text(json.dumps(rows,indent=2))
print('SUMMARY FILES:',len(rows),'(up to 12 if both backends available)')
if not rows:raise SystemExit('NO SUCCESSFUL PILOT RUNS. Check ingress and stdout logs.')
PY
printf '\nPILOT FINISHED: %s\n' "$OUT"
printf 'These are bounded LR smoke measurements, NOT a validated COMET scheduling campaign.\n'
