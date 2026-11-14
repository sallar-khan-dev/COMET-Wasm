# COMET-Wasm WP1 — Corrected Pilot Completion

- Date: 14 November 2026
- Models: Logistic Regression and Random Forest
- Backends: Wasmtime and Docker
- Successful independent repetitions: **481/481**
- Statistical precision acceptance: **20/20 cells**
- Offered loads: 100, 300, 600, 1200, 2400 RPS
- No-op calibration: 4800 RPS across four configurations
- Corrected RF/SVM golden pilot: passed
- Formal campaign: experimentally completed
- Supervisor methodological sign-off: pending

## Limitations

- Equal aggregate thread counts do not prove complete resource equivalence.
- Docker shim PSS could not be measured due to HPC permissions.
- Historical experiments and corrected treatment are not pooled.
- Large raw per-request JSONL and compiled artifacts remain on HPC.
- WP2 and WP3 are outside this completion decision.

Corrected campaign: `research_enhancement/automated_supervisor_workplan/wp1_matched_correction/20261114_015337_2877545`

Validation pilot: `research_enhancement/wp1_rf_svm_pilot_runs/20261114_014457_2876133`
