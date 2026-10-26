import json
import hashlib
import os
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

ROOT = Path("/home/sallar/wasiMultitenant")
GOLDEN = ROOT / "research_enhancement/v2_references/rf_breast_cancer_golden_v1.json"
REPORT = ROOT / "research_enhancement/v2_parity/RF_DOCKER_PARITY_REPORT.json"

IMAGE = "comet-rf-docker:v1"
NAME = f"comet_rf_parity_{os.getpid()}"
PORT = 18085

def docker(*args):
    return subprocess.run(
        ["docker", *args],
        text=True,
        capture_output=True,
        check=True
    )

def infer(features):
    payload = json.dumps({"features": features}).encode()
    request = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/infer",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.load(response)

def port_available():
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", PORT))
            return True
        except OSError:
            return False

def main():
    if not port_available():
        raise RuntimeError(f"Port {PORT} is occupied. No container started.")

    golden_bytes = GOLDEN.read_bytes()
    golden = json.loads(golden_bytes)
    records = golden["records"]

    assert len(records) == 569
    assert all(len(r["features"]) == 30 for r in records)

    docker("image", "inspect", IMAGE)

    started = False
    try:
        docker(
            "run", "-d",
            "--name", NAME,
            "--publish", f"127.0.0.1:{PORT}:8085",
            IMAGE
        )
        started = True

        for attempt in range(40):
            try:
                infer(records[0]["features"])
                break
            except Exception:
                if attempt == 39:
                    raise RuntimeError("RF Docker server did not become ready")
                time.sleep(0.25)

        mismatches = []
        errors = []
        matched = 0

        for record in records:
            try:
                response = infer(record["features"])
                actual = response["prediction"]
                expected = record["prediction"]

                if actual == expected:
                    matched += 1
                else:
                    mismatches.append({
                        "id": record["id"],
                        "expected": expected,
                        "actual": actual
                    })
            except Exception as exc:
                errors.append({
                    "id": record["id"],
                    "error": str(exc)
                })

        passed = matched == len(records) and not mismatches and not errors

        report = {
            "model": "RandomForestPacked",
            "backend": "docker",
            "image": IMAGE,
            "golden_sha256": hashlib.sha256(golden_bytes).hexdigest(),
            "total": len(records),
            "matched": matched,
            "mismatched": len(mismatches),
            "errors": len(errors),
            "status": "PASS" if passed else "FAIL",
            "mismatch_details": mismatches,
            "error_details": errors
        }

        REPORT.write_text(json.dumps(report, indent=2) + "\n")

        print("\n====================================")
        print("RF DOCKER PARITY")
        print("====================================")
        print("Records:", len(records))
        print("Matched:", matched)
        print("Mismatches:", len(mismatches))
        print("Errors:", len(errors))
        print("Status:", report["status"])
        print("Report:", REPORT)

        if not passed:
            raise SystemExit(1)

    finally:
        if started:
            subprocess.run(
                ["docker", "rm", "-f", NAME],
                capture_output=True,
                text=True
            )

if __name__ == "__main__":
    main()
