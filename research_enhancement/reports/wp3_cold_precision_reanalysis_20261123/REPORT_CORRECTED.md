# WP3 cold precision reanalysis (no new experiment)

Source: `research_enhancement/automated_supervisor_workplan/wp3_symmetric_common_gateway_cold_20261123/20261123_181241_1339927/trials.csv`; 120 raw trials.
Corrected a bootstrap confidence-interval implementation error. Original files remain unchanged.

| Backend | Metric | N | Student-t half-width % | Bootstrap half-width % | Precision accepted |
|---|---|---:|---:|---:|---|
| wasmtime | gateway_health_ms | 60 | 1.604 | 1.725 | True |
| wasmtime | first_valid_ms | 60 | 1.792 | 1.980 | True |
| docker | gateway_health_ms | 60 | 2.072 | 2.127 | True |
| docker | first_valid_ms | 60 | 2.059 | 2.110 | True |

**Decision:** `PRECISION_ACCEPTED_SCOPED_COLD_ONLY`.

The original measured readiness comparison is a scope-limited cold-deployment comparison. It does not establish comparable warm admission, complete memory ownership or WP1 capacity equivalence.
