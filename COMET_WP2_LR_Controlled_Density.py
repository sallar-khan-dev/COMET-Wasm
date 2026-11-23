#!/usr/bin/env python3
"""Supervisor WP2 LR controlled Wasmtime-vs-Docker density pilot, separate from historical data."""
import csv, fcntl, hashlib, json, math, os, socket, subprocess, sys, time, urllib.request
from pathlib import Path
import numpy as np
from scipy.stats import t

ROOT = Path('/home/sallar/wasiMultitenant')
BASE = ROOT/'research_enhancement/automated_supervisor_workplan/wp2_lr_controlled_density_20261121'
SERVER = ROOT/'serving/multitenant_server/target/release/comet_multitenant_server'
WASM = ROOT/'wasm/tenant_lr_real/target/wasm32-unknown-unknown/release/tenant_lr_real.wasm'
GOLD = ROOT/'research_enhancement/v2_references/lr_iris_golden_v1.json'
IMAGE = 'comet-wp1cap-lr:latest'
LEVELS = [1,5,10,20,50,100,200]
CPU = min(os.sched_getaffinity(0))
MIN_REPS, MAX_REPS = 20,40
FIELDS = ['backend','tenants','rep','pss_mib','rss_mib','private_mib','total_threads','max_threads','cpu','image_id']

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()
def run(args,timeout=60,check=True):
    p=subprocess.run([str(x) for x in args],cwd=ROOT,capture_output=True,text=True,timeout=timeout)
    if check and p.returncode:
        raise RuntimeError(f'Command failed {args[:3]}: {(p.stderr or p.stdout)[-450:]}')
    return p.stdout.strip()
def require(ok,msg):
    if not ok: raise RuntimeError('SAFE STOP: '+msg)
def freeport():
    s=socket.socket();s.bind(('127.0.0.1',0));p=s.getsockname()[1];s.close();return p
def http(url, obj):
    payload=json.dumps(obj).encode()
    q=urllib.request.Request(url,data=payload,headers={'Content-Type':'application/json'},method='POST')
    with urllib.request.urlopen(q,timeout=3) as r:return json.loads(r.read())
def ready(url, obj, expected, deadline=30):
    stop=time.monotonic()+deadline
    last=''
    while time.monotonic()<stop:
        try:
            result=http(url,obj)
            if int(result['prediction'])!=int(expected):
                raise ValueError(f'Golden prediction mismatch {result}')
            return result
        except ValueError: raise
        except Exception as e:last=str(e);time.sleep(.06)
    raise RuntimeError('Readiness failed: '+last)
def mem(text):
    d={}
    for line in text.splitlines():
        a=line.split()
        if len(a)>=2 and a[0].endswith(':') and a[1].isdigit(): d[a[0][:-1]]=int(a[1])
    require(all(k in d for k in ('Pss','Rss','Private_Clean','Private_Dirty')),
            'Kernel smaps_rollup missing PSS/private fields')
    return [d['Pss']/1024,d['Rss']/1024,(d['Private_Clean']+d['Private_Dirty'])/1024]
def threads(pid):
    p=Path(f'/proc/{pid}/status')
    for line in p.read_text().splitlines():
        if line.startswith('Threads:'):return int(line.split()[1])
    raise RuntimeError('Cannot observe Threads for '+str(pid))
def precision(values):
    if len(values)<2:return {'accepted':False}
    x=np.asarray(values,dtype=float);n=len(x);mean=float(x.mean())
    require(mean>0 and np.isfinite(x).all(),'Invalid PSS observation')
    ht=float(t.ppf(.975,n-1)*x.std(ddof=1)/math.sqrt(n))
    rng=np.random.default_rng(20261121+n)
    boot=x[rng.integers(0,n,size=(5000,n))].mean(axis=1)
    hb=float((np.quantile(boot,.975)-np.quantile(boot,.025))/2)
    return {'n':n,'mean_pss_mib':mean,'student_t_pct':100*ht/mean,
            'bootstrap_pct':100*hb/mean,'accepted':n>=MIN_REPS and max(ht,hb)/mean<=.025}
