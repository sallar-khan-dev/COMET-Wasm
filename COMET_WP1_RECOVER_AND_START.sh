#!/usr/bin/env bash
set -euo pipefail

cd /home/sallar/wasiMultitenant

ROOT="$PWD/research_enhancement/automated_supervisor_workplan/wp1_five_model_formal"
BUILD="$ROOT/20261112_230658_2309146"
RESULTS="$ROOT/20261112_231004_2309146"
BACKUP="$RESULTS/recovery_backup_20261113"
SESSION="comet_wp1_resume"

# Prevent a duplicate campaign.
if pgrep -f '[p]ython.*COMET_WP1_.*Formal.py' >/dev/null; then
    echo "SAFE STOP: Another formal launcher may be running."
    exit 1
fi

if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "Existing recovery session found."
    tmux attach -t "$SESSION"
    exit 0
fi

test -f "$RESULTS/state.json"
test -d "$BUILD"

mkdir -p "$BACKUP/interrupted_rep4"

# Back up original checkpoint.
cp -pn "$RESULTS/state.json" "$BACKUP/state_before_resume.json"

# Verify checkpoint and isolate only the interrupted repetition.
RESULTS="$RESULTS" BACKUP="$BACKUP" .venv/bin/python - <<'PY'
import json
import os
import shutil
from pathlib import Path

out = Path(os.environ["RESULTS"])
backup = Path(os.environ["BACKUP"])
state = json.loads((out / "state.json").read_text())
runs = state["WP1"]["runs"]

assert len(runs) == 1127, (
    f"SAFE STOP: expected 1127 saved runs, found {len(runs)}"
)

matches = [
    r for r in runs
    if r["model"] == "kmeans"
    and r["backend"] == "wasmtime"
    and r["offered_rps"] == 1200
    and r["repeat"] == 4
]

assert not matches, "SAFE STOP: interrupted repetition already indexed"

folder = out / "kmeans_wasmtime"
target = backup / "interrupted_rep4"

for src in folder.glob("rps1200_rep4.*"):
    dst = target / src.name
    assert not dst.exists(), f"SAFE STOP: backup already exists: {dst}"
    shutil.move(str(src), str(dst))

print("CHECKPOINT PROTECTED:", len(runs), "saved repetitions")
print("INTERRUPTED REPETITION: isolated safely")
PY

# Create a recovery-only copy of the existing five-model launcher.
.venv/bin/python - <<'PY'
from pathlib import Path

original = Path("COMET_WP1_Remaining_Five_Formal.py")
recovery = Path("COMET_WP1_Resume_20261113.py")

source = original.read_text()

changes = [
    (
        "out=OUTROOT/(dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d_%H%M%S')+'_'+str(os.getpid()))",
        "out=OUTROOT/'20261112_230658_2309146'"
    ),
    (
        "out.mkdir(parents=True,exist_ok=False)",
        "if not out.is_dir():fail('Original build directory missing')"
    ),
    (
        "resume=None,resume_latest=False",
        "resume=OUTROOT/'20261112_231004_2309146',resume_latest=False"
    )
]

for old, new in changes:
    assert source.count(old) == 1, (
        f"SAFE STOP: expected exactly one occurrence of {old!r}"
    )
    source = source.replace(old, new, 1)

recovery.write_text(source)
print("Recovery launcher created:", recovery)
PY

.venv/bin/python -m py_compile COMET_WP1_Resume_20261113.py

# Run independently of the SSH connection.
tmux new-session -d -s "$SESSION" \
  "cd /home/sallar/wasiMultitenant && \
   .venv/bin/python -u COMET_WP1_Resume_20261113.py \
   2>&1 | tee COMET_WP1_Resume_20261113.log"

echo
echo "RECOVERY SESSION LAUNCHED."
echo "Session: $SESSION"
echo "Logs: COMET_WP1_Resume_20261113.log"
echo
echo "Attaching to the running session..."
tmux attach -t "$SESSION"
