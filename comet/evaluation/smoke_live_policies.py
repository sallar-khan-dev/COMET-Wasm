import json
import subprocess
import tempfile
from pathlib import Path

from comet.evaluation.live_backend import (
    CLIENT_CPUSET,
    ROOT,
    LiveBackendPair,
)


MODEL = "logistic_regression"

POLICIES = [
    "comet",
    "wasmtime_only",
    "docker_only",
    "random",
    "best_static",
]


with LiveBackendPair(
    MODEL,
    physical_units=20,
):

    results = []

    for policy in POLICIES:

        with tempfile.NamedTemporaryFile(
            suffix=".json",
            delete=False,
        ) as tmp:
            output = Path(
                tmp.name
            )

        try:

            cmd = [
                "taskset",
                "-c",
                CLIENT_CPUSET,

                str(
                    ROOT
                    / ".venv"
                    / "bin"
                    / "python"
                ),

                "-m",
                "comet.evaluation.live_client",

                "--model",
                MODEL,

                "--policy",
                policy,

                "--concurrency",
                "24",

                "--tenants",
                "20",

                "--physical-units",
                "20",

                "--requests",
                "200",

                "--seed",
                "42",

                "--output",
                str(output),
            ]

            proc = subprocess.run(
                cmd,
                cwd=ROOT,
                text=True,
                capture_output=True,
            )

            if proc.returncode != 0:
                raise RuntimeError(
                    f"{policy} failed\n"
                    f"STDOUT:\n{proc.stdout}\n"
                    f"STDERR:\n{proc.stderr}"
                )

            data = json.loads(
                output.read_text()
            )

            results.append(
                data
            )

            print(
                f"{policy:15s} "
                f"admission="
                f"{data['admission_rate']:.3f} "
                f"correct="
                f"{data['correctness_rate']:.3f} "
                f"backend="
                f"{data['backend_distribution']} "
                f"p95="
                f"{data['p95_latency_ms']:.3f} ms "
                f"rps="
                f"{data['throughput_rps']:.1f}"
            )

        finally:
            output.unlink(
                missing_ok=True
            )


assert len(results) == 5

for result in results:
    assert (
        result[
            "correctness_rate"
        ] == 1.0
    )

    assert (
        result[
            "admission_rate"
        ] == 1.0
    )


assert (
    results[0][
        "exact_operating_point"
    ]
    is False
)

assert (
    results[0][
        "scheduler_operating_concurrency"
    ]
    in {
        16,
        32,
    }
)


print()
print(
    "LIVE FIVE-POLICY ROUTING: PASS"
)
