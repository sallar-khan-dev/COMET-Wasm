#!/usr/bin/env bash
set -euo pipefail
echo "Starting REAL Docker LR cold-start test..."
docker rm -f docker_lr_coldstart >/dev/null 2>&1 || true
START=$(date +%s%3N)
docker run -d -p 8090:8085 --name docker_lr_coldstart docker-lr-server > /dev/null
sleep 2
curl -s -X POST http://localhost:8090/infer -H "Content-Type: application/json" -d '{"f1":6.3,"f2":3.3,"f3":6.0,"f4":2.5}' > /dev/null || true
END=$(date +%s%3N)
echo "REAL Docker LR cold-start time: $((END - START)) ms"
docker rm -f docker_lr_coldstart >/dev/null 2>&1 || true
