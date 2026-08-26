#!/usr/bin/env bash
set -euo pipefail

cd ~/wasiMultitenant
source .venv/bin/activate

LEVELS="2 4 8 16 32 64 128 256"

echo "============================================================"
echo "DECISION TREE OVERNIGHT PERFORMANCE CAMPAIGN"
echo "Started: $(date)"
echo "============================================================"

echo
echo "===== WASMTIME START ====="
date

python experiments/performance/run_performance_full.py \
  --backend wasmtime \
  --model decision_tree \
  --levels $LEVELS \
  2>&1 | tee results/logs/dt_wasmtime_performance_overnight.log

echo
echo "===== WASMTIME COMPLETE ====="
date

sleep 10

echo
echo "===== DOCKER START ====="
date

python experiments/performance/run_performance_full.py \
  --backend docker \
  --model decision_tree \
  --levels $LEVELS \
  2>&1 | tee results/logs/dt_docker_performance_overnight.log

echo
echo "===== DOCKER COMPLETE ====="
date

echo
echo "============================================================"
echo "DECISION TREE OVERNIGHT CAMPAIGN COMPLETE"
echo "Finished: $(date)"
echo "============================================================"
