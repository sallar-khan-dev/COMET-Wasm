#!/usr/bin/env bash
set -euo pipefail

cd ~/wasiMultitenant
source .venv/bin/activate

mkdir -p results/logs/performance_completion

echo "================================================================"
echo "K-MEANS PERFORMANCE — WASMTIME"
echo "================================================================"

python experiments/performance/run_performance_full.py \
  --backend wasmtime \
  --model kmeans \
  --physical-units 20 \
  --levels 1 2 4 8 16 32 64 128 256 \
  --fresh \
  2>&1 | tee results/logs/performance_completion/wasmtime_kmeans_full.log

echo
echo "================================================================"
echo "K-MEANS PERFORMANCE — DOCKER"
echo "================================================================"

python experiments/performance/run_performance_full.py \
  --backend docker \
  --model kmeans \
  --physical-units 20 \
  --levels 1 2 4 8 16 32 64 128 256 \
  --fresh \
  2>&1 | tee results/logs/performance_completion/docker_kmeans_full.log

echo
echo "================================================================"
echo "K-MEANS FULL PERFORMANCE CAMPAIGN: COMPLETE"
echo "================================================================"
