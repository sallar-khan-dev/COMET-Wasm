import csv
import math
import statistics
import subprocess
import time
from pathlib import Path

ROOT = Path("/home/sallar/wasiMultitenant")
RAW = ROOT / "results/raw/tenant_admission"
PROBE = ROOT / (
    "research_enhancement/wp3_kernel_admission/"
    "admission_probe/target/release/comet_admission_probe"
)

MODELS = [
    "decision_tree",
    "kmeans",
    "logistic_regression",
    "mlp",
    "naive_bayes",
    "random_forest",
    "svm",
]

TARGET = 0.025
MAX_REPS = 200
BATCH = 10
WARMUP = 3

import sys
sys.path.insert(0, str(ROOT / "experiments/common"))
from model_registry import get_model

def read_csv(path):
    if not path.exists():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))

def relative_ci(values):
    n = len(values)
    if n < 2:
        return float("inf")
    mean = statistics.mean(values)
    if mean <= 0:
        return float("inf")
    sd = statistics.stdev(values)
    # Conservative critical value for all n >= 20.
    half_width = 2.093 * sd / math.sqrt(n)
    return half_width / mean

if not PROBE.is_file():
    raise SystemExit(f"Missing compiled probe: {PROBE}")

for model in MODELS:
    baseline_path = RAW / f"wasmtime_{model}_admission.csv"
    extension_path = RAW / f"wasmtime_{model}_admission_extension.csv"

    baseline = read_csv(baseline_path)
    if len(baseline) != 20:
        raise RuntimeError(
            f"{model}: expected 20 baseline measurements, "
            f"found {len(baseline)}"
        )

    previous = read_csv(extension_path)
    values = [
        int(r["admission_ns"])
        for r in baseline + previous
    ]

    print(
        f"\n=== {model} === "
        f"existing={len(values)}, "
        f"relative_CI={relative_ci(values)*100:.3f}%",
        flush=True,
    )

    if relative_ci(values) <= TARGET:
        print("Already meets target; skipping.", flush=True)
        continue

    artifact = Path(get_model(model)["wasm_artifact_abs"])
    if not artifact.is_file():
        raise RuntimeError(f"Missing Wasm artifact: {artifact}")

    with subprocess.Popen(
        [str(PROBE), str(artifact)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    ) as proc:

        ready = proc.stdout.readline().strip()
        if ready != "READY":
            raise RuntimeError(
                f"{model}: unexpected probe response: {ready!r}"
            )

        def run_probe():
            proc.stdin.write("RUN\n")
            proc.stdin.flush()
            response = proc.stdout.readline().strip()
            if not response.startswith("OK,"):
                raise RuntimeError(
                    f"{model}: unexpected response: {response!r}"
                )
            return int(response.split(",", 1)[1])

        for _ in range(WARMUP):
            run_probe()

        with extension_path.open("a", newline="") as f:
            writer = csv.writer(f)
            if extension_path.stat().st_size == 0:
                writer.writerow([
                    "backend",
                    "model",
                    "repetition",
                    "admission_ns",
                    "timestamp_unix",
                ])

            while len(values) < MAX_REPS:
                for _ in range(min(BATCH, MAX_REPS - len(values))):
                    ns = run_probe()
                    values.append(ns)
                    writer.writerow([
                        "wasmtime",
                        model,
                        len(values),
                        ns,
                        time.time(),
                    ])
                    f.flush()

                ci = relative_ci(values)
                print(
                    f"{model}: n={len(values)}, "
                    f"mean={statistics.mean(values)/1000:.4f} us, "
                    f"relative_95CI={ci*100:.3f}%",
                    flush=True,
                )

                if ci <= TARGET:
                    print(f"{model}: PRECISION TARGET MET", flush=True)
                    break

        proc.stdin.write("STOP\n")
        proc.stdin.flush()
        proc.wait(timeout=10)

    if relative_ci(values) > TARGET:
        print(
            f"{model}: MAXIMUM REPETITIONS REACHED; "
            "precision target not met",
            flush=True,
        )

print("\nWASMTIME PRECISION EXTENSION FINISHED", flush=True)
