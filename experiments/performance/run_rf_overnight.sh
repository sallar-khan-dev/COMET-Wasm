#!/usr/bin/env bash
set -euo pipefail

cd ~/wasiMultitenant
source .venv/bin/activate

LEVELS="2 4 8 16 32 64 128 256"

echo "============================================================"
echo "RANDOM FOREST OVERNIGHT PERFORMANCE CAMPAIGN"
echo "Started: $(date)"
echo "============================================================"

echo
echo "===== WASMTIME START ====="

python experiments/performance/run_performance_full.py \
  --backend wasmtime \
  --model random_forest \
  --levels $LEVELS \
  2>&1 | tee results/logs/rf_wasmtime_performance_overnight.log

echo
echo "===== WASMTIME COMPLETE ====="
date

sleep 10

echo
echo "===== DOCKER START ====="

python experiments/performance/run_performance_full.py \
  --backend docker \
  --model random_forest \
  --levels $LEVELS \
  2>&1 | tee results/logs/rf_docker_performance_overnight.log

echo
echo "===== DOCKER COMPLETE ====="
date

echo
echo "============================================================"
echo "RANDOM FOREST PERFORMANCE CAMPAIGN COMPLETE"
echo "============================================================"
