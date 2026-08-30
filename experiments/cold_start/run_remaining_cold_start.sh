#!/usr/bin/env bash
set -euo pipefail

cd ~/wasiMultitenant
source .venv/bin/activate

mkdir -p results/logs/cold_start

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
    echo "COLD START — WASMTIME — ${model}"
    echo "================================================================"

    python experiments/cold_start/run_cold_start_full.py \
      --backend wasmtime \
      --model "$model" \
      --fresh \
      2>&1 | tee \
      "results/logs/cold_start/wasmtime_${model}.log"

    echo
    echo "================================================================"
    echo "COLD START — DOCKER — ${model}"
    echo "================================================================"

    python experiments/cold_start/run_cold_start_full.py \
      --backend docker \
      --model "$model" \
      --fresh \
      2>&1 | tee \
      "results/logs/cold_start/docker_${model}.log"
done

echo
echo "================================================================"
echo "ALL REMAINING COLD-START EXPERIMENTS COMPLETE"
echo "================================================================"
