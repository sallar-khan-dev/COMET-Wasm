#!/usr/bin/env python3

import subprocess
from pathlib import Path

ROOT = Path("/home/sallar/wasiMultitenant")
MAX_BYTES = 5 * 1024 * 1024

allowed = {".py", ".sh", ".md", ".txt", ".json", ".csv", ".toml"}
excluded_parts = {
    ".git", ".venv", "target", "cargo_target",
    "__pycache__", "recovery_backup_20261113"
}

selected = []

raw = subprocess.check_output(
    ["git", "ls-files", "--others", "--exclude-standard", "-z"],
    cwd=ROOT
)

for item in raw.split(b"\0"):
    if not item:
        continue

    relative = item.decode("utf-8", errors="surrogateescape")
    path = ROOT / relative

    if not path.is_file() or path.is_symlink():
        continue

    if any(part in excluded_parts for part in Path(relative).parts):
        continue

    if path.stat().st_size > MAX_BYTES:
        continue

    if path.suffix.lower() not in allowed:
        continue

    name = path.name.lower()

    if name.endswith((
        ".requests.jsonl", ".log", ".lock",
        ".summary.json", ".resources.json"
    )):
        continue

    if "_rep" in name or name.startswith("rps"):
        continue

    # Stage scripts and concise reports only.
    if (
        relative.startswith("COMET_")
        or relative.startswith("WP4_")
        or relative.startswith("comet_wp1_")
        or name in {"state.json", "report.md"}
        or name.endswith((
            "_review.json", "_review.md",
            "_manifest.json", "_summary.csv",
            "_summary.json", "_report.csv", "_report.md"
        ))
        or (
            relative.startswith("research_enhancement/")
            and path.suffix.lower() in {".py", ".sh", ".toml"}
            and "/generated/" not in relative
        )
    ):
        selected.append(relative)

selected = sorted(set(selected))

print("Selected research files:", len(selected))
print("Total size (MB):", round(
    sum((ROOT / p).stat().st_size for p in selected) / 1048576, 2
))

if selected:
    subprocess.run(
        ["git", "add", "--", *selected],
        cwd=ROOT,
        check=True
    )

print("Curated research files staged.")
