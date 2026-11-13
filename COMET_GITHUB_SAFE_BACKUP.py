#!/usr/bin/env python3
import subprocess
from pathlib import Path

ROOT = Path("/home/sallar/wasiMultitenant")
MAX_BYTES = 5 * 1024 * 1024

allowed_suffixes = {
    ".py", ".sh", ".md", ".txt",
    ".csv", ".json", ".toml", ".yaml", ".yml"
}

excluded_parts = {
    "target", "cargo_target", ".venv",
    "__pycache__", "node_modules", ".git",
    "recovery_backup_20261113"
}

excluded_names = {
    "state.json.writing",
}

result = subprocess.check_output(
    ["git", "ls-files", "--others", "--exclude-standard", "-z"],
    cwd=ROOT
)

selected = []
skipped = 0

for raw in result.split(b"\0"):
    if not raw:
        continue

    relative = raw.decode("utf-8", errors="surrogateescape")
    path = ROOT / relative

    if not path.is_file() or path.is_symlink():
        continue

    if any(part in excluded_parts for part in path.parts):
        continue

    if path.name in excluded_names:
        continue

    if path.name.endswith((".requests.jsonl", ".lock", ".log")):
        continue

    if path.suffix.lower() not in allowed_suffixes:
        continue

    if path.stat().st_size > MAX_BYTES:
        skipped += 1
        continue

    selected.append(relative)

print("Candidate files:", len(selected))
print("Skipped oversized files:", skipped)
print("Combined candidate size (MiB):",
      round(sum((ROOT / p).stat().st_size for p in selected) / 1048576, 2))

print("\nFirst 35 candidates:")
for name in selected[:35]:
    print(" ", name)

# Stage only after selecting files.
if selected:
    subprocess.run(
        ["git", "add", "--", *selected],
        cwd=ROOT,
        check=True
    )

print("\nSTAGED. Review changes before committing.")
