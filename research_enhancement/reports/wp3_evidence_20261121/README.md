# COMET-Wasm Supervisor WP3 Evidence

## Accepted precision
- Wasmtime batched admission: 45 batches, 4500 admissions.
- Docker cold deployment: 20 independent repetitions.
- Decomposition: native, Wasmtime guest call, copy-plus-call and no-op typed call.

## Outstanding
- Host input-copy precision: NOT ACCEPTED at 60 repetitions.
- Student-t 95% relative half-width: 4.258%.
- Bootstrap 95% relative half-width: 3.555%.
- No-op Wasmtime typed-call is not a pure host-call measurement.
- Complete common-gateway service-cost attribution requires review.
- Cold deployment and warm admission are different operations.
- WP1–WP3 STOP/GO approval remains pending.

Do not pool incompatible Docker image campaigns.
Do not redesign the scheduler before the supervisor STOP/GO checkpoint.
