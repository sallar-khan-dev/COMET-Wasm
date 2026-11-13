#!/usr/bin/env bash
set -euo pipefail
cd /home/sallar/wasiMultitenant

ROOT="$PWD/research_enhancement/automated_supervisor_workplan/wp1_five_model_formal"
RESULTS="$ROOT/20261112_231004_2309146"
BUILD="$ROOT/20261112_230658_2309146"
FAILED="$ROOT/20261113_recovery_prepare_1/cargo_target"
ORIGINAL="$BUILD/cargo_target/release/comet_common_ingress"
RECOVERY="COMET_WP1_Resume_20261113.py"
SESSION="comet_wp1_resume"

if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "SAFE STOP: Recovery tmux session already exists."
    exit 1
fi

test -f "$RESULTS/state.json"
test -x "$ORIGINAL"
test -f "$BUILD/gateway_isolated/src/main.rs"

echo "=== VALIDATE ORIGINAL GATEWAY ==="
.venv/bin/python - <<'PY'
import json, hashlib, re
from pathlib import Path

root = Path("research_enhancement/automated_supervisor_workplan/wp1_five_model_formal")
results = root / "20261112_231004_2309146"
build = root / "20261112_230658_2309146"
binary = build / "cargo_target/release/comet_common_ingress"

state = json.loads((results / "state.json").read_text())
expected = state["config"]["ingress_sha256"]
actual = hashlib.sha256(binary.read_bytes()).hexdigest()

assert actual == expected, "SAFE STOP: Gateway binary fingerprint mismatch"
assert len(state["WP1"]["runs"]) == 1127, "SAFE STOP: Checkpoint has changed"

source = (build / "gateway_isolated/src/main.rs").read_text()
match = re.search(
    r"SocketAddr::from\(\(\[127,\s*0,\s*0,\s*1\],\s*(\d+)\)\)",
    source
)
assert match, "SAFE STOP: Cannot determine original gateway port"

print("Gateway SHA256 verified")
print("Original gateway port:", match.group(1))
print("Saved repetitions:", len(state["WP1"]["runs"]))
PY

echo "=== CLEAN UP ORPHANED GATEWAY ==="
PID=2407152
if [ -d "/proc/$PID" ]; then
    CMD=$(tr '\0' ' ' < "/proc/$PID/cmdline")
    case "$CMD" in
        "$ORIGINAL"*)
            echo "Stopping verified orphaned gateway PID $PID"
            kill "$PID"
            ;;
        *)
            echo "SAFE STOP: PID $PID does not match original gateway"
            exit 1
            ;;
    esac
fi

sleep 2

if [ -d "/proc/$PID" ]; then
    echo "SAFE STOP: Old gateway process still exists"
    exit 1
fi

echo "=== REMOVE ONLY FAILED TEMPORARY CARGO BUILD ==="
if [ -d "$FAILED" ]; then
    rm -rf -- "$FAILED"
fi

echo "=== CREATE REUSE-BINARY RECOVERY LAUNCHER ==="
.venv/bin/python - <<'PY'
from pathlib import Path

p = Path("COMET_WP1_Resume_20261113.py")
s = p.read_text()

changes = [
    (
        "out=OUTROOT/'20261113_recovery_prepare_1'",
        "out=OUTROOT/'20261113_recovery_prepare_2'"
    ),
    (
        "gateway_port,docker_port=ports()",
        """import re
    original_source=(OUTROOT/'20261112_230658_2309146/gateway_isolated/src/main.rs').read_text()
    port_match=re.search(
        r'SocketAddr::from\\(\\(\\[127,\\s*0,\\s*0,\\s*1\\],\\s*(\\d+)\\)\\)',
        original_source)
    if not port_match:fail('Original gateway port unavailable')
    gateway_port=int(port_match.group(1))
    docker_port=ports()[1]"""
    ),
    (
        "gateway=corrected.corrected_build(None,mod,out,gateway_port)",
        """gateway=OUTROOT/'20261112_230658_2309146/cargo_target/release/comet_common_ingress'
    if not gateway.is_file():fail('Original gateway binary unavailable')
    if sha(gateway)!=json.loads(
        (OUTROOT/'20261112_231004_2309146/state.json').read_text()
    )['config']['ingress_sha256']:
        fail('Original gateway binary fingerprint mismatch')
    print('Reusing verified original gateway:',gateway,flush=True)"""
    )
]

for old, new in changes:
    if s.count(old) != 1:
        raise SystemExit("SAFE STOP: Unexpected launcher content: " + old)
    s = s.replace(old, new, 1)

assert "resume=OUTROOT/'20261112_231004_2309146'" in s

p.write_text(s)
print("Recovery launcher prepared")
PY

.venv/bin/python -m py_compile "$RECOVERY"

echo "=== START RESUMED CAMPAIGN INSIDE TMUX ==="
tmux new-session -d -s "$SESSION" \
  "cd /home/sallar/wasiMultitenant && \
   .venv/bin/python -u $RECOVERY \
   > COMET_WP1_Resume_20261113.log 2>&1"

echo "=== SESSION ==="
tmux ls

echo "Recovery launched. Check the log before switching off."
