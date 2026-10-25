#!/usr/bin/env bash
# Corrected LR golden-check pilot, one backend per run. Safe on shared HPC.
set -Eeuo pipefail
ROOT="${COMET_ROOT:-$HOME/wasiMultitenant}"
OUT="$ROOT/research_enhancement/v2_wp1_corrected/$(date -u +%Y%m%d_%H%M%S)_$$"
mkdir -p "$OUT"
exec > >(tee -a "$OUT/console.log") 2>&1
GEN="$ROOT/research_enhancement/v2_loadgen/target/release/comet_v2_loadgen"
ING="$ROOT/serving/common_ingress/target/release/comet_common_ingress"
TRACE="$ROOT/research_enhancement/v2_workloads/lr_iris_trace_135_seed42_t3.json"
GOLD="$ROOT/research_enhancement/v2_references/lr_iris_golden_v1.json"
WASM="$ROOT/wasm/tenant_lr_real/target/wasm32-unknown-unknown/release/tenant_lr_real.wasm"
OWN_PID=''
cleanup(){ if [[ -n "$OWN_PID" ]]; then kill "$OWN_PID" 2>/dev/null || :; wait "$OWN_PID" 2>/dev/null || :; OWN_PID=''; fi; }
trap cleanup EXIT
trap 'echo "FAIL at line $LINENO; results: $OUT"' ERR
for c in python3 curl flock sha256sum; do command -v "$c" >/dev/null || { echo "Missing command: $c"; exit 2; }; done
for f in "$GEN" "$ING" "$TRACE" "$GOLD" "$WASM"; do [[ -f "$f" ]] || { echo "Missing $f"; exit 2; }; done
exec 9>"$ROOT/research_enhancement/.comet_v2_wp1_corrected.lock"
flock -n 9 || { echo 'Another corrected pilot is active'; exit 2; }
python3 - <<'PY'
import socket
s=socket.socket()
try: s.bind(('127.0.0.1',8200))
except OSError: raise SystemExit('Port 8200 occupied; refusing to disturb an existing service')
finally: s.close()
PY
printf 'RUN_DIR=%s\n' "$OUT"
(cd "$ROOT" && { git rev-parse HEAD; git status --short; }) > "$OUT/git_state.txt"
sha256sum "$GEN" "$ING" "$TRACE" "$GOLD" "$WASM" > "$OUT/provenance_sha256.txt"
printf 'backend,rps,rep,exit_code,offered,success,failed,timed_out,dropped,p95_ms,gate\n' > "$OUT/validation.csv"
for backend in wasmtime docker native; do
  case "$backend" in
    wasmtime) url='' ;;
    docker) url='http://127.0.0.1:8085/infer' ;;
    native) url='http://127.0.0.1:8086/infer' ;;
  esac
  if [[ -n "$url" ]]; then
    code=$(curl --noproxy '*' -s --max-time 2 -o /dev/null -w '%{http_code}' "$url" || :)
    if [[ "$code" == 000 || -z "$code" ]]; then echo "SKIP $backend: backend not reachable"; continue; fi
  fi
  python3 - "$OUT/routes_${backend}.json" "$backend" "$url" <<'PY'
