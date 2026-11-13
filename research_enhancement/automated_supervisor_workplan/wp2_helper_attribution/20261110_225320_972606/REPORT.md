# WP2 §5, Docker application and attributable runtime-helper memory

- Repeated independent container starts: **20/20**
- Application PSS mean: **2201.84 KiB**
- Container-owned helper PSS mean: **None KiB**
- Fully visible helper trials: **0/20**

Global Docker daemon/containerd PSS remains shared and is **not** attributed per tenant. A missing shim observation is **unknown**, not zero.

**Status:** PARTIAL_HELPER_VISIBILITY. This alone does not establish WP1–WP3 GO.

Preserved: `samples.jsonl`, `trials.csv`, `manifest.json`, `RESULT.json`.
