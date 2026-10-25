#!/usr/bin/env bash
# COMET-Wasm WP1 safe consolidated checkpoint: does not kill/restart existing services.
set -Eeuo pipefail
ROOT="${COMET_ROOT:-$HOME/wasiMultitenant}"
cd "$ROOT"
OUT="$ROOT/research_enhancement/v2_wp1_combined/$(date -u +%Y%m%d_%H%M%S)_$$"
mkdir -p "$OUT"
exec > >(tee "$OUT/console.log") 2>&1
LOCK="$ROOT/research_enhancement/.comet_v2_wp1_combined.lock"
exec 9>"$LOCK"
flock -n 9 || { echo 'Another WP1 run is active; exiting.'; exit 2; }
OWN_PID=''
cleanup(){ if [[ -n "$OWN_PID" ]]; then kill "$OWN_PID" 2>/dev/null || :; wait "$OWN_PID" 2>/dev/null || :; fi; }
trap cleanup EXIT
printf 'RUN_DIR=%s\n' "$OUT"
printf 'UTC=%s\n' "$(date -u -Is)" > "$OUT/provenance.txt"
git rev-parse HEAD >> "$OUT/provenance.txt" 2>&1 || :
git status --short >> "$OUT/git_status.txt" 2>&1 || :
sha256sum research_enhancement/v2_loadgen/target/release/comet_v2_loadgen serving/common_ingress/target/release/comet_common_ingress 2>/dev/null > "$OUT/binary_hashes.txt" || :
# Read-only inventory; never run experiments/cross_model/smoke_model.py: it uses pkill -f and docker rm -f.
python3 - "$OUT" <<'PY'
import json,sys,pathlib
out=pathlib.Path(sys.argv[1]); root=pathlib.Path.cwd()
models=['lr','nb','dt','kmeans','rf','svm','mlp']
rows=[]
for model in models:
    wasms=list((root/'wasm').glob(f'tenant_{model}_real/target/wasm32-unknown-unknown/release/*.wasm'))
    rows.append(dict(model=model,wasm=[str(x.relative_to(root)) for x in wasms],docker_server=(root/f'docker/{model}_server/src/main.rs').exists()))
(out/'model_inventory.json').write_text(json.dumps(rows,indent=2)+'\n')
PY
{
  docker ps --format '{{.ID}} {{.Names}} {{.Image}} {{.Ports}}'
  docker inspect comet_v2_lr_functional --format 'network={{.HostConfig.NetworkMode}} cpuset={{.HostConfig.CpusetCpus}} nano_cpus={{.HostConfig.NanoCpus}}' 2>&1 || :
} > "$OUT/docker_status.txt" 2>&1
printf 'pid,comm,threads,cpus_allowed_list,pss_kib\n' > "$OUT/processes.csv"
for p in $(pgrep -u "$(id -u)" -f 'comet_native_lr|docker_lr_serve|comet_common_ingress' || :); do
 [[ -r "/proc/$p/status" ]] || continue
 comm=$(tr -d '\n' < "/proc/$p/comm" 2>/dev/null || :)
 threads=$(awk '/^Threads:/{print $2}' "/proc/$p/status")
 cpus=$(awk '/^Cpus_allowed_list:/{print $2}' "/proc/$p/status")
 pss=$(awk '/^Pss:/{print $2;exit}' "/proc/$p/smaps_rollup" 2>/dev/null || :)
 printf '%s,%s,%s,%s,%s\n' "$p" "$comm" "$threads" "$cpus" "$pss" >> "$OUT/processes.csv"
done
for port in 8085 8086 8200; do
 printf 'port=%s health=' "$port" >> "$OUT/ports.txt"
 curl --noproxy '*' -sS --max-time 2 -o /dev/null -w '%{http_code}\n' "http://127.0.0.1:$port/health" >> "$OUT/ports.txt" 2>/dev/null || echo unreachable >> "$OUT/ports.txt"
