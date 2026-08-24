#!/usr/bin/env bash
set -euo pipefail

PREFIX="comet-nb-tenant"
COUNT="${1:-4}"

for ((i=0; i<COUNT; i++)); do
    docker rm -f "${PREFIX}-${i}" >/dev/null 2>&1 || true
done

echo "Docker tenant pool stopped."
