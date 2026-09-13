import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

DEFAULT_PROBE = (
    ROOT
    / "comet"
    / "tools"
    / "wasm_probe"
    / "target"
    / "release"
    / "comet-wasm-probe"
)


class WasmProbeError(RuntimeError):
    pass


def probe_wasm(
    artifact,
    probe_binary=DEFAULT_PROBE,
):
    artifact = Path(artifact)

    if not artifact.is_absolute():
        artifact = ROOT / artifact

    probe_binary = Path(probe_binary)

    if not probe_binary.exists():
        raise WasmProbeError(
            "COMET Wasm probe binary not found: "
            f"{probe_binary}. "
            "Build it with: "
            "cd comet/tools/wasm_probe && "
            "cargo build --release"
        )

    if not artifact.exists():
        raise WasmProbeError(
            f"Wasm artifact not found: {artifact}"
        )

    proc = subprocess.run(
        [
            str(probe_binary),
            str(artifact),
        ],
        capture_output=True,
        text=True,
    )

    if proc.returncode != 0:
        raise WasmProbeError(
            proc.stderr.strip()
            or "COMET Wasm probe failed"
        )

    try:
        result = json.loads(
            proc.stdout
        )
    except json.JSONDecodeError as exc:
        raise WasmProbeError(
            "Invalid JSON returned by "
            "COMET Wasm probe"
        ) from exc

    return result
