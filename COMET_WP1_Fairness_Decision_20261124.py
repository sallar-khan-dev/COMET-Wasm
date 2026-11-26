#!/usr/bin/env python3
"""WP1 supervisor §§4.1-4.5 substantive fairness and capacity adjudication.
Reads the ORIGINAL 1027 repetitions, resource traces and noop summaries,
reports measured asymmetry and per-condition evidence; never silently grants GO.
No experimental data modifications, model reruns, or invented thresholds.
"""
from pathlib import Path
from collections import defaultdict, Counter
from statistics import mean,median
import csv,json,datetime,math,sys

ROOT=Path(__file__).resolve().parent
EXP=ROOT/"research_enhancement/automated_supervisor_workplan/20261123_184837_1364620"
REPORT=ROOT/"research_enhancement/reports/wp1_fairness_decision"/datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
REPORT.mkdir(parents=True,exist_ok=False)

def jload(p):
    try:return json.loads(p.read_text())
    except (OSError,ValueError):return None
def safe_num(v):
    if type(v) in (int,float) and math.isfinite(v):return float(v)
    return None
def stat(vals):
    x=[safe_num(v) for v in vals]
    x=[v for v in x if v is not None]
    if not x:return None
    return {"n":len(x),"min":min(x),"median":median(x),"mean":mean(x),"max":max(x)}
def status(s):
    if not isinstance(s,dict):return {}
    return {k:v for k,v in s.items() if k in ("Threads","Cpus_allowed_list","voluntary_ctxt_switches","nonvoluntary_ctxt_switches","VmRSS","pid","pss_kib")}
def rowkey(r):
    return (r.get("model"),r.get("backend"),r.get("offered_rps",r.get("rate")))
state=jload(EXP/"state.json")
if state is None:
    raise SystemExit("BLOCKED: original WP1 state.json unavailable; original data unchanged.")
runs=(state.get("WP1") or {}).get("runs",[])
if not runs: raise SystemExit("BLOCKED: original WP1 state contains no runs.")
groups=defaultdict(list)
for r in runs:
    if isinstance(r,dict):groups[rowkey(r)].append(r)
rows=[]
for (model,backend,rate),data in sorted(groups.items(),key=lambda v:str(v[0])):
    offered=sum((safe_num(x.get("offered")) or 0) for x in data)
    success=sum((safe_num(x.get("success")) or 0) for x in data)
    losses=offered-success
    rows.append({
      "model":model,"backend":backend,"offered_rps":rate,"repetitions":len(data),
      "offered":int(offered),"success":int(success),"lost_requests":int(losses),
      "loss_fraction":losses/offered if offered else None,
      "gateway_cpu_pct":stat([x.get("gateway_cpu_pct") for x in data]),
      "client_cpu_pct":stat([x.get("loadgen_cpu_pct") for x in data]),
      "backend_cpu_pct":stat([x.get("docker_cpu_pct") for x in data]),
      "gateway_max_threads":stat([x.get("max_gateway_threads") for x in data]),
      "docker_max_threads":stat([x.get("max_docker_threads") for x in data]),
      "p50_ms":stat([x.get("p50_ms") for x in data]),
      "p95_ms":stat([x.get("p95_ms") for x in data]),
      "p99_ms":stat([x.get("p99_ms") for x in data]),
      "p99_scheduling_delay_ms":stat([x.get("sched_p99_ms") for x in data]),
    })
baseline={}
noop={}
for model in ("lr","rf"):
 for backend in ("wasmtime","docker"):
    label=f"{model}_{backend}"
    folder=EXP/label
    snapshot=jload(folder/"baseline_resources.json")
    baseline[label]={k:status(v) for k,v in snapshot.items() if isinstance(v,dict)} if isinstance(snapshot,dict) else None
    fs=sorted(folder.glob("noop*.summary.json"))
    samples=[]
    for f in fs:
        x=jload(f)
        if isinstance(x,dict):
            offered=x.get("offered_requests");success=x.get("successful_requests")
            samples.append({"file":str(f.relative_to(EXP)),"offered":offered,"success":success,
              "zero_loss":offered is not None and offered==success and all(x.get(k,0)==0 for k in ("failed_requests","timed_out_requests","dropped_requests"))})
    noop[label]=samples

# Resource traces: summarize max actual Linux Threads, CPU sets and context-switch counters,
# without rescanning multi-million-request HTTP traces.
resource={}
for model in ("lr","rf"):
 for backend in ("wasmtime","docker"):
    label=f"{model}_{backend}"
    folder=EXP/label
    traces=list(folder.glob("rps*.resources.json"))
    snaps=defaultdict(list)
    affinities=defaultdict(Counter)
    switches=defaultdict(list)
    for f in traces:
        x=jload(f)
        if not isinstance(x,list):continue
        for s in x:
            if not isinstance(s,dict):continue
            for role,v in s.items():
                if not isinstance(v,dict):continue
                t=safe_num(v.get("Threads"))
                if t is None:
                    try:t=float(v["Threads"])
                    except (ValueError,TypeError,KeyError):pass
                if t is not None:snaps[role].append(t)
                if v.get("Cpus_allowed_list"):affinities[role][v["Cpus_allowed_list"]]+=1
                for field in ("voluntary_ctxt_switches","nonvoluntary_ctxt_switches"):
                    try:switches[f"{role}.{field}"].append(int(v.get(field)))
                    except (ValueError,TypeError):pass
    resource[label]={"files":len(traces),
        "threads":{k:stat(v) for k,v in snaps.items()},
        "cpu_affinities":{k:dict(v) for k,v in affinities.items()},
        "context_switch_counter_samples":{k:stat(v) for k,v in switches.items()}}
