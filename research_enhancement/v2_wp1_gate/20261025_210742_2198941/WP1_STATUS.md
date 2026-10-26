# WP1 supervisor gate — evidence-based status

This script is an audit, not a completed WP1 validation.

## Model inventory
- lr: Wasm present=True; Dockerfile present=True
- nb: Wasm present=True; Dockerfile present=True
- dt: Wasm present=True; Dockerfile present=True
- kmeans: Wasm present=True; Dockerfile present=True
- rf: Wasm present=True; Dockerfile present=True
- svm: Wasm present=True; Dockerfile present=True
- mlp: Wasm present=True; Dockerfile present=True

## Outstanding mandatory gates
- RF or SVM real varied-input golden-checked open-loop pilot: NOT VERIFIED BY THIS SCRIPT.
- Docker internal bridge path (rather than published loopback port): inspect docker_inspect.jsonl; NOT AUTOMATICALLY VALIDATED.
- Matched and verified worker counts, CPU affinity, context switches: review process_resources.csv and serving_code_hints.txt.
- Generator/gateway headroom ABOVE fastest real backend: NOT YET DEMONSTRATED by 600 RPS no-op.
- Sustained corrected latency-throughput curves: NOT YET VALIDATED.
- Full seven-model expansion only after WP1 acceptance gate.
- Statistical acceptance for full campaign: independent repetitions, 95% CI relative half-width <= 2.5%, appropriate tail-metric intervals; not satisfied by two-repetition smoke tests.

No source, containers, or services were modified by this script.
