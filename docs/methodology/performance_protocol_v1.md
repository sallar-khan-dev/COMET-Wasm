# COMET-Wasm Throughput and Tail-Latency Protocol v1

## Objective

Compare multi-tenant inference throughput and latency scaling between:

- Wasmtime multi-instance execution
- Docker container execution

## Reference workload

Gaussian Naive Bayes on the Breast Cancer dataset.

## Physical serving units

20 physical inference units for both backends:

- Wasmtime: 20 independent Store/Instance workers
- Docker: 20 native inference containers

## Concurrency levels

1, 2, 4, 8, 16, 32, 64, 128, 256

## Requests per repetition

5000 inference requests.

## Metrics

- throughput_rps
- mean_latency_ms
- p50_latency_ms
- p90_latency_ms
- p95_latency_ms
- p99_latency_ms
- max_latency_ms
- error_rate

## Statistical protocol

Minimum repetitions: 20

Maximum repetitions: 60

Confidence level: 95%

Target relative CI half-width: 2.5%

A concurrency point is considered stable only when all three primary metrics satisfy the target:

- throughput
- P95 latency
- P99 latency

## CPU / NUMA isolation

Host:

- 2 sockets
- 32 cores/socket
- 2 threads/core
- 128 logical CPUs
- 2 NUMA nodes

NUMA node 0:
even logical CPUs

NUMA node 1:
odd logical CPUs

Benchmark policy:

- inference backend is pinned to NUMA node 0
- client/load generator is pinned to NUMA node 1

This prevents the benchmark client from directly competing with the server for the same logical CPUs.

## Interpretation

The experiment evaluates application-level serving throughput and latency under controlled concurrent request load.

Results from the Naive Bayes reference workload are not generalized to all workload classes until cross-workload evaluation is completed.

## Repetition independence amendment

The initial performance stability test identified distinct throughput
regimes when repeated client measurements were executed against one
long-lived inference backend.

Therefore, final performance repetitions use independent backend
lifecycles.

For every repetition:

1. ensure no previous backend instance remains;
2. start a clean inference backend;
3. wait for readiness;
4. warm all physical serving units;
5. execute the measured request workload;
6. record performance metrics;
7. terminate the backend;
8. apply a cooldown period;
9. proceed to the next repetition.

This prevents persistent backend state from coupling nominally independent
performance observations.

The original long-lived-backend measurements are retained only as a
diagnostic dataset and are excluded from final comparative statistics.
