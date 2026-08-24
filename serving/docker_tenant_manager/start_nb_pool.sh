#!/usr/bin/env bash
set -euo pipefail

IMAGE="comet-nb-docker:v1"
PREFIX="comet-nb-tenant"
BASE_PORT=8200
COUNT="${1:-4}"

echo "Starting Docker tenant pool"
echo "Image: $IMAGE"
echo "Containers: $COUNT"

for ((i=0; i<COUNT; i++)); do
    NAME="${PREFIX}-${i}"
    PORT=$((BASE_PORT + i))

    docker rm -f "$NAME" >/dev/null 2>&1 || true

    docker run -d \
        --name "$NAME" \
        -p "${PORT}:8085" \
        "$IMAGE" >/dev/null

    echo "container=$i name=$NAME port=$PORT"
done

echo
echo "Docker tenant pool started."
