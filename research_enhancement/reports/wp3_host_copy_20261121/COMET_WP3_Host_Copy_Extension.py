import csv, hashlib, json, math, os, subprocess, sys
from collections import Counter
from pathlib import Path
import numpy as np
from scipy.stats import t

ROOT = Path("/home/sallar/wasiMultitenant")
BASE = ROOT / "research_enhancement/automated_supervisor_workplan"
OLD = BASE / "wp3_copy_call_decomposition/20261121_031019_419098_3892934"
OUT = BASE / "wp3_host_copy_extension_20261121"

EXE = ROOT / "serving/common_ingress/target/release/comet_wp3_cost_decomp"
WASM = ROOT / "wasm/tenant_lr_real/target/wasm32-unknown-unknown/release/tenant_lr_real.wasm"
TRACE = ROOT / "research_enhancement/v2_workloads/lr_iris_trace_135_seed42_t3.json"

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def require(condition, message):
    if not condition:
        sys.exit("SAFE STOP: " + message)

old_manifest = json.loads((OLD / "manifest.json").read_text())
cpu = int(old_manifest["cpu"])
batch = int(old_manifest["batch_per_input"])

for p in (EXE, WASM, TRACE, OLD / "trials.csv"):
    require(p.is_file(), f"Missing original artifact: {p}")

require(cpu in os.sched_getaffinity(0), "Original CPU unavailable")
require(batch == 500, "Original batch configuration changed")
require(sha(EXE) == old_manifest["executable_sha256"], "Benchmark binary changed")
require(sha(WASM) == old_manifest["wasm_sha256"], "Wasm artifact changed")
require(sha(TRACE) == old_manifest["trace_sha256"], "Input trace changed")

with (OLD / "trials.csv").open() as f:
    historical = list(csv.DictReader(f))

metrics = {"native", "wasmtime", "host_copy",
           "copy_plus_wasm", "noop_typed_call"}

counts = Counter(int(r["process"]) for r in historical)
require(len(counts) == 60 and
        all(counts.get(i) == 5 for i in range(1, 61)),
        "Original 60-process evidence incomplete")

for i in range(1, 61):
    observed = {r["metric"] for r in historical if int(r["process"]) == i}
    require(observed == metrics, f"Original process {i} incomplete")

baseline = [
    float(r["ns_per_call"])
    for r in historical if r["metric"] == "host_copy"
]

OUT.mkdir(parents=True, exist_ok=True)

manifest = {
    "experiment": "WP3 host-copy precision extension",
    "original_campaign": str(OLD),
    "original_trials_sha256": sha(OLD / "trials.csv"),
    "binary_sha256": sha(EXE),
    "wasm_sha256": sha(WASM),
    "trace_sha256": sha(TRACE),
    "cpu": cpu,
    "calls_per_input": batch,
    "historical_processes": 60,
    "maximum_total_processes": 220,
    "confidence": 0.95,
    "relative_halfwidth_target": 0.025,
    "bootstrap_resamples": 5000,
    "accepted_prior_metrics": "Preserved; no new acceptance claim",
    "scope": "Host-to-Wasm linear-memory write only"
}

manifest_path = OUT / "manifest.json"
if manifest_path.exists():
    require(json.loads(manifest_path.read_text()) == manifest,
            "Existing extension has different provenance")
else:
    manifest_path.write_text(json.dumps(manifest, indent=2))

def read_process(path):
    with path.open() as f:
        rows = list(csv.DictReader(f))

    require(len(rows) == 5 and
            {r["metric"] for r in rows} == metrics,
            f"Incomplete process: {path}")

    checks = {r["metric"]: r["checksum"] for r in rows}
    require(len({checks[m] for m in
                 ("native", "wasmtime", "copy_plus_wasm")}) == 1,
            f"Prediction mismatch: {path}")

    require(all(int(r["calls"]) == 67500 for r in rows),
            f"Unexpected batch count: {path}")

    return float(next(r["ns_per_call"] for r in rows
                      if r["metric"] == "host_copy"))

def precision(values):
    x = np.asarray(values, dtype=float)
    n = len(x)
    avg = float(x.mean())
    require(np.isfinite(x).all() and avg > 0,
            "Invalid host-copy samples")

    th = float(t.ppf(.975, n-1) * x.std(ddof=1) / math.sqrt(n))
    rng = np.random.default_rng(20261121 + n)
    boot = x[rng.integers(0, n, size=(5000, n))].mean(axis=1)
    bh = float(np.diff(np.quantile(boot, [.025, .975]))[0] / 2)

    return {
        "total_independent_processes": n,
        "new_independent_processes": n - 60,
        "mean_host_copy_ns": avg,
        "student_t_relative_halfwidth_pct": 100 * th / avg,
        "bootstrap_relative_halfwidth_pct": 100 * bh / avg,
        "accepted": max(th, bh) / avg <= 0.025
    }

values = list(baseline)

print("WP3 HOST-COPY PRECISION EXTENSION", flush=True)
print("Original 60 processes preserved.", flush=True)
print("Original executable and input hashes verified.", flush=True)
print("Output:", OUT, flush=True)

for rep in range(61, 221):
    current = precision(values)
    if current["accepted"]:
        break

    file = OUT / f"process_{rep:03d}.csv"

    if not file.exists():
        result = subprocess.run(
            ["taskset", "-c", str(cpu), str(EXE),
             str(WASM), str(TRACE), str(batch),
             str(rep), str(file)],
            cwd=ROOT, capture_output=True, text=True, timeout=120
        )
        require(result.returncode == 0,
                f"Process {rep} failed: {result.stderr[-500:]}")

    values.append(read_process(file))

    if rep % 10 == 0:
        current = precision(values)
        (OUT / "RESULT.json").write_text(
            json.dumps(current, indent=2) + "\n"
        )
        print(
            f"PROCESSES={rep} "
            f"Student-t={current['student_t_relative_halfwidth_pct']:.3f}% "
            f"Bootstrap={current['bootstrap_relative_halfwidth_pct']:.3f}% "
            f"ACCEPTED={current['accepted']}",
            flush=True
        )

final = precision(values)
final["status"] = (
    "HOST_COPY_PRECISION_ACCEPTED"
    if final["accepted"]
    else "HOST_COPY_PRECISION_NOT_MET"
)

(OUT / "RESULT.json").write_text(
    json.dumps(final, indent=2) + "\n"
)

print("FINAL:", final["status"], flush=True)
print("REPORT:", OUT / "RESULT.json", flush=True)
