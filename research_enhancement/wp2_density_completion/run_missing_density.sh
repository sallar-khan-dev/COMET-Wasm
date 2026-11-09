#!/usr/bin/env bash
set -euo pipefail

cd /home/sallar/wasiMultitenant

PYTHON="$PWD/.venv/bin/python"
RUNNER="experiments/density/run_density_full.py"

mkdir -p research_enhancement/wp2_density_completion/logs

run_density() {
    local backend="$1"
    local model="$2"
    shift 2

    local log="research_enhancement/wp2_density_completion/logs/${backend}_${model}.log"

    echo "START: ${backend} ${model} levels=$*"

    "$PYTHON" "$RUNNER" \
        --backend "$backend" \
        --model "$model" \
        --levels "$@" \
        2>&1 | tee "$log"
}

for backend in wasmtime docker; do
    run_density "$backend" logistic_regression 5 10 50
    run_density "$backend" decision_tree 5 10 50
    run_density "$backend" kmeans 1 5 10 50
    run_density "$backend" random_forest 5 10 50
    run_density "$backend" svm 5 10 50
    run_density "$backend" mlp 5 10 50
done

echo "WP2 MISSING DENSITY CONDITIONS FINISHED"
