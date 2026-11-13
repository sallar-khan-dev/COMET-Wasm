#!/usr/bin/env bash
set -euo pipefail

ROOT=/home/sallar/wasiMultitenant
BASE="$ROOT/research_enhancement/wp4_compute_crossover/generated"

for WIDTH in 64 128 256; do
    echo "========== BUILDING MLP WIDTH $WIDTH =========="

    WASM="$BASE/mlp_width_$WIDTH/wasm"
    DOCKER="$BASE/mlp_width_$WIDTH/docker"

    # Preserve generated source files.
    cp "$ROOT/wasm/tenant_mlp_real/Cargo.toml" "$WASM/"
    cp "$ROOT/docker/mlp_server/Cargo.toml" "$DOCKER/"
    cp "$ROOT/docker/mlp_server/Dockerfile" "$DOCKER/"

    echo "Building Wasm width $WIDTH"

    (
        cd "$WASM"
        cargo build --release --target wasm32-unknown-unknown
    )

    echo "Building Docker width $WIDTH"

    docker build \
        -t "comet-wp4-mlp-$WIDTH:latest" \
        "$DOCKER"

    echo "COMPLETED MLP WIDTH $WIDTH"
done

echo "ALL WP4 MLP BUILDS COMPLETED"
