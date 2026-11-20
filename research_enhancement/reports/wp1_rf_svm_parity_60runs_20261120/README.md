# COMET-Wasm RF/SVM 60-run Results

**Status:** UNACCEPTED_PRECISION_AT_MAX_60
**Completed:** 60 independent repetitions
**Precision accepted:** 2/8 conditions
**Target:** 95% CI relative half-width <= 2.5%

| Condition | Mean P95 (ms) | Precision |
|---|---:|---|
| rf|docker|infer | 3.7087 | FAIL |
| rf|docker|noop | 2.1715 | FAIL |
| rf|wasmtime|infer | 2.5400 | FAIL |
| rf|wasmtime|noop | 2.1643 | PASS |
| svm|docker|infer | 3.6538 | FAIL |
| svm|docker|noop | 2.1655 | FAIL |
| svm|wasmtime|infer | 2.6065 | FAIL |
| svm|wasmtime|noop | 2.1739 | PASS |

Inference achieved throughput was not recorded and is not estimated.
These results do not constitute final WP1 acceptance.

Source SHA256: `0573d18f66f4daf79046dbf6ce084f2febc027e2e0b15951ad922932856dab1b`
