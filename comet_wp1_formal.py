#!/usr/bin/env python3
"""COMET-Wasm WP1 acquisition and conservative statistical acceptance runner.

Python >=3.9; scipy recommended for exact t quantiles (otherwise fails closed).
Manifest JSON specifies real paths and backend startup commands. Never overwrites runs.
"""
import argparse, hashlib, json, math, os, random, shlex, shutil, signal, statistics, subprocess, sys, time
from pathlib import Path

try:
    from scipy.stats import t as student_t
except ImportError:
    student_t = None

METRICS = ('p50_ms','p95_ms','p99_ms','throughput_rps')

def save_atomic(path, data):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp = path.with_name(path.name+'.tmp')
    tmp.write_text(json.dumps(data,indent=2,sort_keys=True)+'\n')
    tmp.replace(path)

def t_interval(values, confidence=.95):
    if len(values)<2 or student_t is None: return None
    n=len(values); mu=statistics.mean(values)
    hw=float(student_t.ppf((1+confidence)/2,n-1))*statistics.stdev(values)/math.sqrt(n)
    return dict(mean=mu,lower=mu-hw,upper=mu+hw,relative_halfwidth=(hw/abs(mu) if mu else None))

def bootstrap_interval(values, *, seed, nboot=2000, confidence=.95):
    # Cluster bootstrap of independent repetitions, not individual requests.
    if len(values)<2:return None
    rng=random.Random(seed); n=len(values); arr=[]
    for _ in range(nboot):arr.append(statistics.mean(rng.choices(values,k=n)))
    arr.sort(); lo=arr[int((1-confidence)/2*nboot)]; hi=arr[min(nboot-1,int((1+confidence)/2*nboot))]
    mu=statistics.mean(values)
    return dict(mean=mu,lower=lo,upper=hi,relative_halfwidth=((hi-lo)/2/abs(mu) if mu else None))

def get(d,*keys):
    for k in keys:
        if k in d:return d[k]
    return None

def parse_output(stdout, summary_path, expected):
    import re
    def number(label):
        m=re.search(r'^'+re.escape(label)+r':\s*(?:Some\()?([\d.eE+-]+)',stdout,re.M)
        return float(m.group(1)) if m else None
    offered=number('Offered requests'); success=number('Successful requests')
    failed=number('Failed requests'); timeout=number('Timed out requests'); dropped=number('Dropped requests')
    if any(x is None for x in (offered,success,failed,timeout,dropped)):
        raise ValueError('Missing request counters in load-generator output')
    if offered!=expected or success!=expected or failed or timeout or dropped:
        raise ValueError(f'Invalid counts: offered={offered}, success={success}, failed={failed}, timeout={timeout}, dropped={dropped}')
    result={'p50_ms':number('P50 latency (ms)'), 'p95_ms':number('P95 latency (ms)'), 'p99_ms':number('P99 latency (ms)')}
    if any(result[k] is None or result[k]<=0 for k in ('p50_ms','p95_ms','p99_ms')):
        raise ValueError('Missing/invalid latency percentiles')
    # Use measured elapsed time only, never offered rate as achieved throughput.
    # We require a documented wall-clock elapsed duration in summary, or else fail closed.
    summ=json.loads(summary_path.read_text())
    elapsed=get(summ,'elapsed_seconds','elapsed_s','duration_seconds','duration_s','wall_time_seconds')
    if elapsed is None:
        # Check explicit millisecond/nanosecond duration keys.
        ms=get(summ,'elapsed_ms','duration_ms')
        ns=get(summ,'elapsed_ns','duration_ns')
        if ms is not None:elapsed=float(ms)/1000
        elif ns is not None:elapsed=float(ns)/1e9
    if elapsed is None or float(elapsed)<=0:
        raise ValueError('Summary has no recognized measured duration; cannot compute achieved throughput safely. Inspect summary keys and configure parser.')
    result['throughput_rps']=success/float(elapsed)
    result['elapsed_seconds']=float(elapsed)
    return result

