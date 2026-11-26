#!/usr/bin/env python3
"""WP1 §4 serving-resource/precision assessment + WP3 §6 service evidence extraction.
Reads existing results only; records truthful components and explicit missing fields.
No experiment rerun, no scheduler changes, no claim of supervisor GO.
"""
from pathlib import Path
import json, csv, math, statistics, datetime as dt, os, sys
from collections import defaultdict
ROOT=Path(__file__).resolve().parent
WP1=ROOT/"research_enhancement/automated_supervisor_workplan/20261123_184837_1364620"
RUNS=ROOT/"research_enhancement/reports/supervisor_wp2_wp3_execution"
OUT=ROOT/"research_enhancement/reports/wp1_wp3_extracted_service"/dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S")
OUT.mkdir(parents=True,exist_ok=False)

def read(p):
    try:return json.loads(Path(p).read_text())
    except (OSError,ValueError):return None
def number(x):
    return isinstance(x,(int,float)) and math.isfinite(x) and x>=0
def summarize(xs):
    xs=[float(x) for x in xs if number(x)]
    if not xs:return None
    xs.sort()
    return {"n":len(xs),"mean":statistics.mean(xs),"p50":xs[(len(xs)-1)//2],
      "p95":xs[math.ceil((len(xs)-1)*.95)],"p99":xs[math.ceil((len(xs)-1)*.99)]}
def pct(x,y):return round(x/y*100,4) if y else None

state=read(WP1/"state.json") or {}
rows=(state.get("WP1") or {}).get("runs",[])
precision=read(WP1/"adaptive_precision.json") or {}
if not rows:sys.exit("BLOCKED: WP1 original 1,027-run state is unavailable; no files modified")
groups=defaultdict(list)
for r in rows:
    if isinstance(r,dict) and all(k in r for k in ("model","backend","offered_rps")):
        groups[(r["model"],r["backend"],r["offered_rps"])].append(r)
results=[]
for (model,backend,rate),rs in sorted(groups.items()):
    key=f"{model}_{backend}_{rate}"
    pp=precision.get(key) or {}
    losses=sum(max(0,int(r.get("offered",0))-int(r.get("success",0))) for r in rs if number(r.get("offered")) and number(r.get("success")))
    # 1 per serving CPU is an illustrative NOT universal fairness guarantee:
    # consider both gateway and Docker application threads.
    row={"model":model,"backend":backend,"offered_rps":rate,
         "repetitions":len(rs),"lost_requests":losses,
         "offered_requests":sum(int(r.get("offered",0)) for r in rs if number(r.get("offered"))),
         "latency_p50_ms":summarize([r.get("p50_ms") for r in rs]),
         "latency_p95_ms":summarize([r.get("p95_ms") for r in rs]),
         "latency_p99_ms":summarize([r.get("p99_ms") for r in rs]),
         "successful_rps":summarize([r.get("achieved_success_rps_nominal") for r in rs]),
         "loadgen_cpu_pct":summarize([r.get("loadgen_cpu_pct") for r in rs]),
         "gateway_cpu_pct":summarize([r.get("gateway_cpu_pct") for r in rs]),
         "gateway_max_threads":summarize([r.get("max_gateway_threads") for r in rs]),
         "docker_backend_max_threads":summarize([r.get("max_docker_threads") for r in rs]),
         "precision_decision":pp.get("decision","NOT_RECORDED"),
         "precision_metrics":pp.get("metrics",{}),
         "server_thread_parity":"NOT_ESTABLISHED_BY_THREAD_COUNT_ALONE"}
    results.append(row)
# WP1 source-grounded no-op calibration and server affinity files.
noop={}
affinity={}
for b in ("wasmtime","docker"):
 for m in ("lr","rf"):
    folder=WP1/f"{m}_{b}"
    baseline=read(folder/"baseline_resources.json")
    if baseline: affinity[f"{m}_{b}"]=baseline
    files=list(folder.glob("noop*.summary.json")) if folder.is_dir() else []
    noop[f"{m}_{b}"]=[{"file":str(f),
      "offered":(read(f) or {}).get("offered_requests"),
      "success":(read(f) or {}).get("successful_requests"),
      "failed":(read(f) or {}).get("failed_requests"),
      "timed_out":(read(f) or {}).get("timed_out_requests"),
      "dropped":(read(f) or {}).get("dropped_requests")} for f in files]

# WP3 genuine batched components; distinguish independently timed guest from subtraction.
batched={}
if RUNS.is_dir():
 for d in sorted(RUNS.glob("*"),reverse=True):
    if all((d/f"wp3_kernel_{m}.json").is_file() for m in ("lr","rf")):
      for m in ("lr","rf"):
        k=read(d/f"wp3_kernel_{m}.json") or {}
        native=k.get("native_kernel_ns_per_inference",[])
        copy=k.get("wasm_input_copy_ns_per_inference",[])
        combined=k.get("wasm_copy_plus_guest_call_ns_per_inference",[])
        dif=[a-b for a,b in zip(combined,copy) if number(a) and number(b)]
        batched[m]={"source":str(d/f"wp3_kernel_{m}.json"),
          "native_kernel_ns":summarize(native),"input_copy_ns":summarize(copy),
          "copy_plus_guest_call_ns":summarize(combined),
          "guest_call_plus_host_overhead_estimated_ns":summarize(dif),
          "interpretation":"Derived paired difference; NOT independently timed pure guest compute"}
      break
# Look at existing raw request lines for service component fields, with strict definitions.
fields=("request_total_ns","execution_time_ns","inference_time_ns","adapter_roundtrip_ns")
observed=defaultdict(lambda:defaultdict(list))
raw_sample_counts=defaultdict(int)
request_files=sorted(WP1.glob("*/*.requests.jsonl"))
for f in request_files:
    # Only infer model/backend from folder name; do not conflate no-op samples.
    folder=f.parent.name
    if folder not in ("lr_wasmtime","lr_docker","rf_wasmtime","rf_docker"):continue
    with f.open(errors="replace") as stream:
      for line_number,line in enumerate(stream):
        if line_number>=3: break
        try:x=json.loads(line)
        except (ValueError,TypeError):continue
        if not isinstance(x,dict):continue
        raw_sample_counts[folder]+=1
        for field in fields:
            if number(x.get(field)):observed[folder][field].append(x[field])
            elif isinstance(x.get("response"),dict) and number(x["response"].get(field)):
                observed[folder][field].append(x["response"][field])
service={}
for folder in ("lr_wasmtime","lr_docker","rf_wasmtime","rf_docker"):
    vals=observed[folder]
    service[folder]={
      "sampled_request_records":raw_sample_counts[folder],
      "recorded_response_components_ns":{field:summarize(vals[field]) for field in fields},
      "full_service_decomposition_accepted":False,
      "unavailable_components":[field for field in fields if not vals[field]]}
# Existing common-ingress response has these fields, but generator may not store them.
# Avoid false attribution: end-to-end HTTP latency is not pure server service.
coverage={"WP1_conditions":len(groups),"WP1_repetitions":len(rows),
 "WP1_noop":noop,"WP1_baseline_resources":affinity,
 "WP1_condition_metrics":results,
 "WP3_batched_kernels":batched,
 "WP3_response_component_evidence":service,
 "caveats":[
   "Server CPU affinity cannot prove equivalent Tokio/thread worker capacity.",
   "Request losses and outlier variance are reported rather than discarded.",
   "Full HTTP latency is not identical to server processing time.",
   "Input copy plus guest-call minus input-copy is not pure guest compute.",
   "Docker helper PSS is not measured where host permission prevents reading.",
   "Missing per-request response fields require backend response capture for true WP3 service decomposition."],
 "supervisor_gate":"NOT_AUTOMATICALLY_APPROVED"}
(OUT/"EVIDENCE.json").write_text(json.dumps(coverage,indent=2,default=str)+"\n")
with (OUT/"WP1_CONDITIONS.csv").open("w",newline="") as f:
 w=csv.writer(f)
 w.writerow(("model","backend","offered_rps","repetitions","losses","mean_p95_ms","mean_p99_ms","mean_loadgen_cpu_pct","mean_gateway_threads","mean_backend_threads","precision_decision"))
 for r in results:
    val=lambda k: (r.get(k) or {}).get("mean")
    w.writerow([r["model"],r["backend"],r["offered_rps"],r["repetitions"],r["lost_requests"],val("latency_p95_ms"),val("latency_p99_ms"),val("loadgen_cpu_pct"),val("gateway_max_threads"),val("docker_backend_max_threads"),r["precision_decision"]])
print("WP1:",len(rows),"repetitions,",len(groups),"conditions; precision accepted",
 sum(r["precision_decision"]=="PRECISION_ACCEPTED" for r in results))
print("WP1 request losses:",sum(r["lost_requests"] for r in results))
print("WP1 baseline resource snapshots:",len(affinity),"/4")
print("WP3 batched kernels:",",".join(batched) if batched else "NOT FOUND")
for k,v in service.items():
 print("WP3",k,"sampled",v["sampled_request_records"],"response timing fields:",",".join([n for n,t in v["recorded_response_components_ns"].items() if t]) or "NONE")
print("SAVED",OUT/"EVIDENCE.json")
