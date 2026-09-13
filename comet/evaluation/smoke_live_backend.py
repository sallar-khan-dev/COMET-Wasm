import csv
import json
import urllib.request

from comet.evaluation.live_backend import (
    DOCKER_BASE_PORT,
    WASMTIME_PORT,
    LiveBackendPair,
)
from experiments.common.model_registry import (
    get_model,
)


MODEL = "logistic_regression"
UNITS = 20

cfg = get_model(
    MODEL
)

with cfg["test_path_abs"].open(
    newline=""
) as f:
    row = next(
        csv.DictReader(f)
    )

features = [
    float(value)
    for key, value in row.items()
    if key.lower() not in {
        "label",
        "target",
        "class",
        "y",
        "expected",
        "prediction",
    }
]

expected = int(
    row["label"]
)


def post(url, body):
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={
            "Content-Type":
                "application/json"
        },
        method="POST",
    )

    with urllib.request.urlopen(
        request,
        timeout=5,
    ) as response:
        return json.loads(
            response.read()
        )


with LiveBackendPair(
    MODEL,
    UNITS,
):

    wasm = post(
        (
            "http://127.0.0.1:"
            f"{WASMTIME_PORT}/infer"
        ),
        {
            "tenant_id": 0,
            "features": features,
        },
    )

    docker = post(
        (
            "http://127.0.0.1:"
            f"{DOCKER_BASE_PORT}/infer"
        ),
        {
            "features": features,
        },
    )

    print(
        "expected:",
        expected
    )

    print(
        "wasmtime:",
        wasm
    )

    print(
        "docker:",
        docker
    )

    assert int(
        wasm["prediction"]
    ) == expected

    assert int(
        docker["prediction"]
    ) == expected

    print(
        "DUAL-BACKEND CORRECTNESS: PASS"
    )
