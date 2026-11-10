# COMET-Wasm: next supervisor-plan checkpoint

## Scope
WP1 capacity data collected but not formally accepted. WP2 permits parallel work after thread control; this checkpoint processes existing WP2 density data without rerunning experiments.

## WP2 evidence
- Statistical precision: {'reported_ci_cells': 98, 'reported_ci_unit': 'percent', 'max_reported_relative_ci_pct': 1.3309523663692973, 'ci_over_2p5_pct': 0}; 2.5% is a pre-existing experimental precision target, not a new supervisor WP2 acceptance threshold.
- Source: `results/processed/density/density_seven_levels_statistical_summary.csv` (SHA256 16d4887ccf31ae25...)
- Required 7 models × 2 backends × 7 densities = **98 cells**; present 42/98.
- Missing cells: [('dt', 'docker', 1), ('dt', 'docker', 5), ('dt', 'docker', 10), ('dt', 'docker', 20), ('dt', 'docker', 50), ('dt', 'docker', 100), ('dt', 'docker', 200), ('dt', 'wasmtime', 1), ('dt', 'wasmtime', 5), ('dt', 'wasmtime', 10), ('dt', 'wasmtime', 20), ('dt', 'wasmtime', 50)]
- Saved **measured** density/delta curves in `wp2_derived_curve.csv`; delta relative to N=1 is not independently measured base/model-resident memory.
- Docker daemon/helper PSS evidence: **not demonstrated by source summary**
- Wasmtime JIT/AOT pilot evidence: **not demonstrated by source summary**

## Acceptance and next execution boundary
- **WP1:** REVIEW; the client/gateway no-op envelope and native attribution are not conclusively accepted by current summaries.
- **WP2:** REVIEW; never infer total process, helper, and model-resident memory from a single total-PSS column.
- **WP3:** Not started by this script, because the supervisor requires paired batched-kernel and matched admission timing protocols.
- **WP4:** Existing kernel runs retained. No final service crossover claim.
- **WP5/WP6:** Not started; supervisor stop/go after WP1–WP3 remains in force.

## Outstanding actions
- WP2: obtain separately attributable Docker application and helper/runtime PSS with consistent process coverage.
- WP2 §5.1: run or locate comparable JIT-loaded vs AOT/precompiled Wasmtime pilot under same thread limits.
- WP2: establish base, resident-model and incremental memory attribution separately; N=1 total PSS is not a base-memory measurement.
- WP2: investigate genuine missing/duplicate/corrupt rows in saved data before accepting curves.
