#!/usr/bin/env bash
set -euo pipefail

cd ~/wasiMultitenant
source .venv/bin/activate

mkdir -p results/logs

echo "===== LR WASMTIME START ====="
date

python experiments/performance/run_performance_full.py \
  --backend wasmtime \
  --model logistic_regression \
  --physical-units 20 \
  --levels 2 4 8 16 32 64 128 256 \
  2>&1 | tee results/logs/lr_wasmtime_performance.log

echo
echo "===== LR WASMTIME COMPLETE ====="
date

echo
echo "===== LR DOCKER START ====="
date

python experiments/performance/run_performance_full.py \
  --backend docker \
  --model logistic_regression \
  --physical-units 20 \
  --levels 2 4 8 16 32 64 128 256 \
  2>&1 | tee results/logs/lr_docker_performance.log

echo
echo "===== LR DOCKER COMPLETE ====="
date

echo
echo "===== LR FULL PERFORMANCE CAMPAIGN COMPLETE ====="