done
GEN="$ROOT/research_enhancement/v2_loadgen/target/release/comet_v2_loadgen"
ING="$ROOT/serving/common_ingress/target/release/comet_common_ingress"
TRACE="$ROOT/research_enhancement/v2_workloads/lr_iris_trace_135_seed42_t3.json"
GOLD="$ROOT/research_enhancement/v2_references/lr_iris_golden_v1.json"
ROUTES="$ROOT/serving/common_ingress/routes.v2.three_backend_lr.json"
WASM="$ROOT/wasm/tenant_lr_real/target/wasm32-unknown-unknown/release/tenant_lr_real.wasm"
if [[ ! -x "$GEN" || ! -x "$ING" || ! -f "$TRACE" || ! -f "$GOLD" || ! -f "$ROUTES" || ! -f "$WASM" ]]; then
 echo 'MISSING required LR pilot artifacts; see paths in script. No runs attempted.' | tee "$OUT/STATUS.txt"
 exit 3
fi
if curl --noproxy '*' -s --max-time 1 -o /dev/null http://127.0.0.1:8200/health; then
 echo 'Port 8200 already in use; will not replace or benchmark an unidentified ingress.' | tee "$OUT/STATUS.txt"
 exit 4
fi
# Launch only our own temporary ingress; never terminate other users or existing LR servers.
COMET_LR_WASM_PATH="$WASM" COMET_INGRESS_WORKERS=2 COMET_WASM_WORKERS=2 "$ING" "$ROUTES" > "$OUT/ingress.log" 2>&1 &
OWN_PID=$!
ready=0
for _ in $(seq 1 80); do
 if ! kill -0 "$OWN_PID" 2>/dev/null; then break; fi
 if [[ "$(curl --noproxy '*' -s --max-time 1 -o /dev/null -w '%{http_code}' http://127.0.0.1:8200/health || :)" == 200 ]]; then ready=1; break; fi
 sleep 0.25
done
if (( ! ready )); then echo 'Ingress readiness FAILED' | tee "$OUT/STATUS.txt"; exit 5; fi
printf 'phase,backend,rps,exit_code\n' > "$OUT/run_index.csv"
# Bounded diagnostic only: 135 requests per backend, NOT a sustained throughput/precision result.
for pair in 'wasmtime 20' 'docker 20' 'native 20' 'wasmtime 100' 'docker 100' 'native 100' 'wasmtime 300' 'docker 300' 'native 300'; do
 read -r backend rps <<< "$pair"
 prefix="$OUT/lr_${backend}_${rps}rps"
 echo "PILOT backend=$backend rps=$rps"
 rc=0
 "$GEN" "$TRACE" "$GOLD" http http://127.0.0.1:8200/infer "$backend" "$rps" 3000 128 "$prefix" > "$prefix.log" 2>&1 || rc=$?
 printf 'lr,%s,%s,%s\n' "$backend" "$rps" "$rc" >> "$OUT/run_index.csv"
done
# No-op is only valid as gateway/loadgen headroom, not model capacity.
for rps in 600 1200 2400; do
 echo "NOOP rps=$rps"
 rc=0
 "$GEN" noop http://127.0.0.1:8200/noop "$rps" 5 3000 256 "$OUT/noop_${rps}" > "$OUT/noop_${rps}.log" 2>&1 || rc=$?
 echo "noop $rps exit=$rc" >> "$OUT/noop_status.txt"
done
# Existing RF/SVM runner is unsafe on a shared host: it executes pkill -f and docker rm -f.
cat > "$OUT/NEXT_BLOCKERS.txt" <<'TXT'
WP1 gate NOT yet passed:
1. Existing cross-model smoke_model.py is not safe to run unmodified on shared HPC: pkill -f comet_multitenant_server and docker rm -f fixed names.
2. Common ingress wasm_adapter only supports LR; V2 loadgen validates only LR and iris_binary. RF/SVM need real adapter and trace/golden generalization.
3. Current Docker route is published localhost port, not a demonstrated internal Docker bridge path.
4. Native LR has many threads; fairness requires controlled replacement instance or measured thread-constrained design, not killing current process.
5. LR pilot 135 requests per run is not sustained, nor 95% CI +/-2.5% precision compliant.
6. No-op 5-second test checks limited headroom only; establish saturation with sustained model tests after corrections.
TXT
printf 'DONE: %s\n' "$OUT"
printf 'Return the tarball created by:\n tar -czf ~/comet_wp1_combined_results.tar.gz -C "%s" .\n' "$OUT"
