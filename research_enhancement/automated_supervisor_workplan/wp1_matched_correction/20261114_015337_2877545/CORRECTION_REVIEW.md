# Supervisor WP1 matched full-scale serving correction

- Runner status: **DATA COLLECTED; ACCEPTANCE REVIEW REQUIRED**
- Repetitions collected: **481** (adaptive range 400–1200)
- Completely successful repetitions: **481 / 481**

| Model/backend | Repetitions | Full-success | Successful no-op rates (RPS) |
|---|---:|---:|---|
| lr_wasmtime | 144 | 144 | 4800 |
| lr_docker | 105 | 105 | 4800 |
| rf_wasmtime | 126 | 126 | 4800 |
| rf_docker | 106 | 106 | 4800 |

## Formal independent-run statistical precision
| Model/backend/rate | Runs | 95% CI precision | Correctness | Stopping |
|---|---:|---|---|---|
| lr_docker_rps100 | 20 | True | True | precision_met_after_minimum |
| lr_docker_rps1200 | 20 | True | True | precision_met_after_minimum |
| lr_docker_rps2400 | 20 | True | True | precision_met_after_minimum |
| lr_docker_rps300 | 20 | True | True | precision_met_after_minimum |
| lr_docker_rps600 | 25 | True | True | precision_met_after_minimum |
| lr_wasmtime_rps100 | 48 | True | True | precision_met_after_minimum |
| lr_wasmtime_rps1200 | 20 | True | True | precision_met_after_minimum |
| lr_wasmtime_rps2400 | 20 | True | True | precision_met_after_minimum |
| lr_wasmtime_rps300 | 25 | True | True | precision_met_after_minimum |
| lr_wasmtime_rps600 | 31 | True | True | precision_met_after_minimum |
| rf_docker_rps100 | 20 | True | True | precision_met_after_minimum |
| rf_docker_rps1200 | 20 | True | True | precision_met_after_minimum |
| rf_docker_rps2400 | 23 | True | True | precision_met_after_minimum |
| rf_docker_rps300 | 20 | True | True | precision_met_after_minimum |
| rf_docker_rps600 | 23 | True | True | precision_met_after_minimum |
| rf_wasmtime_rps100 | 32 | True | True | precision_met_after_minimum |
| rf_wasmtime_rps1200 | 20 | True | True | precision_met_after_minimum |
| rf_wasmtime_rps2400 | 20 | True | True | precision_met_after_minimum |
| rf_wasmtime_rps300 | 20 | True | True | precision_met_after_minimum |
| rf_wasmtime_rps600 | 34 | True | True | precision_met_after_minimum |

## Scientific limitation
Data collection and file completeness do not establish supervisor acceptance.
Actual thread and CPU observations and complete request series must be evaluated before GO.
Native historical 100-run campaign is preserved separately and is not pooled as a matched campaign.
Docker bridge mode is inspected, but OS-level thread parity must still be reviewed, because the existing Docker LR server uses #[tokio::main] and may not honor TOKIO_WORKER_THREADS.
Precision CI evaluates independent full-run summaries, not independent HTTP requests; failure or load loss prevents a full precision acceptance.

## Remaining prescribed evidence
- WP1 common-ingress path parity, no-op load generator/gateway headroom, observed thread and CPU parity
- WP2 application vs Docker-helper PSS where measurable; current visibility is partial
- WP3 guest-call, input-copy, and complete-service timing boundaries without double-counting
- WP3 real service cold start and warm admission scope comparability
