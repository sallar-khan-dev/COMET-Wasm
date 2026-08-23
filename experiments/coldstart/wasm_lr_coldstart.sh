#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
echo "Starting REAL Wasm LR cold-start test..."
START=$(date +%s%3N)
cd "$ROOT/serving/wasm_server/host_lr_server"
cargo run --release > /tmp/wasm_lr_server.log 2>&1 &
SERVER_PID=$!
sleep 2
curl -s -X POST http://localhost:8010/infer -H "Content-Type: application/json" -d '{"f1":6.3,"f2":3.3,"f3":6.0,"f4":2.5}' > /dev/null || true
END=$(date +%s%3N)
echo "REAL Wasm LR cold-start time: $((END - START)) ms"
kill "$SERVER_PID" > /dev/null 2>&1 || true
wait "$SERVER_PID" 2>/dev/null || true
