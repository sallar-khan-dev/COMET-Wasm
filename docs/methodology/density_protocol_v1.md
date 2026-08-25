# COMET-Wasm Physical Tenant Memory-Density Protocol v1

## Objective

Measure how process-level resident memory scales with increasing numbers
of physically isolated ML inference execution units under Wasmtime and Docker.

## Workload

Initial reference workload:

- Model: Gaussian Naive Bayes
- Dataset: Breast Cancer
- Features: 30
- Correctness equivalence:
  Python reference = Wasmtime = Docker

## Physical isolation unit

### Wasmtime

One physical worker consists of:

- independent Wasmtime Store
- independent Wasmtime Instance
- independent guest linear memory

All workers share:

- Linux server process
- Wasmtime Engine
- compiled Module

### Docker

One physical tenant consists of:

- one Docker container
- one native Rust inference process

## Density levels

- 1
- 5
- 10
- 20
- 50
- 100
- 200

## Warm-up

Each physical execution unit receives 100 inference requests before
memory measurement.

Warm-up is applied separately to every worker/container.

## Memory metric

Primary metric:

- Proportional Set Size (PSS)

Secondary metrics:

- RSS
- Private memory

### Wasmtime measurement

/proc/<server-pid>/smaps_rollup

This represents aggregate process memory containing the runtime,
server, and all Wasmtime workers.

### Docker measurement

/proc/1/smaps_rollup read inside every inference container.

PSS values are aggregated across container inference processes.

Therefore, the comparison represents inference-process memory footprint
and does not claim to include all Docker daemon, kernel namespace,
cgroup, or container-management overhead.

## Repetition protocol

For every backend × density level:

1. ensure no previous experimental instances are active;
2. launch a clean configuration;
3. wait for readiness;
4. warm every physical execution unit;
5. collect repeated memory snapshots;
6. aggregate snapshots into one repetition measurement;
7. destroy all experimental instances;
8. repeat from a clean state.

Minimum repetitions: 20

Maximum repetitions: 60

Confidence level: 95%

Target relative confidence-interval half-width: 2.5%

## Experimental outputs

For every backend × density level:

- number of repetitions
- mean PSS
- standard deviation
- 95% confidence interval
- mean RSS
- mean private memory

## Derived analysis

Fit:

M(N) = alpha + beta*N

where:

- alpha = fixed execution/runtime footprint
- beta = marginal memory cost per physical execution unit

Report:

- fitted alpha
- fitted beta
- R-squared
- observed memory ratio
- fitted crossover point where applicable

## Interpretation constraint

Results describe process-level resident-memory scaling for the specified
implementations and workload.

Pilot or single-workload results must not be generalized to all ML
workloads until cross-workload evaluation is completed.
