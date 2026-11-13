#!/usr/bin/env bash
set -euo pipefail

cd /home/sallar/wasiMultitenant

echo "=== VERIFY NO ACTIVE BENCHMARKS ==="
if pgrep -af '[C]OMET_WP1_Resume|[c]omet_common_ingress|[c]argo build|[r]ustc'; then
    echo "SAFE STOP: An experiment or compiler may be running."
    exit 1
fi

echo "=== QUOTA BEFORE ==="
quota -s

# Legacy Rust build artifacts only.
# Source code, models, Docker images and research data are retained.
DIRS=(
  "serving/common_ingress/target/debug"
  "serving/multitenant_server/target/debug"
  "serving/worker_pool/target/debug"

  "serving/wasm_server/host_lr_server/target"
  "serving/wasm_server/host_nb_server/target"
  "serving/wasm_server/host_dt_server/target"
  "serving/wasm_server/host_kmeans_server/target"
  "serving/wasm_server/host_rf_server/target"
  "serving/wasm_server/host_svm_server/target"
  "serving/wasm_server/host_mlp_server/target"
)

echo "=== CLEANING LEGACY BUILD ARTIFACTS ==="

for dir in "${DIRS[@]}"; do
    if [ -d "$dir" ] && [ ! -L "$dir" ]; then
        echo "Removing build cache: $dir"
        du -sh "$dir"
        rm -rf -- "$dir"
    fi
done

echo
echo "=== QUOTA AFTER ==="
quota -s

echo
echo "=== ORIGINAL EXPERIMENT CHECKPOINT ==="
ls -lh \
  research_enhancement/automated_supervisor_workplan/wp1_five_model_formal/20261112_231004_2309146/state.json

echo
echo "=== ORIGINAL GATEWAY BINARY ==="
ls -lh \
  research_enhancement/automated_supervisor_workplan/wp1_five_model_formal/20261112_230658_2309146/cargo_target/release/comet_common_ingress

echo
echo "CLEANUP COMPLETE"
