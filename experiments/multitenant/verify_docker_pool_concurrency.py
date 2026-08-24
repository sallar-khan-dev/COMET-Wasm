#!/usr/bin/env python3

import concurrent.futures
import csv
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

DATA = ROOT / "models/naive_bayes/breast_cancer/test_samples.csv"

BASE_PORT = 8200
CONTAINERS = 4
TENANTS = 100
REQUESTS_PER_TENANT = 10

with DATA.open() as f:
    rows = list(csv.DictReader(f))

sample = rows[0]

features = [
    float(v)
    for k, v in sample.items()
    if k != "label"
]

EXPECTED = int(sample["label"])


def request(tenant_id):
    container_id = tenant_id % CONTAINERS
    port = BASE_PORT + container_id

    payload = json.dumps({
        "features": features
    }).encode()

    req = urllib.request.Request(
        f"http://localhost:{port}/infer",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    with urllib.request.urlopen(req, timeout=10) as response:
        result = json.loads(response.read())

    return {
        "tenant_id": tenant_id,
        "container_id": container_id,
        "prediction": int(result["prediction"]),
    }


jobs = [
    tenant
    for tenant in range(TENANTS)
    for _ in range(REQUESTS_PER_TENANT)
]


results = []

with concurrent.futures.ThreadPoolExecutor(
    max_workers=64
) as executor:

    futures = [
        executor.submit(request, tenant)
        for tenant in jobs
    ]

    for future in concurrent.futures.as_completed(futures):
        results.append(future.result())


wrong_predictions = [
    r for r in results
    if r["prediction"] != EXPECTED
]

wrong_mapping = [
    r for r in results
    if r["container_id"] != r["tenant_id"] % CONTAINERS
]

tenants_seen = {
    r["tenant_id"] for r in results
}

containers_seen = {
    r["container_id"] for r in results
}


print("===== Docker Multi-Tenant Concurrent Validation =====")
print()
print("Logical tenants:", TENANTS)
print("Physical containers:", CONTAINERS)
print("Requests per tenant:", REQUESTS_PER_TENANT)
print("Expected requests:", TENANTS * REQUESTS_PER_TENANT)
print("Completed requests:", len(results))
print("Tenant IDs seen:", len(tenants_seen))
print("Containers seen:", sorted(containers_seen))
print("Wrong predictions:", len(wrong_predictions))
print("Wrong mappings:", len(wrong_mapping))


assert len(results) == TENANTS * REQUESTS_PER_TENANT
assert len(tenants_seen) == TENANTS
assert containers_seen == {0, 1, 2, 3}
assert not wrong_predictions
assert not wrong_mapping


summary = {
    "model": "naive_bayes",
    "backend": "docker",
    "physical_containers": CONTAINERS,
    "logical_tenants": TENANTS,
    "requests_per_tenant": REQUESTS_PER_TENANT,
    "total_requests": len(results),
    "wrong_predictions": len(wrong_predictions),
    "wrong_mappings": len(wrong_mapping),
    "containers_seen": sorted(containers_seen),
    "status": "PASS"
}

out = ROOT / "results/correctness/multitenant_nb_docker_pool.json"
out.write_text(json.dumps(summary, indent=2))

print()
print(json.dumps(summary, indent=2))
print()
print("DOCKER MULTI-TENANT CONCURRENT CORRECTNESS: PASS")
