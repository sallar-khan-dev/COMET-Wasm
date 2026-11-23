# COMET-Wasm — WP1–WP3 scientific STOP/GO review

**Review date:** 2026-11-23 (UTC)  
**Reference:** `COMET_Wasm_Work_Plan (1).docx`, especially §4 (WP1), §5 (WP2), §6 (WP3) and the explicit STOP/GO clause following §6.2.  
**Repository branch assessed:** `research/wp1-lr-2026-11-08`  
**Remote HEAD verified:** `b87fb016681162537f01d26e6050fac63c230ba4` (2026-11-23 07:37:38 UTC)

## Decision: NO-GO for definitive WP4 crossover campaign; GO for targeted acceptance-gap resolution

The supervisor expressly prohibits selecting new heavy workloads or modifying the scheduler until corrected serving-path cost, memory curves and compute/startup primitives are trustworthy. The new WP2 and WP3 diagnostic datasets are complete but cannot, by themselves, satisfy all WP1–WP3 acceptance criteria. This is an evidence-quality gate, not a rejection of completed experiments or a demand to repeat them.

## WP1 — benchmark-path and load-resource controls: PARTIAL

**Available:** Common-ingress/native attribution reports, corrected LR/RF serving series, RF/SVM pilot and 60-run statistical report; open-loop work and some no-op tests.

**Outstanding scientific decisions:**
1. Demonstrate actual generator **and gateway** no-op headroom beyond fastest ML backend with relevant successful throughput, errors/drops, offered load and client/gateway CPU evidence.
2. Verify actual worker-thread totals, `Cpus_allowed_list`, resource controls, and container path through the **same ingress**. A published loopback Docker forwarding route and separate historical client configurations do not establish bridge/native/Wasmtime statistical parity.
3. Ensure matched varied deterministic request trace and golden prediction correctness on the final WP1 path.
4. Record the 60-run RF/SVM pilot precision misses (2/8 P95 conditions accepted) without altering or deleting the data. These are reportable limitations, not automatic rerun requests.

**Evidence:** `research_enhancement/reports/wp1_native_20261121/REPORT.md`; `research_enhancement/reports/wp1_rf_svm_parity_60runs_20261120/{README.md,SOURCE_REPORT.md}`; existing corrected WP1 source runs.

## WP2 — density and memory: DATASET COMPLETE; ACCOUNTING PARTIAL

**Verified audit:** seven models × seven tenant densities {1,5,10,20,50,100,200} × two backends = **98/98 backend-density conditions**, **1,960 raw backend-condition repetitions**, and **98/98 reported PSS precision checks ≤2.5%**. Six-model readiness retries (SVM N=50; MLP N=100) are preserved. No need to rerun this accepted density campaign.

**Outstanding:** Baseline/model-resident/incremental per-tenant PSS attribution, measurable Docker helper and deployment overhead (or explicitly bounded/unobservable on unprivileged host), thread-count verification across density, and integration of measured JIT versus AOT pilot without incorrectly declaring full-component precision. The prior JIT/AOT ready-PSS difference was observed under a scoped pilot only.

**Evidence:** `research_enhancement/automated_supervisor_workplan/wp2_seven_model_controlled_audit_20261123/{WP2_Controlled_Audit.json,WP2_Seven_Model_98_Conditions.csv,WP2_App_PSS_Comparison.csv}`; `research_enhancement/reports/wp2_memory_attribution_20261121/README.md`.

## WP3 — timing and readiness: DIAGNOSTIC COMPLETE; SYMMETRY PARTIAL

**Verified:** seven reference models × three densities {1,20,50} × two backends = **42 completed backend-density conditions**, **847 observations**; first-valid-response and all-ready timing metrics both recorded, **84/84 metric precision checks ≤2.5%**. These are **direct functional HTTP `/infer` readiness** measurements and must be labelled **DIRECT_ENDPOINT_DIAGNOSTIC_NOT_COMMON_GATEWAY**.

