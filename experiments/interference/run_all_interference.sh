#!/usr/bin/env bash
set -euo pipefail

cd ~/wasiMultitenant
source .venv/bin/activate

mkdir -p results/logs/interference

PAIRS=(
  lr_lr
  lr_svm
  kmeans_rf
  dt_mlp
  svm_mlp
)

BACKENDS=(
  wasmtime
  docker
)

for pair in "${PAIRS[@]}"
do
    for backend in "${BACKENDS[@]}"
    do
        echo
        echo "================================================================"
        echo "INTERFERENCE — ${backend^^} — ${pair}"
        echo "================================================================"

        python experiments/interference/run_interference_full.py \
          --backend "$backend" \
          --pair "$pair" \
          --fresh \
          2>&1 | tee \
          "results/logs/interference/${backend}_${pair}.log"
    done
done

echo
echo "================================================================"
echo "ALL INTERFERENCE EXPERIMENTS COMPLETE"
echo "================================================================"
