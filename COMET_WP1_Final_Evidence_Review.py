#!/usr/bin/env python3
"""Read-only WP1 acceptance evidence review for the COMET-Wasm work-plan.

Usage: .venv/bin/python COMET_WP1_Final_Evidence_Review.py
       .venv/bin/python COMET_WP1_Final_Evidence_Review.py --run PATH

No network, experiments, writes, container/service/process actions, or source changes.
All thresholds are descriptive flags, NOT supervisor-defined numerical acceptance.
"""
import argparse, json, math, os, statistics, sys
from pathlib import Path
from collections import Counter, defaultdict

ROOT=Path(__file__).resolve().parent
BASE=ROOT/'research_enhancement/automated_supervisor_workplan'

def pctl(values,q):
    if not values: return None
    values.sort()
    return values[math.ceil((len(values)-1)*q)]

def fmt(x,dp=3):
    return 'NA' if x is None else f'{x:.{dp}f}'

def read(p):
    return json.loads(p.read_text())

def examine_raw(path, backend):
    acc=Counter(); errs=Counter(); d=[]; scheduled=[]; dispatched=[]; backend_bad=0; oracle_bad=0
    latest=0; latest_schedule=0; n=0; min_completion=None
    with path.open() as f:
        for line in f:
            if not line.strip(): continue
            r=json.loads(line); n+=1
            ok=bool(r.get('success')); acc['success' if ok else 'unsuccessful']+=1
            if r.get('dropped'): acc['dropped']+=1
            if r.get('timed_out'): acc['timeout']+=1
            if not ok:
                errs[str(r.get('error') or 'no_error_message')[:120]]+=1
            if r.get('served_backend') is not None and r['served_backend']!=backend: backend_bad+=1
            if ok and r.get('actual_prediction')!=r.get('expected_prediction'): oracle_bad+=1
            for k,buf in (('scheduling_delay_ns',d),('latency_from_schedule_ns',scheduled),('latency_from_dispatch_ns',dispatched)):
                v=r.get(k)
                if isinstance(v,(int,float)) and math.isfinite(v) and v>=0 and (ok or k=='scheduling_delay_ns'):buf.append(v/1e6)
            v=r.get('completion_ns')
            if isinstance(v,(int,float)) and v>=0: latest=max(latest,v)
            v=r.get('scheduled_ns')
            if isinstance(v,(int,float)) and v>=0: latest_schedule=max(latest_schedule,v)
    # Because completion and scheduled timestamps share a run-local origin,
    # max completion is a bounded duration-based throughput estimator.
    duration=latest/1e9 if latest>0 else None
    return {'n':n, 'counts':dict(acc), 'errors':errs.most_common(6),
            'p99_schedule_delay_ms':pctl(d,.99), 'p95_latency_from_schedule_ms':pctl(scheduled,.95),
            'p95_latency_from_dispatch_ms':pctl(dispatched,.95),
            'observed_rate_from_last_completion':acc['success']/duration if duration else None,
            'last_completion_seconds':duration,'backend_mismatch':backend_bad,'prediction_mismatch':oracle_bad}

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--run',type=Path,help='Existing automated supervisor workplan results folder')
    args=ap.parse_args()
    if args.run: out=args.run.resolve()
    else:
        runs=sorted(BASE.glob('*/state.json'))
        if not runs: print('BLOCKED: No state.json found'); return 2
        out=runs[-1].parent
    statefile=out/'state.json'
    if not statefile.is_file():print('BLOCKED: No state.json at',out);return 2
    state=read(statefile); cfg=state.get('config',{}); runs=state.get('WP1',{}).get('runs',[])
    print('COMET-Wasm | WP1 FINAL EVIDENCE REVIEW (READ ONLY)')
    print('DATA:',out)
    print('STATE:',state.get('WP1',{}).get('status'))
    print('CONFIG:',json.dumps({k:cfg.get(k) for k in ('rates','seconds','repetitions','service_cpu','client_cpu')},sort_keys=True))
    expected={(m,b,r,i) for m in ('lr','rf') for b in ('wasmtime','docker') for r in cfg.get('rates',[]) for i in range(1,cfg.get('repetitions',0)+1)}
    keyed={}
    duplicates=[]
    for x in runs:
        k=(x.get('model'),x.get('backend'),x.get('offered_rps'),x.get('repeat'))
        if k in keyed:duplicates.append(k)
        keyed[k]=x
    print('\nCAMPAIGN ACCOUNTING')
    print('Expected:',len(expected),'Unique:',len(keyed),'Missing:',len(expected-set(keyed)),'Duplicates:',len(duplicates))
    print('Fully successful runs:',sum(1 for x in keyed.values() if x.get('correctness_pass')))
    print('Offered:',sum(x.get('offered') or 0 for x in keyed.values()),'Successful:',sum(x.get('success') or 0 for x in keyed.values()))
    if duplicates:print('CAUTION: Duplicate keys in state.json:',duplicates[:5])
    print('\nINFERENCE RATE-BY-RATE SUMMARY (descriptive; not confidence intervals)')
    print(f"{'model/backend':19} {'RPS':>5} {'reps':>4} {'success':>10} {'offered':>10} {'mean P95ms':>11} {'max P99sch':>11} {'mean client%':>12} {'mean server%':>12}")
    for m in ('lr','rf'):
        for rate in cfg.get('rates',[]):
            for b in ('wasmtime','docker'):
                rows=[x for k,x in keyed.items() if k[:3]==(m,b,rate)]
                if not rows:continue
                avg=lambda key: statistics.mean(v for x in rows if isinstance((v:=x.get(key)),(int,float))) if any(isinstance(x.get(key),(int,float)) for x in rows) else None
                p99=[x.get('sched_p99_ms') for x in rows if isinstance(x.get('sched_p99_ms'),(int,float))]
                serverkey='gateway_cpu_pct'
                print(f"{m+'/'+b:19} {rate:5} {len(rows):4} {sum(x.get('success') or 0 for x in rows):10} {sum(x.get('offered') or 0 for x in rows):10} {fmt(avg('p95_ms')):>11} {fmt(max(p99) if p99 else None):>11} {fmt(avg('loadgen_cpu_pct')):>12} {fmt(avg(serverkey)):>12}")
    print('\nNO-OP CALIBRATIONS (no-op uses gateway+loadgen; backend label names only the setup)')
    for m in ('lr','rf'):
        for b in ('wasmtime','docker'):
            folder=out/f'{m}_{b}'
            files=sorted(folder.glob('noop_*.summary.json'))
            if not files: print(m,b,'MISSING');continue
            for f in files:
                x=read(f)
                offered=x.get('offered_requests',0);success=x.get('successful_requests',0)
                print(m,b,f.stem, 'success',f'{success}/{offered}',
                      'offered_rps',x.get('offered_rps'), 'achieved_rps',fmt(x.get('achieved_success_rps')),
                      'p99_sched_ms',fmt(x.get('p99_scheduling_delay_ms')))
    print('\nFOCUSED REQUEST-LEVEL CHECKS')
    targets=[('lr','wasmtime',2400,3),('rf','docker',2400,3),('rf','docker',100,1),('rf','wasmtime',100,1)]
    for m,b,rate,rep in targets:
        path=out/f'{m}_{b}'/f'rps{rate}_rep{rep}.requests.jsonl'
        if not path.is_file():print('MISSING raw',path);continue
        x=examine_raw(path,b)
        print(f'{m}/{b} {rate}RPS rep{rep}:',json.dumps(x,default=list))
    print('\nINTEGRITY/INTERPRETATION')
    if len(expected)!=len(keyed) or expected-set(keyed):print('BLOCKER: Missing/duplicate campaign cells; verify raw files')
    print('REVIEW: Loss at LR/Wasmtime 2400 RPS is a real observation until request-level errors are examined.')
    print('REVIEW: RF Docker vs Wasmtime ordering changed compared with prior pilot; do not merge mismatched CPU/pinning campaigns.')
    print('REVIEW: 3600-RPS no-op vs 2400-RPS inference is 1.5x observed offered-rate margin; supervisor does not provide a numeric acceptance threshold.')
    print('REVIEW: No-op loss at 4800 RPS, with high scheduling delay, limits demonstrated gateway/loadgen envelope.')
    print('REVIEW: CPU utilisation percentages and representative active thread samples should be interpreted with measured per-process accounting, not simple thread totals.')
    print('DECISION: WP1 data complete, final supervisor acceptance is not automatically established. No new runs were launched.')
    return 0

if __name__=='__main__':sys.exit(main())
