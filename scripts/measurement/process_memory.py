#!/usr/bin/env python3

import json
import sys
from pathlib import Path

def parse_smaps_rollup(pid):
    path = Path(f"/proc/{pid}/smaps_rollup")

    if not path.exists():
        raise RuntimeError(f"Cannot access {path}")

    values = {}

    for line in path.read_text().splitlines():
        parts = line.split()

        if len(parts) >= 2 and parts[0].endswith(":"):
            key = parts[0][:-1]

            try:
                values[key] = int(parts[1])
            except ValueError:
                pass

    return values


if len(sys.argv) != 2:
    print(f"Usage: {sys.argv[0]} PID")
    raise SystemExit(1)

pid = int(sys.argv[1])
values = parse_smaps_rollup(pid)

result = {
    "pid": pid,
    "rss_kib": values.get("Rss", 0),
    "pss_kib": values.get("Pss", 0),
    "private_clean_kib": values.get("Private_Clean", 0),
    "private_dirty_kib": values.get("Private_Dirty", 0),
    "shared_clean_kib": values.get("Shared_Clean", 0),
    "shared_dirty_kib": values.get("Shared_Dirty", 0),
}

result["rss_mib"] = result["rss_kib"] / 1024.0
result["pss_mib"] = result["pss_kib"] / 1024.0

print(json.dumps(result, indent=2))
