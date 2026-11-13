#!/usr/bin/env bash
set -euo pipefail
cd /home/sallar/wasiMultitenant

ROOT="$PWD/research_enhancement/automated_supervisor_workplan/wp1_five_model_formal"
RESULTS="$ROOT/20261112_231004_2309146"
BACKUP="$RESULTS/recovery_backup_20261113/interrupted_rep29"
SESSION="comet_wp1_resume"
LAUNCHER="COMET_WP1_Resume_20261113.py"

echo "=== SAFETY CHECKS ==="

if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "SAFE STOP: Recovery session already exists"
    exit 1
fi

if pgrep -af '[c]omet_common_ingress|[C]OMET_WP1_Resume_20261113.py'; then
    echo "SAFE STOP: Check existing processes before restarting"
    exit 1
fi

test -f "$RESULTS/state.json"
test -f "$LAUNCHER"

.venv/bin/python - <<'PY'
import json, socket, hashlib
from pathlib import Path

root=Path("research_enhancement/automated_supervisor_workplan/wp1_five_model_formal")
out=root/"20261112_231004_2309146"
binary=root/"20261112_230658_2309146/cargo_target/release/comet_common_ingress"
state=json.loads((out/"state.json").read_text())

assert len(state["WP1"]["runs"])==1172, "Checkpoint changed"
assert hashlib.sha256(binary.read_bytes()).hexdigest()==state["config"]["ingress_sha256"], "Gateway mismatch"

with socket.socket() as s:
    try:
        s.bind(("127.0.0.1",58427))
    except OSError as e:
        raise SystemExit(f"SAFE STOP: gateway port occupied: {e}")

print("Checkpoint, original binary and gateway port verified")
PY

echo "=== BACKUP CHECKPOINT ==="
mkdir -p "$BACKUP"
cp -pn "$RESULTS/state.json" \
  "$RESULTS/recovery_backup_20261113/state_before_quota_recovery.json"

echo "=== ISOLATE INCOMPLETE REPETITION 29 ==="
.venv/bin/python - <<'PY'
import json, shutil
from pathlib import Path

root=Path("research_enhancement/automated_supervisor_workplan/wp1_five_model_formal")
out=root/"20261112_231004_2309146"
folder=out/"kmeans_wasmtime"
backup=out/"recovery_backup_20261113/interrupted_rep29"
runs=json.loads((out/"state.json").read_text())["WP1"]["runs"]

assert not any(
    r["model"]=="kmeans" and
    r["backend"]=="wasmtime" and
    r["offered_rps"]==2400 and
    r["repeat"]==29
    for r in runs
), "SAFE STOP: repetition 29 already indexed"

for f in folder.glob("rps2400_rep29.*"):
    dst=backup/f.name
    assert not dst.exists(), f"SAFE STOP: Backup exists: {dst}"
    shutil.move(str(f),str(dst))
    print("Preserved interrupted file:",f.name)

print("Existing 1,172 repetition records preserved")
PY

echo "=== PREPARE NEXT RECOVERY ==="
.venv/bin/python - <<'PY'
from pathlib import Path

p=Path("COMET_WP1_Resume_20261113.py")
s=p.read_text()
old="out=OUTROOT/'20261113_recovery_prepare_2'"
new="out=OUTROOT/'20261113_recovery_prepare_3'"

assert s.count(old)==1, "SAFE STOP: unexpected launcher version"
assert "resume=OUTROOT/'20261112_231004_2309146'" in s
assert "Reusing verified original gateway:" in s
assert not Path(
    "research_enhancement/automated_supervisor_workplan/"
    "wp1_five_model_formal/20261113_recovery_prepare_3"
).exists(), "SAFE STOP: preparation directory already exists"

p.write_text(s.replace(old,new,1))
print("Launcher ready; original experiment directory unchanged")
PY

.venv/bin/python -m py_compile "$LAUNCHER"

echo "=== START IN PERSISTENT TMUX ==="
tmux new-session -d -s "$SESSION" \
  "cd /home/sallar/wasiMultitenant && \
   exec .venv/bin/python -u $LAUNCHER \
   > COMET_WP1_Resume_20261113.log 2>&1"

echo "=== TMUX SESSION ==="
tmux ls

echo "Recovery started. Verify the log before disconnecting."
