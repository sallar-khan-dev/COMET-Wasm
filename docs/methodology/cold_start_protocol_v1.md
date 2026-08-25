# COMET-Wasm Cold-Start Protocol v1

## Objective

Measure the cost of creating a new isolated inference tenant and serving
its first request using:

- Wasmtime / COMET-Wasm
- Docker native-container baseline

## Reference workload

Gaussian Naive Bayes on the Breast Cancer dataset.

## Primary metrics

1. backend_startup_ms
   Time from backend creation command until the endpoint becomes ready.

2. first_inference_ms
   End-to-end latency of the first inference request after readiness.

3. cold_to_first_result_ms
   Time from backend creation until completion of the first successful
   inference request.

4. warm_inference_ms
   Latency of a subsequent inference request on the already initialized
   backend.

## Repetition policy

Minimum repetitions: 20
Maximum repetitions: 60

Confidence level: 95%

Relative CI half-width target: 2.5%.

Each repetition uses a completely fresh backend.

## Wasmtime lifecycle

For each repetition:

1. ensure no COMET-Wasm server is running;
2. start a fresh Wasmtime server with one physical worker;
3. measure time until /health becomes ready;
4. submit one inference request;
5. submit warm inference requests;
6. terminate the server;
7. cooldown.

## Docker lifecycle

For each repetition:

1. remove any previous benchmark container;
2. start a fresh native inference container;
3. measure time until the inference endpoint is ready;
4. submit one inference request;
5. submit warm inference requests;
6. terminate/remove container;
7. cooldown.

## Fairness

Both backends use:

- the same Naive Bayes model;
- identical feature input;
- identical correctness requirement;
- the same host;
- the same measurement clock;
- fresh lifecycle per repetition.

The experiment initially measures a single newly-created tenant so that
container and Wasm instantiation costs are directly comparable.

## Interpretation

Cold-start measurements are distinct from the previously completed
steady-state throughput and memory-density experiments.
