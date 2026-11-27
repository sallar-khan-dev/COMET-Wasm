#!/usr/bin/env python3
"""COMET-Wasm WP4 §7: extend load generator IDs for existing scaled RF/SVM
models, preserve verification and 20-60 adaptive precision, resume checkpoint.
Run in existing tmux session. Does not change algorithms, scheduling or tracing.
"""
from pathlib import Path
import datetime as dt
import os
import shutil
import subprocess
import sys

ROOT = Path("/home/sallar/wasiMultitenant")
SRC = ROOT / "research_enhancement/v2_loadgen/src/main.rs"
MANIFEST = ROOT / "research_enhancement/v2_loadgen/Cargo.toml"
BINARY = ROOT / "research_enhancement/v2_loadgen/target/release/comet_v2_loadgen"
DRIVER = ROOT / "COMET_WP4_SCALED_RF_SVM_GATEWAY_20261126.py"
OLD = '"lr" | "nb" | "dt" | "kmeans" | "rf" | "svm" | "mlp"'
NEW = (
    '"lr" | "nb" | "dt" | "kmeans" | "rf" | "svm" | "mlp"'
    ' | "rf_trees_100" | "rf_trees_200" | "rf_trees_400"'
    ' | "svm_c_0p03" | "svm_c_0p1" | "svm_c_0p3"'
)
FEATURE_OLD = '"rf" | "svm" => 30,'
FEATURE_NEW = (
    '"rf" | "svm" | "rf_trees_100" | "rf_trees_200"'
    ' | "rf_trees_400" | "svm_c_0p03" | "svm_c_0p1"'
    ' | "svm_c_0p3" => 30,'
)

def run(*args, **kwargs):
    return subprocess.run([str(a) for a in args], cwd=ROOT, check=True, **kwargs)

def main():
    for p in (SRC, MANIFEST, BINARY, DRIVER):
        if not p.is_file():
            raise RuntimeError(f"Required existing file missing: {p}")
    code = SRC.read_text()
    changed = False
    if OLD in code and NEW not in code:
        if code.count(OLD) != 1:
            raise RuntimeError("Unexpected model allowlist: refusing patch")
        code = code.replace(OLD, NEW, 1)
        changed = True
    elif NEW not in code:
        raise RuntimeError("Unknown model allowlist: refusing patch")
    if FEATURE_OLD in code and FEATURE_NEW not in code:
        if code.count(FEATURE_OLD) != 1:
            raise RuntimeError("Unexpected feature-check logic: refusing patch")
        code = code.replace(FEATURE_OLD, FEATURE_NEW, 1)
        changed = True
    elif FEATURE_NEW not in code:
        raise RuntimeError("Unknown feature-check logic: refusing patch")
    if changed:
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup = SRC.with_name(f"main.rs.pre_wp4_scaled_{stamp}.bak")
        backup.write_text(SRC.read_text())
        SRC.write_text(code)
        print("Saved loadgen source backup:", backup, flush=True)
    else:
        print("Loadgen already supports scaled RF/SVM models", flush=True)
    # Preserve existing release binary in case build fails.
    oldbin = BINARY.with_name(BINARY.name + ".pre_wp4_scaled")
    if not oldbin.exists():
        shutil.copy2(BINARY, oldbin)
    env = os.environ.copy()
    env["CARGO_TARGET_DIR"] = str(BINARY.parents[1])
    print("Run loadgen tests (no experimental samples)...", flush=True)
    run("cargo", "test", "--manifest-path", MANIFEST, env=env)
    print("Rebuild exact Rust v2 open-loop loadgen...", flush=True)
    run("cargo", "build", "--release", "--manifest-path", MANIFEST, env=env)
    print("RESUME WP4 scaled RF/SVM gateway experiment (same 20-60 precision)", flush=True)
    run(ROOT/".venv/bin/python", "-u", DRIVER)
    print("WP4 scaled RF/SVM serving experiment complete.", flush=True)

if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print("SAFE STOP:", exc, file=sys.stderr, flush=True)
        sys.exit(2)
