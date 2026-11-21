import csv, hashlib, json, math, os, subprocess, sys
from pathlib import Path
from datetime import datetime, timezone

import numpy as np
from scipy.stats import t

ROOT = Path("/home/sallar/wasiMultitenant")
PROBE = ROOT / "research_enhancement/wp3_kernel_admission/admission_probe/target/release/comet_admission_probe"
WASM = ROOT / "wasm/tenant_lr_real/target/wasm32-unknown-unknown/release/tenant_lr_real.wasm"
BASE = ROOT / "research_enhancement/automated_supervisor_workplan/wp3_wasm_batched_admission"
CPU = min(os.sched_getaffinity(0))
BATCH = 100
WARMUP = 3
MIN_RUNS = 20
MAX_RUNS = 60

for p in (PROBE, WASM):
    if not p.is_file():
        sys.exit(f"BLOCKED: required existing artifact unavailable: {p}")

out = BASE / datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
out.mkdir(parents=True, exist_ok=False)

manifest = {
    "experiment": "Supervisor WP3 Section 6.2, preloaded Wasmtime admission",
    "model": "LR",
    "cpu": CPU,
    "admissions_per_independent_batch": BATCH,
    "warmup_per_batch": WARMUP,
    "minimum_batches": MIN_RUNS,
    "maximum_batches": MAX_RUNS,
    "confidence": 0.95,
    "relative_halfwidth_target": 0.025,
    "bootstrap_resamples": 5000,
    "probe_sha256": hashlib.sha256(PROBE.read_bytes()).hexdigest(),
    "wasm_sha256": hashlib.sha256(WASM.read_bytes()).hexdigest(),
    "scope": "Store/Instance admission with preloaded Engine/Module; excludes HTTP and deployment startup",
    "historical_60_run_experiment": "NOT_POOLED"
}
(out / "manifest.json").write_text(json.dumps(manifest, indent=2))

rows = []

def run_batch(index):
    p = subprocess.Popen(
        ["taskset", "-c", str(CPU), str(PROBE), str(WASM)],
        cwd=ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1
    )
    try:
        response = p.stdout.readline().strip()
        if response != "READY":
            raise RuntimeError(f"Probe startup failed: {response!r}")

        samples = []
        for j in range(WARMUP + BATCH):
            p.stdin.write("RUN\n")
            p.stdin.flush()
            answer = p.stdout.readline().strip()
            if not answer.startswith("OK,"):
                raise RuntimeError(f"Unexpected admission response: {answer!r}")
            duration = int(answer.split(",", 1)[1])
            if duration <= 0:
                raise RuntimeError("Invalid admission duration")
            if j >= WARMUP:
                samples.append(duration)

        p.stdin.write("STOP\n")
        p.stdin.flush()
        p.wait(timeout=10)
        if p.returncode:
            raise RuntimeError(f"Admission probe exited {p.returncode}")

        return {
            "batch": index,
            "admissions": len(samples),
            "mean_admission_ns": float(np.mean(samples)),
            "total_admission_ns": sum(samples)
        }
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()
        for stream in (p.stdin, p.stdout, p.stderr):
            if stream:
                stream.close()

def precision():
    x = np.array([r["mean_admission_ns"] for r in rows])
    n = len(x)
    mean = float(x.mean())
    th = float(t.ppf(.975, n-1) * x.std(ddof=1) / math.sqrt(n))
    rng = np.random.default_rng(20261121 + n)
    boot = x[rng.integers(0, n, size=(5000, n))].mean(axis=1)
    bh = float(np.diff(np.quantile(boot, [.025, .975]))[0] / 2)
    return {
        "independent_batches": n,
        "admissions_measured": n * BATCH,
        "mean_admission_ns": mean,
        "student_t_relative_halfwidth_pct": 100 * th / mean,
        "bootstrap_relative_halfwidth_pct": 100 * bh / mean,
        "accepted": max(th, bh) / mean <= 0.025
    }

print("WP3 BATCHED ADMISSION STARTED", flush=True)
print("RESULTS:", out, flush=True)

for i in range(1, MAX_RUNS + 1):
    rows.append(run_batch(i))

    with (out / "batches.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    if i >= MIN_RUNS and (i == MIN_RUNS or i % 5 == 0):
        result = precision()
        (out / "RESULT.json").write_text(json.dumps(result, indent=2))
        print(
            f"BATCHES={i} ADMISSIONS={i*BATCH} "
            f"Student-t={result['student_t_relative_halfwidth_pct']:.3f}% "
            f"Bootstrap={result['bootstrap_relative_halfwidth_pct']:.3f}% "
            f"ACCEPTED={result['accepted']}",
            flush=True
        )
        if result["accepted"]:
            break

result = precision()
result["status"] = "PRECISION_ACCEPTED" if result["accepted"] else "PRECISION_NOT_MET"
(out / "RESULT.json").write_text(json.dumps(result, indent=2) + "\n")

print("FINAL:", result["status"], flush=True)
print("REPORT:", out / "RESULT.json", flush=True)
