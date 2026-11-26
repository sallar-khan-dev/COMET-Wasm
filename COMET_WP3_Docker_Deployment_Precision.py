import csv, json, math, os, subprocess, sys, time, uuid
import urllib.request, urllib.error
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from scipy.stats import t

ROOT = Path("/home/sallar/wasiMultitenant")
BASE = ROOT / "research_enhancement/automated_supervisor_workplan/wp3_docker_deployment"
IMAGE = "comet-wp1cap-lr:latest"
GOLDEN = ROOT / "research_enhancement/v2_references/lr_iris_golden_v1.json"
CPU = min(os.sched_getaffinity(0))
MIN_REPS, MAX_REPS, STEP = 20, 120, 5

def cmd(args, timeout=40):
    p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    if p.returncode:
        raise RuntimeError(f"{args[0]} failed: {(p.stderr or p.stdout)[-500:]}")
    return p.stdout.strip()

image_id = cmd(["docker", "image", "inspect", IMAGE, "-f", "{{.Id}}"])
record = json.loads(GOLDEN.read_text())["records"][0]
features = record["features"]
expected = record["expected_prediction"]

out = BASE / datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
out.mkdir(parents=True, exist_ok=False)

manifest = {
    "work_package": "WP3 Section 6.2",
    "experiment": "Docker cold deployment to correct HTTP inference",
    "image_id_frozen": image_id,
    "image_tag_at_start": IMAGE,
    "network": "bridge",
    "backend_cpu": CPU,
    "minimum_repetitions": MIN_REPS,
    "maximum_repetitions": MAX_REPS,
    "confidence": 0.95,
    "student_t_and_bootstrap_target_pct": 2.5,
    "bootstrap_resamples": 5000,
    "historical_image_data_pooled": False,
    "scope": "docker run through successful POST /infer; not warm admission"
}
(out / "manifest.json").write_text(json.dumps(manifest, indent=2))

rows = []

def trial(rep):
    name = f"comet_wp3_deploy_{uuid.uuid4().hex[:12]}"
    t0 = time.perf_counter_ns()
    try:
        cmd([
            "docker", "run", "-d", "--name", name,
            "--network", "bridge",
            "--cpuset-cpus", str(CPU),
            "-p", "127.0.0.1::8085", image_id
        ], timeout=60)

        port = cmd(["docker", "port", name, "8085/tcp"]).rsplit(":", 1)[-1]
        url = f"http://127.0.0.1:{port}/infer"
        payload = json.dumps({"features": features}).encode()
        deadline = time.monotonic() + 25

        while time.monotonic() < deadline:
            try:
                req = urllib.request.Request(
                    url, payload,
                    {"Content-Type": "application/json"},
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=0.7) as response:
                    result = json.loads(response.read())
                if result.get("prediction") != expected:
                    raise RuntimeError("Golden prediction mismatch")

                elapsed = (time.perf_counter_ns() - t0) / 1e6

                status = cmd([
                    "docker", "exec", name,
                    "cat", "/proc/1/status"
                ], timeout=15)
                observed = {}
                for line in status.splitlines():
                    if line.startswith(("Threads:", "Cpus_allowed_list:")):
                        key, value = line.split(":", 1)
                        observed[key] = value.strip()

                return {
                    "repetition": rep,
                    "elapsed_ms": elapsed,
                    "prediction_correct": True,
                    "threads": observed.get("Threads", "UNKNOWN"),
                    "cpu_allowed": observed.get("Cpus_allowed_list", "UNKNOWN")
                }
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                time.sleep(0.04)

        raise RuntimeError("Docker readiness deadline exceeded")
    finally:
        subprocess.run(
            ["docker", "rm", "-f", name],
            capture_output=True, timeout=30
        )

def precision():
    x = np.array([r["elapsed_ms"] for r in rows], dtype=float)
    n = len(x)
    avg = float(x.mean())
    th = float(t.ppf(.975, n-1) * x.std(ddof=1) / math.sqrt(n))
    rng = np.random.default_rng(20261121 + n)
    boot = x[rng.integers(0, n, size=(5000, n))].mean(axis=1)
    bh = float(np.diff(np.quantile(boot, [.025, .975]))[0] / 2)
    return {
        "n": n,
        "mean_ms": avg,
        "student_t_relative_halfwidth_pct": 100*th/avg,
        "bootstrap_relative_halfwidth_pct": 100*bh/avg,
        "accepted": max(th, bh)/avg <= 0.025
    }

print("WP3 DOCKER DEPLOYMENT STARTED", flush=True)
print("FROZEN IMAGE:", image_id, flush=True)
print("RESULTS:", out, flush=True)

for rep in range(1, MAX_REPS+1):
    try:
        rows.append(trial(rep))
    except Exception as exc:
        (out / "FAILURE.txt").write_text(
            f"Repetition {rep}: {exc}\n"
        )
        raise

    with (out / "trials.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    if rep >= MIN_REPS and (rep-MIN_REPS) % STEP == 0:
        result = precision()
        (out / "RESULT.json").write_text(json.dumps(result, indent=2))
        print(
            f"RUNS={rep} "
            f"Student-t={result['student_t_relative_halfwidth_pct']:.3f}% "
            f"Bootstrap={result['bootstrap_relative_halfwidth_pct']:.3f}% "
            f"ACCEPTED={result['accepted']}",
            flush=True
        )
        if result["accepted"]:
            break

result = precision()
result["status"] = (
    "PRECISION_ACCEPTED" if result["accepted"]
    else "PRECISION_NOT_MET"
)
(out / "RESULT.json").write_text(json.dumps(result, indent=2) + "\n")

print("FINAL:", result["status"], flush=True)
print("REPORT:", out / "RESULT.json", flush=True)
