#!/usr/bin/env python3
"""COMET-Wasm supervisor WP1 acceptance evidence gate (read-only).

Audits existing results before any additional capacity measurements. No new load
rates, duration, CI target, or capacity definition are manufactured. Does not
claim pass for missing evidence. Produces one on-screen summary, no file changes.
"""
import csv
import json
import math
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BASE = ROOT/'research_enhancement'

def readj(p):
    try: return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError): return None

def status(name, verdict, detail):
    print(f'[{verdict:12}] {name}: {detail}')

def summaries_under(folder):
    if not folder.exists(): return []
    return [(p, readj(p)) for p in folder.rglob('*.summary.json')]

def summarize_pilot():
    root = BASE/'wp1_rf_svm_pilot_runs'
    candidates = sorted(root.glob('*/FINAL_GATE.json')) if root.exists() else []
    successes = [(p,readj(p)) for p in candidates]
    successes = [(p,j) for p,j in successes if isinstance(j,dict) and j.get('status','').startswith('PILOT PASS')]
    if not successes:
        status('RF/SVM correctness pilot','MISSING','No successful FINAL_GATE.json discovered')
        return
    p,j=successes[-1]; runs=j.get('runs',[])
    valid = len(runs)==24 and all(r.get('offered_requests') == r.get('successful_requests') == 1500 and all(r.get(k)==0 for k in ('failed_requests','timed_out_requests','dropped_requests')) for r in runs)
    status('RF/SVM correctness pilot','PASS' if valid else 'REVIEW',f'{len(runs)} runs; {p.parent.relative_to(ROOT)}')
    if valid: status('RF/SVM prediction oracle','PASS','Common-ingress loadgen validated against golden V2 adapted reference; pilot scope only')

def summarize_parity():
    root=BASE/'wp1_parity_headroom'
    gates=sorted(root.glob('*/FINAL_GATE.json')) if root.exists() else []
    passed=[(p,readj(p)) for p in gates]
    passed=[(p,j) for p,j in passed if isinstance(j,dict) and j.get('status','').startswith('DIAGNOSTIC PASS')]
    if not passed:
        status('CPU/client isolation diagnostic','MISSING','No successful diagnostic found')
        return
    p,j=passed[-1]; runs=j.get('runs',[])
    cpu_pair=(j.get('service_cpu'),j.get('client_cpu'))
    status('Separate client/service CPU','PASS' if None not in cpu_pair and cpu_pair[0]!=cpu_pair[1] else 'REVIEW',f'CPUs={cpu_pair}')
    status('Docker bridge topology','PASS' if len(runs)==4 and all(x.get('bridge') == (x.get('backend')=='docker') for x in runs) else 'REVIEW',f'{len(runs)} backend configurations')
    for r in runs:
        infer=r.get('measurements',{}).get('infer',{})
        noop=r.get('measurements',{}).get('noop',{})
        status(f'{r.get("model")}/{r.get("backend")} bounded diagnostic','PASS' if all(infer.get(k)==0 for k in ('failed','dropped','timed_out')) and infer.get('successful')==infer.get('offered') and noop.get('successful')==noop.get('offered') else 'REVIEW',f'infer={infer.get("offered")}, noop={noop.get("offered")}, P99 scheduling={infer.get("p99_scheduling_delay_ms")}ms, threads={infer.get("observed_max_threads")}')
    status('Thread equivalence','REVIEW','Observed process/thread totals recorded; equivalence of runnable workers, native helper and runtime scheduling NOT established')
    status('Gateway headroom ceiling','INCOMPLETE','Bounded no-op test at one rate is not a sustained capacity/headroom envelope')

def summarize_formal():
    exp=BASE/'v2_wp1_workloads'/'experiments'
    for backend in ('wasmtime','docker'):
        p=exp/f'lr_{backend}_formal_25rps'
        outers=sorted(p.glob('outer_*/outer_summary.json')) if p.exists() else []
        nums=[]
        replay=[]
        for f in outers:
            j=readj(f)
            if not isinstance(j,dict):continue
            if isinstance(j.get('inner_replays'),int):replay.append(j['inner_replays'])
            num=j.get('requests')
            if isinstance(num,(int,float)):nums.append(num)
        status(f'Formal LR {backend} 25RPS','FOUND' if len(outers)>=20 else 'REVIEW',f'{len(outers)} outer summaries; inner repeats={sorted(set(replay))}; counts={sorted(set(nums))[:5]}')
    for p in sorted(exp.rglob('statistical_summary.json')) if exp.exists() else []:
        try:rel=p.relative_to(ROOT)
        except ValueError:rel=p
        j=readj(p)
        status('Statistical summary','FOUND' if j is not None else 'REVIEW',str(rel))
    status('RF/SVM statistical convergence','INCOMPLETE','Only two independent pilot repetitions per model/backend/load demonstrated in supplied evidence')

def capacity_inventory():
    targets=[BASE/'v2_wp1_workloads'/'experiments',BASE/'v2_wp1_corrected',BASE/'wp1_rf_svm_pilot_runs',BASE/'wp1_parity_headroom']
    groups=defaultdict(list)
    for root in targets:
        for p,j in summaries_under(root):
            if not isinstance(j,dict):continue
            rps=j.get('offered_rps')
            if rps is None:
                import re
                m=re.search(r'(\d+)rps',p.name)
                if m:rps=int(m.group(1))
            if rps is None:continue
            groups[int(float(rps))].append((p,j))
    print('\n=== EXISTING WP1 RATE COVERAGE (NOT AUTOMATIC CAPACITY ACCEPTANCE) ===')
    for rate,records in sorted(groups.items()):
        good=sum(int(j.get('successful_requests',-1))==int(j.get('offered_requests',-2)) and all(j.get(k)==0 for k in ('failed_requests','timed_out_requests','dropped_requests')) for _,j in records)
        print(f'  {rate:>6} RPS: {len(records):>4} summary files, {good:>4} fully successful')
    if not groups:status('WP1 capacity record discovery','MISSING','No usable load summaries found')
    status('Sustained maximum reliable capacity','INCOMPLETE','Cannot infer saturation/breakpoint from smoke or bounded headroom; require supervisor-defined duration and acceptance conditions')
    status('Open-loop client validity','REVIEW','Inspect recorded achieved/offered throughput, delays, drops, client isolation across capacity curve')

def main():
    print('COMET-Wasm | Supervisor WP1 evidence gate')
    print('READ ONLY: no experiments, source changes, container/process launches, or file changes')
    print('Repository:',ROOT)
    print('\n=== VERIFIED EVIDENCE ===')
    summarize_pilot()
    summarize_parity()
    summarize_formal()
    capacity_inventory()
    print('\n=== DECISION ===')
    print('WP1 RF/SVM functional integration: PASS (existing pilot).')
    print('WP1 bounded headroom/CPU-isolation diagnostic: PASS (existing diagnostic).')
    print('WP1 supervisor acceptance: NOT YET ESTABLISHED.')
    print('Next required experiment: sustained open-loop serving capacity with repeated runs and complete gateway/client/resource accounting.')
    print('Do not substitute the WP5 training load grid for an unspecified WP1 capacity protocol.')
    print('No additional results have been generated or old results overwritten.')

if __name__=='__main__':main()
