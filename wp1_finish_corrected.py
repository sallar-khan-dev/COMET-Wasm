from pathlib import Path
import subprocess, json, sys, datetime

root = Path("/home/sallar/wasiMultitenant")
pilot_root = root / "research_enhancement/wp1_rf_svm_pilot_runs"
rf = root / "docker/rf_server"
bundle = root / "COMET_Auto_Workplan_v4_BUNDLED.py"
logdir = root / "research_enhancement/wp1_final_execution"
logdir.mkdir(parents=True, exist_ok=True)

def stage(name, args, cwd=root):
    print(f"\n=== {name} ===", flush=True)
    log = logdir / (name.replace(" ", "_") + ".log")
    with log.open("w") as f:
        result = subprocess.run(args, cwd=cwd, stdout=f,
                                stderr=subprocess.STDOUT)
    if result.returncode:
        print(f"FAILED: {name}", flush=True)
        print(f"LOG: {log}", flush=True)
        print("\n".join(log.read_text(errors="replace").splitlines()[-25:]),
              flush=True)
        raise RuntimeError(name)
    print(f"PASS: {name}", flush=True)

try:
    # Avoid two overlapping campaigns.
    lock = logdir / "execution.lock"
    import fcntl
    lockfile = lock.open("a+")
    fcntl.flock(lockfile.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    # Reproducible replacement RF image.
    if not (rf / "Cargo.lock").exists():
        stage("RF dependency lock", ["cargo", "generate-lockfile"], rf)

    dockerfile = rf / "Dockerfile"
    source = dockerfile.read_text()
    if "RUN cargo build --release --locked" not in source:
        assert source.count("RUN cargo build --release") == 1
        dockerfile.write_text(
            source.replace("RUN cargo build --release",
                           "RUN cargo build --release --locked")
        )

    assert "worker_threads = 1" in (rf / "src/main.rs").read_text()

    stage("RF locked local build",
          ["cargo", "build", "--release", "--locked"], rf)

    stage("RF corrected Docker image",
          ["docker", "build", "-t", "comet-wp1-rf:latest",
           str(rf)], root)

    # Validate the new image through the established RF/SVM golden pilot.
    before = set(p.parent for p in pilot_root.glob("*/FINAL_GATE.json"))

    stage("Fresh RF SVM golden pilot", [
        sys.executable,
        "COMET_WP1_RF_SVM_Pilot_v2.py",
        "--rf-image", "comet-wp1-rf:latest",
        "--svm-image", "comet-wp1-svm:latest",
        "--requests", "1500",
        "--reps", "2",
        "--tenants", "3",
        "--rps", "50", "100", "300"
    ])

    after = set(p.parent for p in pilot_root.glob("*/FINAL_GATE.json"))
    fresh = list(after - before)
    assert len(fresh) == 1, "Fresh pilot directory not uniquely identified"
    pilot = fresh[0]
    gate = json.loads((pilot / "FINAL_GATE.json").read_text())

    assert gate["status"].startswith("PILOT PASS"), gate["status"]
    assert len(gate["runs"]) == 24
    print("NEW RF/SVM GOLDEN PILOT PASSED:", pilot, flush=True)

    # Point the existing formal campaign at the NEW validated pilot.
    old = (
        "PILOT=ROOT/"
        "'research_enhancement/wp1_rf_svm_pilot_runs/"
        "20261110_170246_710579'"
    )
    new = (
        "PILOT=ROOT/"
        f"'research_enhancement/wp1_rf_svm_pilot_runs/{pilot.name}'"
    )
    text = bundle.read_text()
    assert text.count(old) == 1, "Unexpected pilot reference; safe stop"

    provenance = {
        "new_treatment": True,
        "reason": "Historical RF Docker image no longer available",
        "replacement_pilot": str(pilot),
        "rf_image": gate["rf_image"],
        "rf_image_id": gate["rf_docker_image_id"],
        "validation_runs": len(gate["runs"]),
        "historical_results_pooled": False,
        "supervisor_approval": "PENDING"
    }

    (logdir / "replacement_rf_provenance.json").write_text(
        json.dumps(provenance, indent=2) + "\n"
    )

    bundle.write_text(text.replace(old, new))
    print("FORMAL RUNNER NOW REFERENCES VALIDATED RF PILOT", flush=True)

    # Run the actual corrected LR/RF formal campaign.
    print("\n=== STARTING CORRECTED LR/RF FORMAL WP1 ===", flush=True)
    import os
    env = os.environ.copy()
    env["COMET_LR_DOCKER_IMAGE"] = "comet-wp1-lr:latest"

    stage("Corrected LR RF formal campaign", [
        sys.executable, "-u",
        "COMET_WP1_One_Command_Parity_Corrected.py"
    ], root)

    print("\nFORMAL CAMPAIGN EXECUTION FINISHED", flush=True)
    print("Supervisor scientific acceptance still requires results review.",
          flush=True)

except Exception as error:
    print("\nWP1 EXECUTION BLOCKED:", str(error), flush=True)
    print("Existing experimental results preserved.", flush=True)
    raise
