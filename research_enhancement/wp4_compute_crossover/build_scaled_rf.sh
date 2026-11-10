#!/usr/bin/env bash
set -euo pipefail

ROOT=/home/sallar/wasiMultitenant
BASE="$ROOT/research_enhancement/wp4_compute_crossover/generated"

for TREES in 100 200 400; do
    VARIANT="rf_trees_${TREES}"

    echo "========== RF ${TREES}: WASMTIME =========="

    cd "$BASE/$VARIANT/wasm"
    cargo build --release --target wasm32-unknown-unknown

    echo "========== RF ${TREES}: DOCKER =========="

    cd "$BASE/$VARIANT/docker"
    docker build \
        -t "comet-wp4-rf-${TREES}:latest" \
        .

    echo "COMPILED: RF ${TREES}"
done

echo "ALL SCALED RF BUILDS COMPLETED"