def pair_data(records,n,backend):
    subset=[r for r in records if int(r['tenants'])==n and r['backend']==backend]
    return precision([float(r['pss_mib']) for r in subset])
def wasm_run(n,rep,samples):
    port=freeport();env=dict(os.environ,TOKIO_WORKER_THREADS='1')
    p=subprocess.Popen(['taskset','-c',str(CPU),str(SERVER),'logistic_regression',str(WASM),str(n),str(port)],
                       cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        url=f'http://127.0.0.1:{port}/infer'
        for i in range(n):
            example=samples[(rep+i)%len(samples)]
            got=ready(url,{'tenant_id':i,'features':example['features']},example['expected_prediction'],60)
            require(got['worker_id']==i,'Wrong Wasm instance assignment')
            another=samples[(rep+i+7)%len(samples)]
            got=http(url,{'tenant_id':i,'features':another['features']})
            require(int(got['prediction'])==int(another['expected_prediction']),'Wasm varied-input mismatch')
        values=[]
        for _ in range(3):
            values.append(mem(Path(f'/proc/{p.pid}/smaps_rollup').read_text()))
            time.sleep(.15)
        means=np.asarray(values).mean(axis=0).tolist();tc=threads(p.pid)
        return ['wasmtime',n,rep,*means,tc,tc,CPU,'N/A']
    finally:
        if p.poll() is None:
            p.terminate()
            try:p.wait(timeout=8)
            except subprocess.TimeoutExpired:p.kill();p.wait()
def docker_run(n,rep,samples,image_id):
    names=[]
    try:
        for i in range(n):
            name=f'cometwp2lr_{os.getpid()}_{rep}_{n}_{i}'
            run(['docker','run','-d','--name',name,'--network','bridge','--cpuset-cpus',str(CPU),
                 '--pids-limit','16','--memory','128m','-e','TOKIO_WORKER_THREADS=1','-p','127.0.0.1::8085',image_id],timeout=75)
            names.append(name)
        pids=[]
        for i,name in enumerate(names):
            port=run(['docker','port',name,'8085/tcp']).rsplit(':',1)[-1]
            example=samples[(rep+i)%len(samples)]
            url=f'http://127.0.0.1:{port}/infer'
            ready(url,{'features':example['features']},example['expected_prediction'],60)
            another=samples[(rep+i+7)%len(samples)]
            got=http(url,{'features':another['features']})
            require(int(got['prediction'])==int(another['expected_prediction']),'Docker varied-input mismatch')
            pids.append(int(run(['docker','inspect','-f','{{.State.Pid}}',name])))
        totals=[]
        for _ in range(3):
            mm=[mem(run(['docker','exec','-u','0',name,'cat','/proc/1/smaps_rollup'],timeout=20)) for name in names]
            totals.append(np.sum(mm,axis=0).tolist())
            time.sleep(.15)
        m=np.asarray(totals).mean(axis=0).tolist()
        tcounts=[threads(pid) for pid in pids]
        return ['docker',n,rep,*m,sum(tcounts),max(tcounts),CPU,image_id]
    finally:
        # Never remove containers other than those created by this run.
        for name in reversed(names):
            run(['docker','rm','-f',name],check=False,timeout=30)

def main():
    require(SERVER.is_file() and WASM.is_file() and GOLD.is_file(),'Missing existing compiled LR server/Wasm/golden')
    require(len(os.sched_getaffinity(0))>=2,'Need two accessible CPUs for future matched performance work')
    image_id=run(['docker','image','inspect','-f','{{.Id}}',IMAGE],timeout=20)
    run(['docker','info','--format','{{.ServerVersion}}'],timeout=20)
    data=json.loads(GOLD.read_text())
    samples=data['records']
    require(len(samples)>=20 and all('expected_prediction' in x for x in samples),'Invalid LR golden oracle')
    mem_available=next(int(x.split()[1]) for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable:'))
    require(mem_available >= 4_000_000,'At least 4GB available RAM required for density 200 safety')
    BASE.mkdir(parents=True,exist_ok=True)
    manifest={'scope':'WP2 controlled LR pilot, total application PSS; not final base/model/helper decomposition',
              'cpu':CPU,'levels':LEVELS,'minimum_reps':MIN_REPS,'maximum_reps':MAX_REPS,
              'wasm_sha256':sha(WASM),'server_sha256':sha(SERVER),'golden_sha256':sha(GOLD),
              'docker_image_id':image_id,'docker_network':'bridge','tokio_workers_env':'1',
              'memory_samples_per_repetition':3,'warmup_predictions_per_tenant':2,
              'docker_memory_limit':'128m','docker_pids_limit':16,
              'new_treatment_not_pooled_with_historical_density':True}
    existing=BASE/'manifest.json'
    if existing.exists():require(json.loads(existing.read_text())==manifest,'Manifest changed; refusing to pool separate treatments')
    else:existing.write_text(json.dumps(manifest,indent=2)+'\n')
    path=BASE/'trials.csv'
    with path.open(newline='') if path.exists() else open(os.devnull) as f:
        records=list(csv.DictReader(f)) if path.exists() else []
    require(len({(r['backend'],int(r['tenants']),int(r['rep'])) for r in records})==len(records),'Duplicated existing repetitions')
    print('WP2 CONTROLLED LR DENSITY STARTED',flush=True)
    print('OUTPUT:',BASE,'FROZEN IMAGE:',image_id,'CPU:',CPU,flush=True)
    for n in LEVELS:
        for rep in range(1,MAX_REPS+1):
            status={b:pair_data(records,n,b) for b in ('wasmtime','docker')}
            if rep>MIN_REPS and all(v['accepted'] for v in status.values()):break
            for backend in (('wasmtime','docker') if rep%2 else ('docker','wasmtime')):
                if any(r['backend']==backend and int(r['tenants'])==n and int(r['rep'])==rep for r in records):continue
                if rep>MIN_REPS and status[backend]['accepted']:continue
                # Stop the campaign if RAM declines; preserve all previous results.
                avail=next(int(x.split()[1]) for x in Path('/proc/meminfo').read_text().splitlines() if x.startswith('MemAvailable:'))
                require(avail>2_000_000,'Available RAM below 2GB; stopping before next repetition')
                item=wasm_run(n,rep,samples) if backend=='wasmtime' else docker_run(n,rep,samples,image_id)
                row=dict(zip(FIELDS,item));records.append(row)
                with path.open('a',newline='') as f:
                    w=csv.DictWriter(f,fieldnames=FIELDS)
                    if f.tell()==0:w.writeheader()
                    w.writerow(row);f.flush();os.fsync(f.fileno())
            if rep>=MIN_REPS and (rep==MIN_REPS or rep%5==0):
                status={b:pair_data(records,n,b) for b in ('wasmtime','docker')}
                (BASE/'progress.json').write_text(json.dumps({'level':n,'rep':rep,'precision':status},indent=2)+'\n')
                print(f'N={n} REP={rep} '+ ' '.join(f'{b}: CI t={s["student_t_pct"]:.2f}% b={s["bootstrap_pct"]:.2f}% pass={s["accepted"]}' for b,s in status.items()),flush=True)
        results={str(k):{b:pair_data(records,k,b) for b in ('wasmtime','docker')} for k in LEVELS}
        (BASE/'RESULT.json').write_text(json.dumps({'precision_by_density':results,'raw':str(path)},indent=2)+'\n')
        print('LEVEL COMPLETE:',n,'RESULT:',BASE/'RESULT.json',flush=True)
    print('FINAL: WP2 LR CONTROLLED DENSITY CAMPAIGN COMPLETE',flush=True)

if __name__=='__main__':
    BASE.mkdir(parents=True,exist_ok=True)
    with (BASE/'.single_runner.lock').open('w') as f:
        try:fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:sys.exit('SAFE STOP: another controlled density experiment is running')
        try:main()
        except Exception as e:
            (BASE/'FAILURE.txt').write_text(str(e)+'\n')
            print('SAFE STOP:',str(e),flush=True)
            sys.exit(2)