# Cannot infer worker fairness from thread number alone: thread pools and mutexes differ.
# Source review: Wasmtime adapter uses spawn_blocking and 1 shared worker mutex in pilot,
# while Docker gateway and its single-worker backend are distinct processes.
fairness_conditions=[]
for model in ("lr","rf"):
  w=resource[f"{model}_wasmtime"]
  d=resource[f"{model}_docker"]
  wg=(w.get("threads") or {}).get("gateway") or {}
  dg=(d.get("threads") or {}).get("gateway") or {}
  db=(d.get("threads") or {}).get("docker_backend") or {}
  fair={
    "model":model,"wasmtime_gateway_threads_max":wg.get("max"),
    "docker_gateway_threads_max":dg.get("max"),
    "docker_backend_threads_max":db.get("max"),
    "wasmtime_gateway_CPU_sets":w.get("cpu_affinities",{}).get("gateway",{}),
    "docker_gateway_CPU_sets":d.get("cpu_affinities",{}).get("gateway",{}),
    "docker_backend_CPU_sets":d.get("cpu_affinities",{}).get("docker_backend",{}),
    "verdict":"REQUIRES_VALIDATION: equal CPU affinity alone is insufficient to match effective serving concurrency"
  }
  fairness_conditions.append(fair)
highest=max(float(x["offered_rps"]) for x in rows if safe_num(x.get("offered_rps")) is not None)
noop_rates=[]
for label,samples in noop.items():
 for x in samples:
    # Filename not always encodes RPS. Only read offered over duration if recorded.
    if x.get("zero_loss"):noop_rates.append(label)
noops_complete=all(bool(noop[k]) for k in ("lr_wasmtime","lr_docker","rf_wasmtime","rf_docker"))
losses=sum(x["lost_requests"] for x in rows)
res={
 "evidence_scope":"WP1 4.1-4.5 common serving path, Linux parity, no-op headroom, losses, variability",
 "timestamp_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
 "original_runs":len(runs),"condition_count":len(rows),
 "highest_offered_inference_rps":highest,"total_lost_requests":losses,
 "baseline":baseline,"resource_traces":resource,"fairness":fairness_conditions,
 "noop_summaries":noop,"noop_summary_files_available_for_all":noops_complete,
 "conditions":rows,
 "decision":"INCONCLUSIVE",
 "required_resolution":[
  "Confirm native backend is included through the same gateway for the supervisor's WP1 comparison; the current adaptive LR/RF runs only show Wasmtime/Docker.",
  "Validate effective worker-parity/queueing: Wasmtime spawn_blocking and the worker mutex can cause extra threads; Docker runs a separate backend process.",
  "Explain and retain the 72 lost requests and tail variability; do not silently discard them.",
  "Use no-op throughput and recorded loadgen CPU to confirm headroom without inventing a fixed threshold; traces do not by themselves demonstrate equivalent total compute."],
 "interpretation":"Existing evidence is substantial but does not prove supervisor WP1 serving fairness until effective resource/configuration parity is established.",
 "data_integrity":"Read only. No earlier results modified. No WP4 started."
}
(REPORT/"FAIRNESS.json").write_text(json.dumps(res,indent=2,default=str)+"\n")
with (REPORT/"CONDITIONS.csv").open("w",newline="") as f:
    w=csv.writer(f)
    w.writerow(["model","backend","rps","repetitions","lost_requests","gateway_max_threads_max","docker_max_threads_max","mean_gateway_cpu_pct","mean_client_cpu_pct","mean_p95_ms","mean_p99_ms"])
    for r in rows:
      s=lambda name,part:(r.get(name) or {}).get(part)
      w.writerow([r["model"],r["backend"],r["offered_rps"],r["repetitions"],
        r["lost_requests"],s("gateway_max_threads","max"),s("docker_max_threads","max"),
        s("gateway_cpu_pct","mean"),s("client_cpu_pct","mean"),
        s("p95_ms","mean"),s("p99_ms","mean")])
print("WP1 FAIRNESS — ORIGINAL DATA")
print("Repetitions:",len(runs),"Conditions:",len(rows),"Lost requests:",losses)
for x in fairness_conditions:
 print(x["model"].upper(),"Wasmtime gateway max threads:",x["wasmtime_gateway_threads_max"],
       "Docker gateway max threads:",x["docker_gateway_threads_max"],
       "Docker backend max threads:",x["docker_backend_threads_max"])
print("Baseline snapshots:",sum(bool(v) for v in baseline.values()),"/4")
print("No-op summaries found across all backend/model setups:",noops_complete)
print("WP1 fairness verdict: INCONCLUSIVE until worker parity and common native gateway path are established")
print("SAVED:",REPORT/"FAIRNESS.json")
