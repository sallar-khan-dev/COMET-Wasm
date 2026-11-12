# Supervisor WP1 matched full-scale serving correction

- Runner status: **DATA COLLECTED; ACCEPTANCE REVIEW REQUIRED**
- Repetitions collected: **1071** (adaptive range 400–1200)
- Completely successful repetitions: **1071 / 1071**

| Model/backend | Repetitions | Full-success | Successful no-op rates (RPS) |
|---|---:|---:|---|
| lr_wasmtime | 230 | 230 | 4800 |
| lr_docker | 300 | 300 | 4800 |
| rf_wasmtime | 241 | 241 | 4800 |
| rf_docker | 300 | 300 | 4800 |

## Formal independent-run statistical precision
| Model/backend/rate | Runs | 95% CI precision | Correctness | Stopping |
|---|---:|---|---|---|
| lr_docker_rps100 | 60 | False | True | maximum_60_reached_precision_unmet |
| lr_docker_rps1200 | 60 | False | True | maximum_60_reached_precision_unmet |
| lr_docker_rps2400 | 60 | False | True | maximum_60_reached_precision_unmet |
| lr_docker_rps300 | 60 | False | True | maximum_60_reached_precision_unmet |
| lr_docker_rps600 | 60 | False | True | maximum_60_reached_precision_unmet |
| lr_wasmtime_rps100 | 60 | False | True | maximum_60_reached_precision_unmet |
| lr_wasmtime_rps1200 | 20 | True | True | precision_met_after_minimum |
| lr_wasmtime_rps2400 | 30 | True | True | precision_met_after_minimum |
| lr_wasmtime_rps300 | 60 | False | True | maximum_60_reached_precision_unmet |
| lr_wasmtime_rps600 | 60 | False | True | maximum_60_reached_precision_unmet |
| rf_docker_rps100 | 60 | False | True | maximum_60_reached_precision_unmet |
| rf_docker_rps1200 | 60 | False | True | maximum_60_reached_precision_unmet |
| rf_docker_rps2400 | 60 | False | True | maximum_60_reached_precision_unmet |
| rf_docker_rps300 | 60 | False | True | maximum_60_reached_precision_unmet |
| rf_docker_rps600 | 60 | False | True | maximum_60_reached_precision_unmet |
| rf_wasmtime_rps100 | 60 | False | True | maximum_60_reached_precision_unmet |
| rf_wasmtime_rps1200 | 20 | True | True | precision_met_after_minimum |
| rf_wasmtime_rps2400 | 60 | False | True | maximum_60_reached_precision_unmet |
| rf_wasmtime_rps300 | 41 | True | True | precision_met_after_minimum |
| rf_wasmtime_rps600 | 60 | False | True | maximum_60_reached_precision_unmet |

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
