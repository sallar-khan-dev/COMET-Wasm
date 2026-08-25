# COMET-Wasm Performance Scaling Result — Naive Bayes

## Experiment

Backends:

- Wasmtime multi-instance execution
- Docker native-container execution

Physical serving units:

- 20 Wasmtime workers
- 20 Docker containers

Concurrency levels:

- 1
- 2
- 4
- 8
- 16
- 32
- 64

Requests per measured repetition:

- 5000

Statistical protocol:

- 95% confidence interval
- minimum repetitions: 20
- maximum repetitions: 60
- relative CI half-width target: 2.5%
- throughput, P95, and P99 must all satisfy the target for PASS

Each repetition uses a fresh backend lifecycle:

1. clean backend startup
2. readiness
3. warm-up
4. measured request load
5. shutdown
6. cooldown

## Main Results

| Concurrency | Wasmtime RPS | Docker RPS | Wasmtime/Docker | Wasmtime P95 (ms) | Docker P95 (ms) | Wasmtime P99 (ms) | Docker P99 (ms) |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 6171.4 | 678.1 | 9.10x | 0.205 | 1.617 | 0.214 | 1.653 |
| 2 | 8476.3 | 1805.9 | 4.69x | 0.335 | 1.513 | 0.349 | 1.615 |
| 4 | 8902.9 | 3685.6 | 2.42x | 0.652 | 1.574 | 0.678 | 2.014 |
| 8 | 9071.8 | 5835.0 | 1.55x | 1.293 | 1.691 | 1.339 | 1.848 |
| 16 | 9134.7 | 5996.4 | 1.52x | 2.592 | 3.017 | 2.658 | 3.453 |
| 32 | 9296.6 | 5792.2 | 1.61x | 5.031 | 5.895 | 5.177 | 9.780 |
| 64 | 9058.3 | 5436.5 | 1.67x | 7.964 | 11.977 | 34.200 | 32.448 |

## Peak Throughput

Wasmtime:

- 9296.6 requests/s
- observed at concurrency 32

Docker:

- 5996.4 requests/s
- observed at concurrency 16

Wasmtime peak observed throughput is approximately 55% higher than Docker.

## Tail-Latency Behaviour

Wasmtime has lower P95 latency at every tested concurrency level.

Wasmtime also has lower P99 latency through concurrency 32.

At concurrency 64, both backends exhibit unstable tail behaviour:

- Wasmtime P99: 34.200 ms
- Docker P99: 32.448 ms

Therefore, concurrency 64 should be interpreted as an overload/saturation regime rather than a normal steady-state operating point.

## CI Status

Wasmtime:

- PASS: C=1,2,4,8,16,32
- MAX-REPS: C=64

Docker:

- PASS: C=1,16,32
- MAX-REPS: C=2,4,8,64

MAX-REPS points are retained in the final dataset and not removed as outliers.

## Scope

These results apply to the Gaussian Naive Bayes workload under the specified COMET-Wasm and Docker implementations.

They should not yet be generalized to all ML workloads until cross-workload validation is completed.
