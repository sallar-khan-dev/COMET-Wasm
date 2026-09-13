import json
import signal
import subprocess
import time
import urllib.request
from pathlib import Path

from experiments.common.model_registry import (
    get_model,
)


ROOT = Path(__file__).resolve().parents[2]

SERVER = (
    ROOT
    / "serving"
    / "multitenant_server"
    / "target"
    / "release"
    / "comet_multitenant_server"
)

SERVER_CPUSET = ",".join(
    str(i)
    for i in range(0, 128, 2)
)

CLIENT_CPUSET = ",".join(
    str(i)
    for i in range(1, 128, 2)
)

WASMTIME_PORT = 8100
DOCKER_BASE_PORT = 8300


class LiveBackendPair:
    def __init__(
        self,
        model,
        physical_units=20,
    ):
        self.model = model
        self.physical_units = int(
            physical_units
        )

        if self.physical_units < 1:
            raise ValueError(
                "physical_units must be >= 1"
            )

        self.cfg = get_model(
            model
        )

        self.wasm_proc = None

        self.docker_prefix = (
            "comet-live-eval-"
            + model.replace("_", "-")
        )

    def _run(
        self,
        cmd,
        check=True,
    ):
        return subprocess.run(
            cmd,
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=check,
        )

    def _docker_name(
        self,
        index,
    ):
        return (
            f"{self.docker_prefix}-"
            f"{index}"
        )

    def _docker_port(
        self,
        index,
    ):
        return (
            DOCKER_BASE_PORT
            + index
        )

    def cleanup_docker(self):
        result = self._run(
            [
                "docker",
                "ps",
                "-aq",
                "--filter",
                (
                    "name="
                    + self.docker_prefix
                ),
            ],
            check=False,
        )

        ids = [
            line.strip()
            for line
            in result.stdout.splitlines()
            if line.strip()
        ]

        if ids:
            self._run(
                [
                    "docker",
                    "rm",
                    "-f",
                    *ids,
                ],
                check=False,
            )

    def start_wasmtime(self):
        if not SERVER.exists():
            raise RuntimeError(
                "Generic Wasmtime server "
                f"not built: {SERVER}"
            )

        self.wasm_proc = subprocess.Popen(
            [
                "taskset",
                "-c",
                SERVER_CPUSET,

                str(SERVER),

                self.model,

                str(
                    self.cfg[
                        "wasm_artifact_abs"
                    ]
                ),

                str(
                    self.physical_units
                ),

                str(
                    WASMTIME_PORT
                ),
            ],
            cwd=ROOT,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
        )

        deadline = time.time() + 20

        while time.time() < deadline:

            if (
                self.wasm_proc.poll()
                is not None
            ):
                raise RuntimeError(
                    "Wasmtime server exited"
                )

            try:
                with urllib.request.urlopen(
                    (
                        "http://127.0.0.1:"
                        f"{WASMTIME_PORT}/health"
                    ),
                    timeout=1,
                ) as response:

                    if response.status == 200:
                        return

            except Exception:
                pass

            time.sleep(0.05)

        raise RuntimeError(
            "Wasmtime readiness timeout"
        )

    def start_docker(self):
        self.cleanup_docker()

        image = self.cfg[
            "docker_image"
        ]

        for i in range(
            self.physical_units
        ):
            result = self._run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--rm",

                    "--cpuset-cpus",
                    SERVER_CPUSET,

                    "--name",
                    self._docker_name(i),

                    "-p",
                    (
                        f"{self._docker_port(i)}:"
                        "8085"
                    ),

                    image,
                ],
                check=False,
            )

            if result.returncode != 0:
                self.cleanup_docker()

                raise RuntimeError(
                    result.stderr
                )

        pending = set(
            range(
                self.physical_units
            )
        )

        features = [
            0.0
        ] * int(
            self.cfg["features"]
        )

        deadline = time.time() + 30

        while (
            pending
            and time.time() < deadline
        ):
            ready = []

            for i in pending:
                try:
                    body = json.dumps({
                        "features": features
                    }).encode()

                    req = urllib.request.Request(
                        (
                            "http://127.0.0.1:"
                            f"{self._docker_port(i)}"
                            "/infer"
                        ),
                        data=body,
                        headers={
                            "Content-Type":
                                "application/json"
                        },
                        method="POST",
                    )

                    with urllib.request.urlopen(
                        req,
                        timeout=1,
                    ) as response:

                        if response.status == 200:
                            ready.append(i)

                except Exception:
                    pass

            for i in ready:
                pending.remove(i)

            if pending:
                time.sleep(0.05)

        if pending:
            self.cleanup_docker()

            raise RuntimeError(
                "Docker readiness timeout; "
                f"pending={sorted(pending)}"
            )

    def stop_wasmtime(self):
        if self.wasm_proc is None:
            return

        if self.wasm_proc.poll() is None:

            self.wasm_proc.send_signal(
                signal.SIGTERM
            )

            try:
                self.wasm_proc.wait(
                    timeout=5
                )

            except subprocess.TimeoutExpired:
                self.wasm_proc.kill()
                self.wasm_proc.wait()

        self.wasm_proc = None

    def start(self):
        try:
            self.start_wasmtime()
            self.start_docker()

        except Exception:
            self.stop()
            raise

    def stop(self):
        self.stop_wasmtime()
        self.cleanup_docker()

    def __enter__(self):
        self.start()
        return self

    def __exit__(
        self,
        exc_type,
        exc,
        tb,
    ):
        self.stop()
