import csv, json, math, hashlib
from pathlib import Path
from collections import defaultdict
import numpy as np
from scipy.stats import t

ROOT = Path("/home/sallar/wasiMultitenant")
SRC = ROOT / (
    "research_enhancement/automated_supervisor_workplan/"
    "wp1_matched_correction/20261114_015337_2877545"
)
OUT = ROOT / "research_enhancement/reports/wp3_service_cost_20261121"
OUT.mkdir(parents=True, exist_ok=True)

with (SRC / "wp1_capacity_summary.csv").open() as f:
    campaign = list(csv.DictReader(f))

if len(campaign) != 481:
    raise RuntimeError(
        f"Expected 481 existing independent runs; found {len(campaign)}"
    )

metrics_by_run = []
grouped = defaultdict(lambda: defaultdict(list))

def save_csv(path, rows):
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

for index, run in enumerate(campaign, 1):
    model = run["model"]
    backend = run["backend"]
    rate = int(float(run["offered_rps"]))
    rep = int(run["repeat"])

    path = SRC / f"{model}_{backend}/rps{rate}_rep{rep}.requests.jsonl"
    if not path.is_file():
        raise RuntimeError(f"Missing original request evidence: {path}")

    values = defaultdict(list)
    requests = 0

    with path.open() as f:
        for line in f:
            if not line.strip():
                continue

            r = json.loads(line)
            requests += 1

            if r.get("success") is not True:
                raise RuntimeError(f"Unsuccessful request in {path}")

            required = [
                "latency_from_dispatch_ns",
                "request_total_ns",
                "inference_time_ns",
                "execution_time_ns"
            ]
            if backend == "docker":
                required.append("adapter_roundtrip_ns")

            if any(r.get(key) is None for key in required):
                raise RuntimeError(f"Missing instrumentation in {path}")

            client = int(r["latency_from_dispatch_ns"])
            gateway = int(r["request_total_ns"])
            inference = int(r["inference_time_ns"])
            execution = int(r["execution_time_ns"])

            spans = {
                "client_dispatch_to_response": client,
                "gateway_handler": gateway,
                "backend_inference": inference,
                "backend_execution": execution,
                "client_outside_gateway": client - gateway,
                "inference_outside_execution": inference - execution
            }

            if backend == "docker":
                adapter = int(r["adapter_roundtrip_ns"])
                spans["docker_adapter_roundtrip"] = adapter
                spans["gateway_outside_adapter"] = gateway - adapter
                spans["adapter_outside_backend_inference"] = adapter - inference
            else:
                spans["gateway_outside_inference"] = gateway - inference

            if any(v < 0 for v in spans.values()):
                raise RuntimeError(
                    f"Inconsistent nested timing spans in {path}; "
                    "cannot attribute negative overhead"
                )

            for key, value in spans.items():
                values[key].append(value / 1e6)

    if requests != int(run["success"]):
        raise RuntimeError(
            f"Request count mismatch in {path}: "
            f"{requests} versus {run['success']}"
        )

    key = (model, backend, rate)

    for metric, observations in values.items():
        x = np.asarray(observations, dtype=float)

        for quantile, percentile in (
            ("p50", 50), ("p95", 95), ("p99", 99)
        ):
            v = float(np.percentile(x, percentile))
            grouped[(key, metric, quantile)]["values"].append(v)

            metrics_by_run.append({
                "model": model,
                "backend": backend,
                "offered_rps": rate,
                "repetition": rep,
                "metric": metric,
                "quantile": quantile,
                "value_ms": v,
                "request_count": requests
            })

    if index % 50 == 0:
        print(f"Processed {index}/481 existing runs", flush=True)

save_csv(OUT / "service_components_by_run.csv", metrics_by_run)

rng = np.random.default_rng(20261121)
results = []

for (key, metric, quantile), data in sorted(grouped.items()):
    model, backend, rate = key
    x = np.asarray(data["values"], dtype=float)
    n = len(x)
    avg = float(x.mean())

    if n < 20 or not np.isfinite(x).all():
        raise RuntimeError(f"Invalid run summaries: {key}/{metric}/{quantile}")

    if avg <= 0:
        t_pct = math.inf
        b_pct = math.inf
    else:
        th = float(t.ppf(.975, n-1) * x.std(ddof=1) / math.sqrt(n))
        boot = x[rng.integers(0, n, size=(3000, n))].mean(axis=1)
        bh = float(np.diff(np.quantile(boot, [.025, .975]))[0] / 2)
        t_pct = 100 * th / avg
        b_pct = 100 * bh / avg

    results.append({
        "model": model,
        "backend": backend,
        "offered_rps": rate,
        "metric": metric,
        "quantile": quantile,
        "independent_runs": n,
        "mean_ms": avg,
        "student_t_ci_pct": t_pct,
        "bootstrap_ci_pct": b_pct,
        "precision_accepted": max(t_pct, b_pct) <= 2.5
    })

save_csv(OUT / "service_95ci.csv", results)

passed = sum(r["precision_accepted"] for r in results)

report = {
    "work_package": "WP3 Section 6.1",
    "source_campaign": str(SRC.relative_to(ROOT)),
    "independent_runs_analysed": len(campaign),
    "conditions": 20,
    "confidence": 0.95,
    "bootstrap_resamples": 3000,
    "target_relative_halfwidth_pct": 2.5,
    "accepted_metric_quantiles": passed,
    "total_metric_quantiles": len(results),
    "status": "EVIDENCE_ANALYSED_STOP_GO_REVIEW_PENDING",
    "notes": [
        "Per-request nested timing differences calculated before percentiles",
        "Gateway handler timer excludes ingress parsing and response serialization",
        "Client-to-response includes HTTP transport and client overhead",
        "Docker adapter timing includes bridge transport and backend response",
        "Backend inference and execution timers have different scopes",
        "No raw experiments rerun or pooled with different configurations",
        "Precision failures remain explicitly unaccepted"
    ]
}

(OUT / "RESULT.json").write_text(json.dumps(report, indent=2) + "\n")

(OUT / "README.md").write_text(
    "# WP3 Complete Serving-Cost Attribution\n\n"
    f"- Independent run summaries: {len(campaign)}\n"
    f"- Precision accepted: {passed}/{len(results)} metric-quantile conditions\n"
    "- Confidence: 95% Student-t and bootstrap\n"
    "- Relative half-width target: <=2.5%\n"
    "- Source: corrected WP1 common-ingress LR/RF campaign\n\n"
    "Timing differences were calculated for individual requests, "
    "not by subtracting percentiles.\n\n"
    "**Scope:** existing common-gateway timings only. "
    "Measurement boundaries are detailed in RESULT.json. "
    "WP1–WP3 STOP/GO remains pending.\n"
)

print("FINAL: WP3 EXISTING SERVICE TRACES ANALYSED", flush=True)
print(f"Independent runs: {len(campaign)}", flush=True)
print(f"Precision accepted: {passed}/{len(results)}", flush=True)
print("OUTPUT:", OUT, flush=True)
