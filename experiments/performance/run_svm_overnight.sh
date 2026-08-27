#!/usr/bin/env bash
set -euo pipefail

cd ~/wasiMultitenant
source .venv/bin/activate

mkdir -p results/logs

echo "===== SVM WASMTIME START ====="
date

python experiments/performance/run_performance_full.py \
  --backend wasmtime \
  --model svm \
  --physical-units 20 \
  --levels 2 4 8 16 32 64 128 256 \
  2>&1 | tee results/logs/svm_wasmtime_performance.log

echo
echo "===== SVM WASMTIME COMPLETE ====="
date

echo
echo "===== SVM DOCKER START ====="
date

python experiments/performance/run_performance_full.py \
  --backend docker \
  --model svm \
  --physical-units 20 \
  --levels 2 4 8 16 32 64 128 256 \
  2>&1 | tee results/logs/svm_docker_performance.log

echo
echo "===== SVM DOCKER COMPLETE ====="
date

echo
echo "===== SVM FULL PERFORMANCE CAMPAIGN COMPLETE ====="
