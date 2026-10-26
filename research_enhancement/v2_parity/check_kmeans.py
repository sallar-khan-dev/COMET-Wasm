import json
import subprocess
from pathlib import Path

ROOT = Path.cwd()
GOLDEN = ROOT / "research_enhancement/v2_references/kmeans_iris_golden_v1.json"
WASM = ROOT / "wasm/tenant_kmeans_real/target/wasm32-unknown-unknown/release/tenant_kmeans_real.wasm"

assert GOLDEN.is_file(), "Missing golden reference"
assert WASM.is_file(), "Missing Wasm binary"

data = json.loads(GOLDEN.read_text())
assert len(data["records"]) == 150

print("Golden records:", len(data["records"]))
print("Wasm binary:", WASM)
print("Ready for runtime parity testing.")
