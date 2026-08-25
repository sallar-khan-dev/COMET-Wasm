#!/usr/bin/env bash
set -euo pipefail

COUNT="${1:-20}"
BASE_PORT=8300
IMAGE="comet-nb-docker:v1"

echo "Starting Docker performance pool"
echo "Containers: $COUNT"
echo "Base port: $BASE_PORT"

for ((i=0; i<COUNT; i++)); do
    NAME="comet-nb-perf-${i}"
    PORT=$((BASE_PORT + i))

    docker rm -f "$NAME" >/dev/null 2>&1 || true

    docker run -d \
        --rm \
        --name "$NAME" \
        -p "${PORT}:8085" \
        "$IMAGE" >/dev/null

    echo "container=$i name=$NAME port=$PORT"
done

echo
echo "Docker performance pool started."