**Outstanding:** Final *symmetric* full-deployment cold-start comparison (whole Wasmtime process/engine/module/workers through common gateway vs `docker run` plus equal HTTP readiness), separate *warm admission* comparison (preloaded Wasmtime Engine/Module instance vs precreated Docker start), native kernel, guest-call, input-copy and complete gateway request-path cost with clear non-overlapping boundaries. Existing service cost study accepted only **338/480** metric-quantile precision checks; do not present these as 480/480 passed. Historical measurements and script refinements should be reviewed rather than blindly repeated.

**Evidence:** `research_enhancement/automated_supervisor_workplan/wp3_cold_http_ready_seven_models_20261123/{RESULT.json,manifest.json,trials.csv}`; `research_enhancement/reports/wp3_service_cost_20261121/README.md`; `research_enhancement/reports/wp3_host_copy_20261121/RESULT.json`; `research_enhancement/reports/wp3_precision_final_20261121/`.

## Required targeted actions, in order

1. **Evidence-only acceptance matrix:** Extract from existing files matched client/gateway/no-op capacity, real process thread counts/CPU affinity and Docker bridge attribution; classify PASS, FAIL or UNOBSERVABLE with exact source paths. No concurrent benchmark.
2. **WP2 attribution reconciliation:** Reuse accepted 98-condition PSS curves. Reconcile JIT/AOT, base/model/incremental growth and Docker helpers; mark truly unobservable helper overhead, rather than treating it as zero.
3. **WP3 topology-symmetric pilot only if needed:** Using fixed CPU/thread budgets, frozen binaries/images and deterministic golden trace, measure equal gateway-path `/health` or equivalent ready checks for new deployment and already-prepared tenant admission. Keep cold and warm scopes separate. Use 20–60 repetitions, Student-t/bootstrapped 95% CI, report misses at 60 without forcing acceptance. Preserve readiness failures in separate reliability evidence.
4. **Decision review:** Produce WP1–WP3 signed-off acceptance evidence and a defensible estimated crossover `K*` from corrected gateway dispatch delta and native-vs-Wasm kernel ratio. Only then **GO** to WP4 scaled MLP/RF/SVM, and do not choose a heavy model to force a Docker win.

## Git provenance audit

Confirmed remote research branch contains at least **11 commits dated November 20–23, 2026**, including WP1 RF/SVM and native reports, WP2 memory attribution and 98-cell controlled data, WP3 timing/host-copy/service-cost reports, and the seven-model WP3 diagnostic. The two latest verified commits:

- `683709b6e780bc2544804bdf2361766f28a26a9d` — controlled WP2 seven-model memory evidence and audit (2026-11-23 04:43 UTC).
- `b87fb016681162537f01d26e6050fac63c230ba4` — WP3 seven-model cold-readiness diagnostic and precision report (2026-11-23 07:37 UTC).

**Not verifiable from remote GitHub alone:** untracked, ignored, modified or unpushed files currently present only on the HPC. Inspect locally via `git status --short`, `git ls-files --others --exclude-standard`, `git status --ignored --short`, and `git diff --stat` before declaring full workstation/server backup complete. Avoid committing secrets, virtual environments, Docker layers or generated caches. Use an explicit allowlist for new research evidence and scripts.

## Claim discipline

- Do **not** label the WP1–WP3 scientific gate PASS simply because WP2 and WP3 diagnostic scripts finished.
- Do **not** compare direct-endpoint cold timings as scientifically equivalent common-gateway startup.
- Do **not** change the pre-established 20–60-run statistical policy, discard CI misses, or rerun accepted conditions solely to improve precision.
- Do **not** start WP4 heavy experiments or retune WP5 scheduler before closing the methodological blockers.

**Review outcome:** NO-GO pending evidence/targeted correction; continue work on existing WP1–WP3 scope, not WP4 expansion.
