#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="${COMET_ROOT:-$HOME/wasiMultitenant}"
OUT_BASE="$ROOT/research_enhancement/v2_wp1_source_bundle"
STAMP="$(date -u +%Y%m%d_%H%M%S)_$$"
OUT="$OUT_BASE/$STAMP"
mkdir -p "$OUT/files" "$OUT/diagnostics"
exec > >(tee "$OUT/run.log") 2>&1
echo "COMET WP1 source bundle: $OUT"
if [[ ! -d "$ROOT/.git" ]]; then echo 'ERROR: repository not found' >&2; exit 1; fi
cd "$ROOT"
{
 date -u -Is; hostname; git rev-parse HEAD; git branch --show-current; git status --short;
} > "$OUT/diagnostics/reproducibility.txt"
# Copy only bounded text/source/config inputs; no datasets, binaries, secrets, or result directories.
paths=(
  experiments/cross_model/smoke_model.py
  research_enhancement/deterministic_trace.py
  research_enhancement/v2_workloads/generate_trace.py
  research_enhancement/v2_loadgen/Cargo.toml
  research_enhancement/v2_loadgen/src/main.rs
  research_enhancement/v2_loadgen/src/dispatcher.rs
  serving/common_ingress/Cargo.toml
  serving/common_ingress/src/main.rs
  serving/common_ingress/src/routes.rs
  serving/common_ingress/src/docker_adapter.rs
  serving/common_ingress/src/wasm_adapter.rs
  serving/common_ingress/routes.v2.json
  serving/common_ingress/routes.v2.mixed_lr.json
  serving/common_ingress/routes.v2.three_backend_lr.json
  serving/native_lr_server/src/main.rs
  docker/rf_server/Cargo.toml
  docker/rf_server/src/main.rs
  docker/svm_server/Cargo.toml
  docker/svm_server/src/main.rs
  wasm/tenant_rf_real/src/lib.rs
  wasm/tenant_svm_real/src/lib.rs
  wasm/tenant_rf_real/Cargo.toml
  wasm/tenant_svm_real/Cargo.toml
)
for p in "${paths[@]}"; do
 if [[ -f "$p" ]]; then
   mkdir -p "$OUT/files/$(dirname "$p")"
   cp -- "$p" "$OUT/files/$p"
   echo "FOUND $p"
 else echo "MISSING $p"; fi
done
# Additional manifests/runner filenames, not contents, to find alternate source locations.
find experiments research_enhancement serving docker wasm -maxdepth 5 -type f \
 \( -iname '*rf*' -o -iname '*svm*' -o -iname '*golden*' -o -iname '*cross_model*' \) \
 ! -path '*/target/*' ! -path '*/.git/*' ! -path '*/__pycache__/*' \
 | head -250 > "$OUT/diagnostics/rf_svm_file_candidates.txt" || true
# Relevant existing model registry and reference helpers, if small.
find experiments serving research_enhancement -maxdepth 5 -type f \
 \( -iname '*registry*.py' -o -iname '*reference*.py' -o -iname '*golden*.py' \) \
 ! -path '*/target/*' ! -path '*/__pycache__/*' \
 | head -40 > "$OUT/diagnostics/helper_candidates.txt" || true
while IFS= read -r p; do
 [[ -f "$p" ]] || continue
 [[ $(wc -c < "$p") -le 100000 ]] || continue
 mkdir -p "$OUT/files/$(dirname "$p")"; cp -- "$p" "$OUT/files/$p"
done < "$OUT/diagnostics/helper_candidates.txt"
# Docker bridge evidence, with only selected non-sensitive fields.
if command -v docker >/dev/null 2>&1; then
 docker inspect comet_v2_lr_functional --format 'name={{.Name}} network={{.HostConfig.NetworkMode}} ip={{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}} cpu_quota={{.HostConfig.NanoCpus}} cpuset={{.HostConfig.CpusetCpus}} memory={{.HostConfig.Memory}}' > "$OUT/diagnostics/docker_lr_network.txt" 2>&1 || true
fi
# Non-invasive runtime facts.
for port in 8085 8086 8200; do
 curl -sS -m 2 -o /dev/null -w "port=$port get_infer_http=%{http_code}\n" "http://127.0.0.1:$port/infer" || true
done > "$OUT/diagnostics/ports.txt"
ss -ltnp > "$OUT/diagnostics/listeners.txt" 2>&1 || true
for p in $(pgrep -u "$(id -u)" -f 'docker_lr_server|comet_native_lr_server|comet_common_ingress' || true); do
 [[ "$p" == "$$" || "$p" == "$PPID" ]] && continue
 if [[ -r "/proc/$p/status" ]]; then
   awk -v pid="$p" '/^(Name|Threads|Cpus_allowed_list|voluntary_ctxt_switches|nonvoluntary_ctxt_switches):/{print "pid="pid,$0}' "/proc/$p/status"
 fi
done > "$OUT/diagnostics/process_status.txt" 2>/dev/null || true
(
 cd "$OUT"
 find files diagnostics -type f -print0 | sort -z | xargs -0 -r sha256sum > SHA256SUMS
)
ARCHIVE="$OUT_BASE/comet_v2_wp1_sources_${STAMP}.tar.gz"
tar -czf "$ARCHIVE" -C "$OUT" .
echo "ARCHIVE: $ARCHIVE"
echo "SIZE: $(du -h "$ARCHIVE" | awk '{print $1}')"
echo 'No processes, containers, source files or git state were modified.'