import json,sys
p,b,u=sys.argv[1:]
r={'backend':b,'model':'lr'}
if u:r['url']=u
with open(p,'w') as f:json.dump({str(i):dict(r) for i in range(3)},f,indent=2)
PY
  echo "START ingress: $backend"
  COMET_LR_WASM_PATH="$WASM" COMET_INGRESS_WORKERS=2 COMET_WASM_WORKERS=2 \
    "$ING" "$OUT/routes_${backend}.json" > "$OUT/ingress_${backend}.log" 2>&1 &
  OWN_PID=$!
  ready=0
  for i in $(seq 1 60); do
    if ! kill -0 "$OWN_PID" 2>/dev/null; then break; fi
    if [[ "$(curl --noproxy '*' -s --max-time 1 -o /dev/null -w '%{http_code}' http://127.0.0.1:8200/health || :)" == 200 ]]; then ready=1; break; fi
    sleep .2
  done
  if (( ! ready )); then echo "FAIL ingress $backend"; cleanup; exit 3; fi
  { echo 'timestamp,pid,threads,cpus_allowed_list,pss_kib';
    for pid in "$OWN_PID" $(pgrep -u "$(id -u)" -f 'comet_native_lr|docker_lr_serve' || :); do
      [[ -r "/proc/$pid/status" ]] || continue
      threads=$(awk '/^Threads:/{print $2}' "/proc/$pid/status")
      cpus=$(awk '/^Cpus_allowed_list:/{print $2}' "/proc/$pid/status")
      pss=$(awk '/^Pss:/{print $2;exit}' "/proc/$pid/smaps_rollup" 2>/dev/null || :)
      printf '%s,%s,%s,%s,%s\n' "$(date -u +%FT%TZ)" "$pid" "$threads" "$cpus" "$pss"
    done; } > "$OUT/resources_${backend}.csv"
  for rps in 20 100 300; do
    for rep in 1 2; do
      prefix="$OUT/lr_${backend}_${rps}rps_rep${rep}"
      echo "RUN $backend $rps RPS repetition $rep"
      rc=0
      COMET_LOADGEN_WORKERS=2 "$GEN" "$TRACE" "$GOLD" http http://127.0.0.1:8200/infer "$backend" "$rps" 3000 32 "$prefix" > "$prefix.stdout.log" 2>&1 || rc=$?
      python3 - "$prefix.summary.json" "$backend" "$rps" "$rep" "$rc" >> "$OUT/validation.csv" <<'PY'
import json,sys,pathlib
p,b,rps,rep,rc=sys.argv[1:]
try:
 s=json.loads(pathlib.Path(p).read_text())
 offered=s['offered_requests']; success=s['successful_requests']; failed=s['failed_requests']; timed=s['timed_out_requests']; dropped=s['dropped_requests']; p95=s.get('p95_latency_ms')
 passed=int(rc)==0 and offered==135 and success==135 and failed==timed==dropped==0
 print(f'{b},{rps},{rep},{rc},{offered},{success},{failed},{timed},{dropped},{p95},{"PASS" if passed else "FAIL"}')
except Exception as e:
 print(f'{b},{rps},{rep},{rc},,,,,,FAIL')
 print(f'Invalid summary {p}: {e}',file=sys.stderr)
PY
    done
  done
  cleanup
  sleep .3
done
python3 - "$OUT" <<'PY'
import csv,pathlib,sys,json
out=pathlib.Path(sys.argv[1]);rows=list(csv.DictReader((out/'validation.csv').open()))
expected={(b,str(r),str(rep)) for b in ('wasmtime','docker','native') for r in (20,100,300) for rep in (1,2)}
seen={(x['backend'],x['rps'],x['rep']) for x in rows}
passed=sum(x['gate']=='PASS' for x in rows)
all_pass=seen==expected and passed==18
result={'gate':'PASS' if all_pass else 'FAIL','expected_runs':18,'observed_runs':len(rows),'passed_runs':passed,'missing':sorted([list(x) for x in expected-seen]),'scope':'LR correctness smoke; NOT publication-grade or statistically converged','supervisor_wp1':'NOT COMPLETE: RF/SVM integration, thread parity, Docker internal bridge, sustained capacity still pending'}
(out/'GATE.json').write_text(json.dumps(result,indent=2)+'\n')
print('CORRECTNESS GATE:',result['gate'],f'{passed}/18 runs passed')
print('OUTPUT:',out)
print('PACKAGE: tar -czf ~/comet_v2_wp1_corrected.tar.gz -C "'+str(out)+'" .')
if not all_pass:sys.exit(5)
PY
