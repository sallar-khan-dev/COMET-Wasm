import csv
import subprocess
import sys
import time
import uuid
from pathlib import Path

ROOT = Path("/home/sallar/wasiMultitenant")
sys.path.insert(0, str(ROOT))

from experiments.common.model_registry import get_model, supported_models

OUT = ROOT / "results/raw/tenant_admission"
OUT.mkdir(parents=True, exist_ok=True)

PROBE = ROOT / (
    "research_enhancement/wp3_kernel_admission/"
    "admission_probe/target/release/comet_admission_probe"
)

REPS = 20
WARMUP = 3

def run_command(args, timeout=60):
    return subprocess.run(
        args, check=True, capture_output=True,
        text=True, timeout=timeout
    )

def record(backend, model, rep, ns):
    path = OUT / f"{backend}_{model}_admission.csv"
    new = not path.exists()

    with path.open("a", newline="") as f:
        writer = csv.writer(f)
        if new:
            writer.writerow([
                "backend", "model", "repetition",
                "admission_ns", "timestamp_unix"
            ])
        writer.writerow([
            backend, model, rep, ns, time.time()
        ])

def wasm_trials(model, config):
    path = config["wasm_artifact_abs"]
    if not path.exists():
        raise FileNotFoundError(path)

    process = subprocess.Popen(
        [str(PROBE), str(path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1
    )

    try:
        if process.stdout.readline().strip() != "READY":
            raise RuntimeError("Wasmtime probe failed to initialize")

        for rep in range(-WARMUP, REPS):
            process.stdin.write("RUN\n")
            process.stdin.flush()

            response = process.stdout.readline().strip()
            if not response.startswith("OK,"):
                raise RuntimeError(f"Unexpected response: {response}")

            ns = int(response.split(",")[1])
            if rep >= 0:
                record("wasmtime", model, rep + 1, ns)
                print(f"Wasmtime {model} rep={rep+1}: {ns/1e6:.4f} ms", flush=True)
    finally:
        if process.poll() is None:
            process.stdin.write("STOP\n")
            process.stdin.flush()
            process.wait(timeout=10)

def docker_trials(model, config):
    image = config["docker_image"]
    run_command(["docker", "image", "inspect", image])

    for rep in range(-WARMUP, REPS):
        name = f"comet-admission-{uuid.uuid4().hex[:12]}"

        try:
            start = time.perf_counter_ns()

            run_command([
                "docker", "create",
                "--name", name,
                "--network", "none",
                image
            ])

            run_command(["docker", "start", name])

            run_command([
                "docker", "exec", name, "true"
            ], timeout=30)

            elapsed = time.perf_counter_ns() - start

            if rep >= 0:
                record("docker", model, rep + 1, elapsed)
                print(
                    f"Docker {model} rep={rep+1}: "
                    f"{elapsed/1e6:.4f} ms",
                    flush=True
                )
        finally:
            subprocess.run(
                ["docker", "rm", "-f", name],
                capture_output=True
            )

def main():
    if not PROBE.exists():
        raise RuntimeError(f"Probe binary missing: {PROBE}")

    for model in supported_models():
        config = get_model(model)
        print(f"\n=== {model} ===", flush=True)
        wasm_trials(model, config)
        docker_trials(model, config)

    print("\nADMISSION EXPERIMENT COMPLETED", flush=True)

if __name__ == "__main__":
    main()
