# COMET-Wasm Memory-Density Result — Naive Bayes

## Experiment

Backends:

- Wasmtime multi-instance worker pool
- Docker native-container baseline

Physical tenant levels:

- 1
- 5
- 10
- 20
- 50
- 100
- 200

Repetitions:

- 20 independent clean repetitions per backend × density level
- 140 observations per backend
- 280 observations total

Statistical protocol:

- 95% confidence interval
- minimum repetitions: 20
- maximum repetitions: 60
- stopping target: relative CI half-width <= 2.5%

All evaluated density levels satisfied the CI target after the minimum
20 repetitions.

## Memory metric

Primary metric:

Aggregate inference-process Proportional Set Size (PSS).

Wasmtime measurement includes the server process containing:

- Wasmtime Engine
- compiled module
- independent Stores
- independent Instances
- worker linear memories

Docker PSS is aggregated across the native inference processes executing
inside the corresponding containers.

The comparison therefore concerns inference-process resident memory and
does not claim to include all Docker daemon, kernel namespace, cgroup,
or container-management overhead.

## Results

| Physical tenants | Wasmtime PSS (MiB) | Docker PSS (MiB) | Docker / Wasmtime |
|---:|---:|---:|---:|
| 1 | 17.560 | 3.200 | 0.182x |
| 5 | 17.590 | 13.591 | 0.773x |
| 10 | 17.649 | 25.757 | 1.459x |
| 20 | 17.765 | 49.504 | 2.787x |
| 50 | 18.069 | 119.673 | 6.623x |
| 100 | 18.634 | 236.247 | 12.678x |
| 200 | 19.740 | 469.471 | 23.783x |

## Scaling Models

Wasmtime:

PSS(N) = 17.5383 + 0.010982 N MiB

Marginal fitted cost:

11.246 KiB per physical Wasm instance

R-squared:

0.999861

Docker:

PSS(N) = 2.1031 + 2.338657 N MiB

Marginal fitted cost:

2394.784 KiB per physical Docker inference process

R-squared:

0.999985

## Density Crossover

Fitted crossover:

6.63 physical tenants

Observed crossover:

between 5 and 10 physical tenants

Below the crossover, Docker exhibits the lower inference-process PSS
because Wasmtime carries a larger shared runtime/server baseline.

Above the crossover, the shared Wasmtime execution substrate amortizes
its fixed footprint across increasing numbers of isolated workers,
whereas Docker memory grows approximately linearly with the number of
containerized inference processes.

## High-Density Comparison

At 200 physical tenants:

- Wasmtime PSS: 19.740 MiB
- Docker PSS: 469.471 MiB
- Docker / Wasmtime ratio: 23.783x
- Wasmtime PSS reduction relative to Docker: approximately 95.8%

## Interpretation Constraint

These findings currently apply to the Naive Bayes workload and the
specified COMET-Wasm/Docker implementations.

The result must not yet be generalized to all workload classes until
cross-workload density and performance evaluation is completed.
