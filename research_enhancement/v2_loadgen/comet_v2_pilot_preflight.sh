#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$HOME/wasiMultitenant"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/research_enhancement/v2_pilot_preflight/$STAMP"
mkdir -p "$OUT"
exec > >(tee "$OUT/preflight.log") 2>&1
trap 'echo "ERROR at line $LINENO; inspect $OUT/preflight.log"' ERR
printf 'PILOT PREFLIGHT (read-only)\nOutput: %s\n' "$OUT"
[[ -d "$ROOT/.git" ]] || { echo 'Missing expected repository'; exit 1; }
cd "$ROOT"
printf '\n=== GIT / REPRODUCIBILITY ===\n'
git branch --show-current
git rev-parse HEAD
git status --short | head -100 || true
printf '\n=== ENVIRONMENT ===\n'
date -Is; hostname; uname -a
for x in cargo rustc python3 docker podman taskset numactl flock curl jq smem ps pidstat perf; do
  if command -v "$x" >/dev/null 2>&1; then printf '%-12s %s\n' "$x" "$(command -v "$x")"; else printf '%-12s MISSING\n' "$x"; fi
done
printf '\n=== CPU / MEMORY ===\n'
lscpu | grep -E '^(CPU\(s\)|Thread\(s\) per core|Core\(s\) per socket|Socket\(s\)|NUMA node\(s\)):' || true
free -h || true
printf '\n=== BUILT EXECUTABLES ===\n'
for f in serving/common_ingress/target/release/comet_common_ingress research_enhancement/v2_loadgen/target/release/comet_v2_loadgen; do
  if [[ -x "$f" ]]; then ls -lh "$f"; sha256sum "$f"; else echo "MISSING $f"; fi
done
printf '\n=== MODEL / SERVICE CANDIDATES (paths only) ===\n'
find "$ROOT" -maxdepth 7 -type f \( -iname '*.wasm' -o -iname '*.onnx' -o -iname '*.pkl' -o -iname '*.joblib' -o -iname '*docker*compose*.yml' -o -iname '*docker*compose*.yaml' -o -iname 'Dockerfile*' -o -iname '*golden*.json' -o -iname '*trace*.json' \) -not -path '*/target/*' -not -path '*/.git/*' -print | sort | head -180
printf '\n=== ROUTE CONFIGURATIONS ===\n'
find "$ROOT/serving/common_ingress" "$ROOT/research_enhancement" -maxdepth 3 -type f \( -iname '*routes*.json' -o -name 'routes.v2*.json' \) -print | sort | head -80
printf '\n=== BACKEND SOURCES / LAUNCHERS ===\n'
find "$ROOT/serving" "$ROOT/research_enhancement" -maxdepth 5 -type f \( -name 'main.py' -o -name 'server.py' -o -name '*server*.py' -o -name '*launch*.sh' -o -name 'Dockerfile*' -o -name 'docker-compose*.yml' -o -name 'compose.yaml' \) -print 2>/dev/null | sort | head -120 || true
printf '\n=== BACKEND PROCESS STATUS ===\n'
ps -eo pid,user,comm,args | grep -E 'comet_common_ingress|comet_v2_loadgen|host_lr_server|docker|podman' | grep -v grep | head -40 || true
printf '\n=== LOOPBACK PORT CHECK ===\n'
python3 - <<'PY'
import socket
for port in (8200, 8000, 8080, 8100, 8300, 18999):
    s=socket.socket(); s.settimeout(.3)
    result=s.connect_ex(('127.0.0.1',port))
    print(f'127.0.0.1:{port}: {"LISTENING" if result==0 else "not listening"}')
    s.close()
PY
printf '\n=== MEMORY MEASUREMENT SUPPORT ===\n'
if [[ -r /proc/self/smaps_rollup ]]; then grep -E '^(Pss|Rss):' /proc/self/smaps_rollup; else echo 'smaps_rollup unavailable'; fi
printf '\n=== REQUIRED REFERENCE FILES ===\n'
for f in research_enhancement/v2_references/lr_iris_golden_v1.json research_enhancement/v2_workloads/lr_iris_trace_135_seed42_t3.json; do
  if [[ -s "$f" ]]; then ls -lh "$f"; sha256sum "$f"; else echo "MISSING $f"; fi
done
printf '\n=== COMPLETED CALIBRATION ===\n'
find "$ROOT/research_enhancement/v2_foundation_runs" -maxdepth 2 -name 'calibration_index.json' -print 2>/dev/null | sort | tail -5 || true
printf '\nPREFLIGHT FINISHED. No services started and no experiments launched.\nReport: %s/preflight.log\n' "$OUT"
