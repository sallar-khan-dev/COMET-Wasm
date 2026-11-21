# WP3 Timing Precision

95% Student-t and bootstrap CIs; target <=2.5%.
Existing measurements only; no experiments repeated.

| Metric | N | Mean | Precision |
|---|---:|---:|---|
| native_kernel_ns_per_call | 20 | 7.7202 | PASS |
| wasmtime_call_ns_per_call | 20 | 33.5137 | PASS |
| wasmtime_native_call_ratio | 20 | 4.3409 | PASS |
| wasmtime_deploy_ms | 20 | 44.2724 | PASS |
| docker_deploy_ms | 20 | 419.1369 | NOT ACCEPTED |
| wasmtime_admit_ms | 20 | 1.5589 | NOT ACCEPTED |
| docker_admit_ms | 20 | 360.7357 | PASS |

These are scoped pilots, not complete WP3 supervisor acceptance.
