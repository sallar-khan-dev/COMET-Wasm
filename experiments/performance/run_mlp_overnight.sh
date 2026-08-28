#!/usr/bin/env bash
set -euo pipefail

cd ~/wasiMultitenant
source .venv/bin/activate

mkdir -p results/logs

echo "===== MLP WASMTIME START ====="
date

python experiments/performance/run_performance_full.py \
  --backend wasmtime \
  --model mlp \
  --physical-units 20 \
  --levels 2 4 8 16 32 64 128 256 \
  2>&1 | tee results/logs/mlp_wasmtime_performance.log

echo
echo "===== MLP WASMTIME COMPLETE ====="
date

echo
echo "===== MLP DOCKER START ====="
date

python experiments/performance/run_performance_full.py \
  --backend docker \
  --model mlp \
  --physical-units 20 \
  --levels 2 4 8 16 32 64 128 256 \
  2>&1 | tee results/logs/mlp_docker_performance.log

echo
echo "===== MLP DOCKER COMPLETE ====="
date

echo
echo "===== MLP FULL PERFORMANCE CAMPAIGN COMPLETE ====="
