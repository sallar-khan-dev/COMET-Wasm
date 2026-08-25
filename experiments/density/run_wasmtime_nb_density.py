#!/usr/bin/env python3

import csv
import json
import os
import signal
import statistics
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

SERVER = ROOT / "serving/multitenant_server/target/release/comet_multitenant_server"
WASM = ROOT / "wasm/tenant_nb_real/target/wasm32-unknown-unknown/release/tenant_nb_real.wasm"
DATA = ROOT / "models/naive_bayes/breast_cancer/test_samples.csv"

OUT_CSV = ROOT / "results/raw/density/wasmtime_nb_density_pilot.csv"
OUT_JSON = ROOT / "results/raw/density/wasmtime_nb_density_pilot.json"

PORT = 8100

# Pilot only. Full experiment will later include 50/100/200.
WORKER_COUNTS = [1, 5, 10, 20]

# Multiple clean process launches per worker count.
REPETITIONS = 5

# Keep warm-up intensity constant per physical worker.
REQUESTS_PER_WORKER = 100

# Multiple memory snapshots after warm-up.
MEMORY_SAMPLES = 5
MEMORY_SAMPLE_INTERVAL = 0.25


with DATA.open() as f:
    row = next(csv.DictReader(f))

FEATURES = [
    float(v)
    for k, v in row.items()
    if k != "label"
]


def wait_ready(timeout=20):
    deadline = time.time() + timeout

    while time.time() < deadline:
        try:
            with urllib.request.urlopen(
                f"http://localhost:{PORT}/health",
                timeout=1
            ) as r:
                if r.status == 200:
                    return
        except Exception:
            pass

        time.sleep(0.05)

    raise RuntimeError("Server did not become ready")


def infer(tenant_id):
    body = json.dumps({
        "tenant_id": tenant_id,
        "features": FEATURES
    }).encode()

    req = urllib.request.Request(
        f"http://localhost:{PORT}/infer",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def warm_workers(worker_count):
    for worker in range(worker_count):
        for _ in range(REQUESTS_PER_WORKER):
            result = infer(worker)

            if result["worker_id"] != worker:
                raise RuntimeError(
                    f"Worker mapping error: tenant={worker}, "
                    f"worker={result['worker_id']}"
                )


def memory(pid):
    path = Path(f"/proc/{pid}/smaps_rollup")

    values = {}

    for line in path.read_text().splitlines():
        parts = line.split()

        if len(parts) >= 2 and parts[0].endswith(":"):
            try:
                values[parts[0][:-1]] = int(parts[1])
            except ValueError:
                pass

    return {
        "rss_mib": values.get("Rss", 0) / 1024.0,
        "pss_mib": values.get("Pss", 0) / 1024.0,
        "private_mib": (
            values.get("Private_Clean", 0)
            + values.get("Private_Dirty", 0)
        ) / 1024.0,
    }


results = []

for workers in WORKER_COUNTS:

    print()
    print("=" * 60)
    print(f"WORKERS={workers}")
    print("=" * 60)

    for repetition in range(1, REPETITIONS + 1):

        proc = subprocess.Popen(
            [
                str(SERVER),
                "naive_bayes",
                str(WASM),
                str(workers),
                str(PORT),
            ],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )

        try:
            wait_ready()

            warm_workers(workers)

            rss_values = []
            pss_values = []
            private_values = []

            for _ in range(MEMORY_SAMPLES):
                m = memory(proc.pid)

                rss_values.append(m["rss_mib"])
                pss_values.append(m["pss_mib"])
                private_values.append(m["private_mib"])

                time.sleep(MEMORY_SAMPLE_INTERVAL)

            row = {
                "backend": "wasmtime",
                "model": "naive_bayes",
                "physical_workers": workers,
                "repetition": repetition,
                "warmup_requests_per_worker": REQUESTS_PER_WORKER,
                "rss_mib": statistics.mean(rss_values),
                "pss_mib": statistics.mean(pss_values),
                "private_mib": statistics.mean(private_values),
            }

            results.append(row)

            print(
                f"rep={repetition} "
                f"RSS={row['rss_mib']:.3f} MiB "
                f"PSS={row['pss_mib']:.3f} MiB "
                f"Private={row['private_mib']:.3f} MiB"
            )

        finally:
            proc.send_signal(signal.SIGTERM)

            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()

            time.sleep(0.5)


OUT_CSV.parent.mkdir(parents=True, exist_ok=True)

with OUT_CSV.open("w", newline="") as f:
    writer = csv.DictWriter(
        f,
        fieldnames=[
            "backend",
            "model",
            "physical_workers",
            "repetition",
            "warmup_requests_per_worker",
            "rss_mib",
            "pss_mib",
            "private_mib",
        ]
    )

    writer.writeheader()
    writer.writerows(results)


summary = {}

for workers in WORKER_COUNTS:

    rows = [
        r for r in results
        if r["physical_workers"] == workers
    ]

    summary[str(workers)] = {
        "n": len(rows),
        "rss_mean_mib": statistics.mean(
            r["rss_mib"] for r in rows
        ),
        "rss_sd_mib": statistics.stdev(
            r["rss_mib"] for r in rows
        ) if len(rows) > 1 else 0.0,
        "pss_mean_mib": statistics.mean(
            r["pss_mib"] for r in rows
        ),
        "pss_sd_mib": statistics.stdev(
            r["pss_mib"] for r in rows
        ) if len(rows) > 1 else 0.0,
        "private_mean_mib": statistics.mean(
            r["private_mib"] for r in rows
        ),
    }


OUT_JSON.write_text(
    json.dumps(summary, indent=2)
)

print()
print("=" * 60)
print("PILOT SUMMARY")
print("=" * 60)

for workers, s in summary.items():
    print(
        f"{workers:>3} workers | "
        f"RSS={s['rss_mean_mib']:.3f} MiB | "
        f"PSS={s['pss_mean_mib']:.3f} MiB | "
        f"SD(PSS)={s['pss_sd_mib']:.3f}"
    )

print()
print("CSV:", OUT_CSV)
print("JSON:", OUT_JSON)
print("WASMTIME NB DENSITY PILOT: COMPLETE")