def run_command(command, env, cwd, logfile):
    with logfile.open('w') as f:
        p=subprocess.run(command,cwd=cwd,env=env,stdout=f,stderr=subprocess.STDOUT,text=True)
    return p.returncode

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--manifest',required=True)
    ap.add_argument('--out',required=True)
    ap.add_argument('--models',nargs='*',default=None)
    ap.add_argument('--min-reps',type=int,default=20)
    ap.add_argument('--max-reps',type=int,default=60)
    ap.add_argument('--target',type=float,default=.025)
    ap.add_argument('--bootstrap',type=int,default=2000)
    ap.add_argument('--resume',action='store_true')
    args=ap.parse_args()
    if student_t is None:sys.exit('scipy missing: exact 95% Student-t CI unavailable. Install in existing venv or use your existing statistical_control.py.')
    if not (2<=args.min_reps<=args.max_reps and 0<args.target<1):sys.exit('Invalid stopping parameters')
    manifest_path=Path(args.manifest).resolve(); cfg=json.loads(manifest_path.read_text())
    root=Path(cfg['root']).resolve(); out=Path(args.out).resolve(); out.mkdir(parents=True,exist_ok=True)
    models=args.models or list(cfg['models'])
    for model in models:
        if model not in cfg['models']:sys.exit(f'Missing model configuration: {model}')
    for model in models:
      spec=cfg['models'][model]
      for backend in ('wasmtime','docker'):
        b=spec['backends'][backend]
        for k in ('trace','golden','startup','shutdown','endpoint','backend_name'):
            if k not in b:sys.exit(f'{model}/{backend} missing {k}')
        trace=(root/b['trace']).resolve(); golden=(root/b['golden']).resolve()
        if not trace.is_file() or not golden.is_file():sys.exit(f'Missing trace/golden: {trace} / {golden}')
        req=json.loads(trace.read_text())['requests']; expected=len(req)
        if expected<1000:sys.exit(f'{model}/{backend}: trace too short ({expected}); sustained run requires >=1000 requests')
        for rps in cfg['rps_levels']:
          dest=out/model/backend/f'rps{rps}'; dest.mkdir(parents=True,exist_ok=True)
          state_path=dest/'statistical_summary.json'
          if state_path.exists() and not args.resume:sys.exit(f'Existing campaign: {state_path}; pass --resume')
          existing=list(sorted(dest.glob('rep*.metrics.json')))
          rows=[json.loads(p.read_text()) for p in existing]
          if len(existing)!=len(rows):sys.exit('Incomplete results')
          # Startup per condition, shutdown always; commands are supplied by user manifest.
          env=os.environ.copy(); env.update({str(k):str(v) for k,v in b.get('env',{}).items()})
          startup=subprocess.Popen(['bash','-lc',b['startup']],cwd=root,env=env,stdout=(dest/'server.log').open('a'),stderr=subprocess.STDOUT,start_new_session=True)
          try:
            time.sleep(float(b.get('startup_wait_seconds',2)))
            if startup.poll() is not None:raise RuntimeError(f'Server startup failed for {model}/{backend}; inspect {dest}/server.log')
            for rep in range(len(rows)+1,args.max_reps+1):
              prefix=dest/f'rep{rep:02d}'
              if any(Path(str(prefix)+ext).exists() for ext in ('.log','.metrics.json','.summary.json','.requests.jsonl')):
                raise RuntimeError(f'Existing partial output: {prefix}; manual reconciliation required')
              cmd=[str((root/cfg['loadgen']).resolve()),str(trace),str(golden),'http',b['endpoint'],b['backend_name'],str(rps),str(cfg.get('timeout_ms',5000)),str(cfg.get('max_inflight',256)),str(prefix)]
              runenv=env.copy();runenv['COMET_LOADGEN_WORKERS']=str(cfg.get('loadgen_workers',2))
              print(f'{model}/{backend} RPS={rps} rep={rep}/{args.max_reps}',flush=True)
              rc=run_command(cmd,runenv,root,Path(str(prefix)+'.log'))
              if rc:raise RuntimeError(f'Load generator exit {rc}: {prefix}.log')
              metrics=parse_output(Path(str(prefix)+'.log').read_text(),Path(str(prefix)+'.summary.json'),expected)
              save_atomic(Path(str(prefix)+'.metrics.json'),metrics);rows.append(metrics)
              if rep>=args.min_reps:
                stat={}
                for metric in METRICS:
                  vals=[r[metric] for r in rows]
                  # t and cluster bootstrap both must meet precision target.
                  tci=t_interval(vals); bci=bootstrap_interval(vals,seed=42+rep,nboot=args.bootstrap)
                  stat[metric]={'student_t':tci,'run_cluster_bootstrap':bci,'precision_accepted':all(x['relative_halfwidth'] is not None and x['relative_halfwidth']<=args.target for x in (tci,bci))}
                precise=all(x['precision_accepted'] for x in stat.values())
                report={'model':model,'backend':backend,'offered_rps':rps,'repetitions':rep,'confidence_level':.95,'relative_halfwidth_target':args.target,'metrics':stat,'precision_accepted':precise,'full_wp1_accepted':False,'outstanding_gates':['generator_gateway_noop_headroom','verified_cpu_memory_worker_parity','within_run_serial_dependence_block_bootstrap','documented_duration_and_achieved_load']}
                save_atomic(state_path,report)
                print('PRECISION ACCEPTED' if precise else 'CI not yet converged',flush=True)
                if precise:break
            else:print(f'UNCONVERGED {model}/{backend} rps={rps}',flush=True)
          finally:
            try:
              if startup.poll() is None:
                os.killpg(startup.pid,signal.SIGTERM)
                startup.wait(timeout=10)
            except (ProcessLookupError,subprocess.TimeoutExpired):
              if startup.poll() is None:os.killpg(startup.pid,signal.SIGKILL)
    print('Acquisition finished. Full WP1 acceptance remains gated.',flush=True)

if __name__=='__main__':main()
