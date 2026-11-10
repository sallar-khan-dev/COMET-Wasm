# WP2 §5.1 Wasmtime JIT/AOT measured memory pilot

- Repetitions per condition: **20**
- One CPU: **0**, workers: **1**
- JIT mean ready PSS: **10502.72 KiB**
- AOT mean ready PSS: **5092.46 KiB**
- AOT minus JIT: **-5410.26 KiB**
- All prediction checks: **True**

Raw samples: `samples.csv`; repetitions: `trial_summary.csv`; precompilation provenance: `manifest.json`.

This is a scoped configuration-sensitivity pilot, not WP2-wide acceptance.
