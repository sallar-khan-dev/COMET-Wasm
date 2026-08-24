#!/usr/bin/env python3

import concurrent.futures
import csv
import json
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

DATA = ROOT / "models/naive_bayes/breast_cancer/test_samples.csv"
URL = "http://localhost:8100/infer"

with DATA.open() as f:
    rows = list(csv.DictReader(f))

sample = rows[0]

features = [
    float(v)
    for k, v in sample.items()
    if k != "label"
]

EXPECTED = int(sample["label"])

TENANTS = 100
REQUESTS_PER_TENANT = 10
EXPECTED_WORKERS = 4


def request(tenant_id):
    payload = json.dumps({
        "tenant_id": tenant_id,
        "features": features
    }).encode()

    req = urllib.request.Request(
        URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    with urllib.request.urlopen(req, timeout=10) as response:
        return json.loads(response.read())


jobs = []

for tenant_id in range(TENANTS):
    for _ in range(REQUESTS_PER_TENANT):
        jobs.append(tenant_id)


results = []

with concurrent.futures.ThreadPoolExecutor(
    max_workers=64
) as executor:

    futures = [
        executor.submit(request, tenant_id)
        for tenant_id in jobs
    ]

    for future in concurrent.futures.as_completed(futures):
        results.append(future.result())


wrong_predictions = [
    r for r in results
    if r["prediction"] != EXPECTED
]

wrong_worker_mapping = [
    r for r in results
    if r["worker_id"] != (r["tenant_id"] % EXPECTED_WORKERS)
]

tenant_ids_seen = {
    r["tenant_id"] for r in results
}

workers_seen = {
    r["worker_id"] for r in results
}


print("===== COMET-Wasm Multi-Tenant Concurrent Validation =====")
print()
print("Tenants:", TENANTS)
print("Requests per tenant:", REQUESTS_PER_TENANT)
print("Total expected requests:", TENANTS * REQUESTS_PER_TENANT)
print("Total completed requests:", len(results))
print("Tenant IDs seen:", len(tenant_ids_seen))
print("Workers seen:", sorted(workers_seen))
print("Wrong predictions:", len(wrong_predictions))
print("Wrong worker mappings:", len(wrong_worker_mapping))


assert len(results) == TENANTS * REQUESTS_PER_TENANT, \
    "Not all requests completed"

assert len(tenant_ids_seen) == TENANTS, \
    "Not all tenants were represented"

assert workers_seen == {0, 1, 2, 3}, \
    f"Unexpected workers seen: {workers_seen}"

assert not wrong_predictions, \
    f"{len(wrong_predictions)} incorrect predictions"

assert not wrong_worker_mapping, \
    f"{len(wrong_worker_mapping)} incorrect tenant-worker mappings"


summary = {
    "model": "naive_bayes",
    "backend": "wasmtime",
    "physical_workers": EXPECTED_WORKERS,
    "logical_tenants": TENANTS,
    "requests_per_tenant": REQUESTS_PER_TENANT,
    "total_requests": len(results),
    "wrong_predictions": len(wrong_predictions),
    "wrong_worker_mappings": len(wrong_worker_mapping),
    "workers_seen": sorted(workers_seen),
    "status": "PASS"
}

out = ROOT / "results/correctness/multitenant_nb_pool.json"
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(json.dumps(summary, indent=2))

print()
print(json.dumps(summary, indent=2))
print()
print("MULTI-TENANT CONCURRENT CORRECTNESS: PASS")
