# WP3: Precision-controlled timing evidence

## Wasmtime admission
- 45 independent batches, 100 admissions per batch
- Student-t 95% relative half-width: 2.350%
- Bootstrap 95% relative half-width: 2.233%
- Precision: ACCEPTED
- Scope: preloaded Wasmtime module, repeated worker admissions

## Docker deployment
- 20 independent cold deployments
- Student-t 95% relative half-width: 1.887%
- Bootstrap 95% relative half-width: 1.723%
- Precision: ACCEPTED
- Docker image identity frozen in manifest.json
- Scope: container launch through successful HTTP inference

## Scientific restrictions
- These experiments measure different operations and are not direct backend comparisons.
- Historical measurements from the unavailable Docker image were not pooled.
- Batched admission precision does not establish full HTTP admission precision.
- Full input-copy, guest/host-call and serving-path decomposition remains pending.
- WP1-WP3 supervisor STOP/GO is not yet approved.
