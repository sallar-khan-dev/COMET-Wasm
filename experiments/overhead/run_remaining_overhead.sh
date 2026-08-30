#!/usr/bin/env bash
set -euo pipefail

cd ~/wasiMultitenant
source .venv/bin/activate

mkdir -p results/logs/overhead

MODELS=(
  naive_bayes
  decision_tree
  kmeans
  random_forest
  svm
  mlp
)

for model in "${MODELS[@]}"
do
    echo
    echo "================================================================"
    echo "OVERHEAD DECOMPOSITION — WASMTIME — ${model}"
    echo "================================================================"

    python experiments/overhead/run_overhead_full.py \
      --backend wasmtime \
      --model "$model" \
      --fresh \
      2>&1 | tee \
      "results/logs/overhead/wasmtime_${model}.log"

    echo
    echo "================================================================"
    echo "OVERHEAD DECOMPOSITION — DOCKER — ${model}"
    echo "================================================================"

    python experiments/overhead/run_overhead_full.py \
      --backend docker \
      --model "$model" \
      --fresh \
      2>&1 | tee \
      "results/logs/overhead/docker_${model}.log"
done

echo
echo "================================================================"
echo "ALL REMAINING OVERHEAD EXPERIMENTS COMPLETE"
echo "================================================================"
