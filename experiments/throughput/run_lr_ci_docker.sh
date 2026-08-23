#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
source .venv/bin/activate
python scripts/ci/servingMetricsPlusCI.py --name docker_real_lr_c32 --url http://localhost:8086/infer --body '{"f1":6.3,"f2":3.3,"f3":6.0,"f4":2.5}' --concurrency 32 --duration-s 5 --warmup 1 --repeat-min 20 --repeat-max 60 --rel-precision 0.025 --cooldown-s 1
