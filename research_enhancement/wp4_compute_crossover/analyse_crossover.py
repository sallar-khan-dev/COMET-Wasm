#!/usr/bin/env python3

import csv
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXEC = ROOT / "results/processed/execution_time"
PERF = ROOT / "results/processed/performance"
OUT = ROOT / "results/processed/crossover"

MODELS = [
    "decision_tree",
    "kmeans",
    "logistic_regression",
    "mlp",
    "naive_bayes",
    "random_forest",
    "svm",
]

OUT.mkdir(parents=True, exist_ok=True)

def load(path):
    return json.loads(path.read_text())

def performance_at_concurrency(data, concurrency=2):
    point = data["summary"].get(str(concurrency), {})

    p95 = point.get("p95", {})
    throughput = point.get("throughput", {})

    return (
        float(p95["mean"]) if "mean" in p95 else math.nan,
        float(throughput["mean"]) if "mean" in throughput else math.nan
    )

rows = []

for model in MODELS:
    ew = load(EXEC / f"wasmtime_{model}_execution_time_full_summary.json")
    ed = load(EXEC / f"docker_{model}_execution_time_full_summary.json")
    pw = load(PERF / f"wasmtime_{model}_performance_full_summary.json")
    pd = load(PERF / f"docker_{model}_performance_full_summary.json")

    kw = float(ew["execution_mean_ns"]) / 1000.0
    kd = float(ed["execution_mean_ns"]) / 1000.0

    lw, tw = performance_at_concurrency(pw)
    ld, td = performance_at_concurrency(pd)

    slowdown = kw / kd if kd > 0 else math.nan

    # Illustrative decomposition only:
    # P95 request latency and mean kernel timing are
    # different statistics and must not be interpreted
    # as a directly measured P95 dispatch cost.
    dw_proxy = lw * 1000.0 - kw
    dd_proxy = ld * 1000.0 - kd

    denominator = slowdown - 1.0

    if denominator > 0:
        crossover = (dd_proxy - dw_proxy) / denominator
        if crossover <= 0:
            crossover = math.nan
    else:
        crossover = math.nan

    rows.append({
        "model": model,
        "wasmtime_kernel_us": round(kw, 6),
        "docker_kernel_us": round(kd, 6),
        "kernel_slowdown_wasm_over_docker": round(slowdown, 6),
        "wasmtime_p95_ms_c2": round(lw, 6),
        "docker_p95_ms_c2": round(ld, 6),
        "wasmtime_throughput_rps_c2": round(tw, 3),
        "docker_throughput_rps_c2": round(td, 3),
        "wasmtime_dispatch_proxy_us": round(dw_proxy, 6),
        "docker_dispatch_proxy_us": round(dd_proxy, 6),
        "illustrative_crossover_kernel_us":
            round(crossover, 6) if math.isfinite(crossover) else "",
    })

output = OUT / "wp4_compute_crossover_initial.csv"

with output.open("w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=rows[0].keys())
    writer.writeheader()
    writer.writerows(rows)

print("\nWP4 INITIAL COMPUTE CROSSOVER ANALYSIS")
print("=" * 100)
print(
    f"{'MODEL':22} {'WASM KERNEL':>13} "
    f"{'DOCKER KERNEL':>15} {'SLOWDOWN':>12} "
    f"{'WASM P95':>12} {'DOCKER P95':>12}"
)

for r in rows:
    print(
        f"{r['model']:22} "
        f"{r['wasmtime_kernel_us']:13.3f} "
        f"{r['docker_kernel_us']:15.3f} "
        f"{r['kernel_slowdown_wasm_over_docker']:12.3f} "
        f"{r['wasmtime_p95_ms_c2']:12.3f} "
        f"{r['docker_p95_ms_c2']:12.3f}"
    )

print(f"\nSaved: {output}")
print("Kernel values: microseconds")
print("P95 values: milliseconds")
print("Crossover values are exploratory estimates, not validated boundaries.")
