# WP3 §6.2: Deployment cold start vs warm admission

CPU: 0; repetitions: 20; original model: LR.

| Measurement | Mean milliseconds |
|---|---:|
| wasmtime_deploy | 44.272 |
| docker_deploy | 419.137 |
| wasmtime_admit | 1.559 |
| docker_admit | 360.736 |

Warm Wasmtime internal instance creation is recorded separately in `trials.csv`.
This is a scope-limited WP3 timing experiment; do not combine deployment and admission measurements.
Readiness in all cases uses successful HTTP POST /infer and reference prediction.
**Scope limitation:** Cold path implementations are structurally different; warm harness HTTP is a small adapter, not COMET ingress. HTTP probe endpoints are matched by method and prediction, but no service-level latency comparison is claimed.
**Acceptance:** Requires comparison with full real serving configuration and supervisor WP1–WP3 stop/go validation.
