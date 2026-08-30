#!/usr/bin/env bash
set -euo pipefail

cd ~/wasiMultitenant
source .venv/bin/activate

mkdir -p results/logs/execution_time

MODELS=(
  decision_tree
  kmeans
  random_forest
  svm
  mlp
)

for model in "${MODELS[@]}"
do
    echo
    echo "============================================================"
    echo "EXECUTION TIME — WASMTIME — ${model}"
    echo "============================================================"

    python experiments/execution_time/run_execution_time_full.py \
      --backend wasmtime \
      --model "$model" \
      --fresh \
      2>&1 | tee \
      "results/logs/execution_time/wasmtime_${model}.log"

    echo
    echo "============================================================"
    echo "EXECUTION TIME — DOCKER — ${model}"
    echo "============================================================"

    python experiments/execution_time/run_execution_time_full.py \
      --backend docker \
      --model "$model" \
      --fresh \
      2>&1 | tee \
      "results/logs/execution_time/docker_${model}.log"
done

echo
echo "============================================================"
echo "ALL REMAINING EXECUTION-TIME EXPERIMENTS COMPLETE"
echo "============================================================"
