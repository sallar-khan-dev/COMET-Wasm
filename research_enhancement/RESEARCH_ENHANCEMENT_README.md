# COMET-Wasm research team approval proposal (NOT validated HPC deployment)

## Safety and scope
The original repository is preserved unchanged outside `research_enhancement/`.
Do not merge, deploy, publish new performance numbers or replace the existing scheduler before approval.
The new files are proof-of-design implementations and unit tests, **not** a complete WP1–WP6 execution harness.
No GPU work is included, in accordance with the work plan’s explicit CPU-only scope.

## Verified source findings
- `comet/scheduler/scheduler.py` uses nearest measured concurrency and weighted suitability.
- `comet/backend_selector/feasibility.py` clamps tenants <=20 to the 20-tenant PSS.
- `comet/evaluation/live_client.py` is an asyncio/aiohttp client using per-backend ports.
- The current manuscript claims density-aware tenant placement, while the research team requests admission-time backend selection only.

## New review-only files
- `gateway.py`: aiohttp common-ingress reference prototype with static per-tenant routing and `/noop` endpoint. Does not yet launch Docker or Wasmtime; admission/controller integration pending.
- `scheduler_v2.py`: standalone, constraint-first, memory-first selection with fail-closed interpolation and no weight retuning. The illustrative test fixtures are synthetic unit tests, **not** experimental results.
- `deterministic_trace.py`: reproducible cycling through all reference rows; caller must export actual reference predictions first.
- `system_snapshot.py`: read-only CPU/software/thread information capture.
- `tests/`: fast logic tests.

## Run review tests locally (no HPC needed)
From repository root:
```bash
python -m unittest discover -s research_enhancement/tests -v
python -m compileall -q research_enhancement
```
For a local gateway smoke test, after installing `aiohttp` in a venv and starting the appropriate real serving endpoints:
```bash
python -m research_enhancement.gateway --routes research_enhancement/routes.example.json --port 8200
curl http://127.0.0.1:8200/noop
```
The example Docker IP is illustrative and MUST be replaced with the actual internal bridge IP. Gateway should bind to the server-facing address only after security review.

## WP1 gate — serving foundation
1. Preserve old scripts and results as legacy; branch from a frozen git revision.
2. Wire existing Wasmtime `/infer` and Docker `/infer` behind the gateway, same tenant ID, features and output semantics.
3. Run Docker in a dedicated internal bridge with no per-tenant client-published ports; host-network diagnostic separately.
4. Control Tokio worker threads and CPU affinity symmetrically; collect `/proc/PID/status` actual Threads and context switches.
5. Implement and independently validate a high-headroom Rust open-loop generator with offered-rate scheduling, connection reuse, scheduled-arrival latency, drops/lateness/errors and generator CPU. The supplied Python gateway/noop is only a foundation, **not** proof of load-generator headroom.
6. Export reference predictions and run identical deterministic varied traces on all paths; validate equality.
7. Pilot LR and RF (or SVM), including no-op saturation and gateway bypass attribution. Gate: generator/gateway headroom and stable curves.

## WP2 gate — corrected memory
- N=1,5,10,20,50,100,200; identical thread caps and process attribution.
- Collect PSS from `/proc/PID/smaps_rollup` and distinguish app PSS from identifiable helper/daemon costs.
- Freeze JIT vs precompiled/AOT choice only after controlled pilot.
- Use interpolation within observed range only; never reuse 20-tenant value for 1 tenant.

## WP3 gate — timing
- Batched native/Wasm calls on varied inputs; use native black_box to prevent elimination.
- Separate kernel, input copy, service path; deployment cold start vs warm tenant admission with symmetric HTTP readiness.
- Do not apply cold-start preference to warm admission decisions.

## WP4 gate — CPU crossover
- From measured dispatch and batched compute terms, estimate crossover before selecting models.
- Scale current MLP/RF/SVM first; add at most one heavier CPU model only if justified.
- Repeat memory curves for heavy variants; never assert a Docker win without live evidence.

## WP5 gate — admission scheduler
- After WP1–WP4, produce tenant-conditioned, rate-conditioned sparse profile anchors.
- `scheduler_v2.py` illustrates the work plan’s constraint-first memory objective and rejects unsupported points.
- Validate interpolation on separate measured points, offered-rate capacity, SLA, memory, correctness and errors.
- Admit at tenant/model onboarding; cache route for ordinary requests; no migration or node/slot placement.
- Do NOT feed legacy concurrency-based profiles directly into the new offered-rate policy.

## WP6 gate — independent held-out live validation
- Pre-freeze development profiles and policy. Hold out load rates, tenant counts and light/boundary/heavy model cases.
- Compare Wasm-only, Docker-only, per-model best-static and COMET. Retrospective live oracle is evaluation-only.
- Record P95 SLA and memory violations, correct admission/rejection, throughput and regret.
- Run changing-load mixed-tenant admissions and specified ablations only after the full policy works.
- Preserve old 140-cell study as legacy evidence; do not present replay as independent live truth.

## Approval questions
1. Approve CPU-only scope and exclusion of GPU/WASI-NN from this paper?
2. Approve common gateway + native attribution baseline + internal Docker bridge?
3. Approve the constraint-first memory objective and dropping unsupported operating points?
4. Approve WP1 pilot LR + RF before committing to full reruns?
5. Approve revising paper terminology from tenant placement to backend selection/admission?

## Git implementation after approval
```bash
git switch -c research-wp1-foundation
python -m unittest discover -s research_enhancement/tests -v
# integrate one WP at a time, then commit reviewed source files explicitly
```
Do not overwrite existing scientific datasets or deploy the demo until new measurements pass each gate.
