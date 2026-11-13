#!/usr/bin/env python3
"""COMET-Wasm supervisor work-plan automation (controlled, fail-closed).

Current executable phase: WP1 sustained open-loop LR+RF capacity evidence, automatic
preflight, no-op headroom, resource sampling, and conservative gate. Remaining
WPs are evidence-audited but NEVER marked passed automatically without prescribed
acceptance proof. Does not alter source, earlier results, or scheduler.

Use: .venv/bin/python COMET_Auto_Workplan.py --mode auto
     .venv/bin/python COMET_Auto_Workplan.py --mode audit
     .venv/bin/python COMET_Auto_Workplan.py --mode status
     .venv/bin/python COMET_Auto_Workplan.py --mode auto --resume /path/to/previous/run
"""
import argparse
import csv
import datetime as dt
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import signal
import socket
import statistics
import subprocess
import sys
import threading
import time
import urllib.request
import random
try:
    from scipy.stats import t as student_t
except ImportError:
    student_t = None

ROOT=Path(__file__).resolve().parent
GEN=ROOT/'research_enhancement/v2_loadgen/target/release/comet_v2_loadgen'
ING=ROOT/'serving/common_ingress/target/release/comet_common_ingress'
TRACEGEN=ROOT/'research_enhancement/v2_workloads/generate_trace.py'
LR_GOLD=ROOT/'research_enhancement/v2_references/lr_iris_golden_v1.json'
LR_WASM=ROOT/'wasm/tenant_lr_real/target/wasm32-unknown-unknown/release/tenant_lr_real.wasm'
PILOT=ROOT/'research_enhancement/wp1_rf_svm_pilot_runs/20261110_170246_710579'
RF_WASM=ROOT/'wasm/tenant_rf_real/target/wasm32-unknown-unknown/release/tenant_rf_real.wasm'
OUTROOT=ROOT/'research_enhancement/automated_supervisor_workplan'
GATEWAY_PORT=8200
DOCKER_HOST_PORT=18585
WP1_MODELS=('lr','rf')

class Blocker(Exception):pass

def must(ok,msg):
    if not ok:raise Blocker(msg)

def atomic_json(p,v):
    temp=p.with_suffix(p.suffix+'.writing')
    with temp.open('w') as f:json.dump(v,f,indent=2,default=str);f.write('\n')
    temp.replace(p)

def run(argv,log=None,env=None,timeout=120,check=True):
    argv=[str(x) for x in argv]
    if log:
        with Path(log).open('w') as f:
            r=subprocess.run(argv,cwd=ROOT,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=timeout)
    else:
        r=subprocess.run(argv,cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=timeout)
    if check and r.returncode:raise Blocker(f'Exit {r.returncode} for {argv[0]}; see {log or r.stdout[-1500:]}')
    return r

def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1<<20),b''):h.update(b)
    return h.hexdigest()

def free(port):
    """Check for a real TCP LISTEN socket, not a transient TIME_WAIT bind error.

    /proc/net/tcp[6] is kernel-native and does not require elevated access.
    A matching listener on ANY local interface blocks a new loopback listener.
    """
    needle=f'{port:04X}'
    for table in ('/proc/net/tcp','/proc/net/tcp6'):
        try:
            lines=Path(table).read_text().splitlines()[1:]
        except OSError:
            return False
        for line in lines:
            parts=line.split()
            if len(parts)>3 and parts[3]=='0A' and parts[1].split(':')[-1].upper()==needle:
                return False
    return True

def wait_free(ports, timeout=10):
    """Wait for old owned listeners to finish closing; never terminate unknown processes."""
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if all(free(p) for p in ports):return True
        time.sleep(.2)
    return all(free(p) for p in ports)

def listener_diagnostics(ports):
    result=run(['ss','-ltnp'],check=False,timeout=10)
    text=result.stdout if result.returncode==0 else '(ss unavailable)'
    return '\n'.join(line for line in text.splitlines() if any(':'+str(p)+' ' in line for p in ports)) or '(no matching listeners visible)'

def backend_complete(out,model,backend,args):
    """Resume skip only if EVERY summary+request record pair is present and valid."""
    folder=out/f'{model}_{backend}'
    for rate in args.rates:
        for rep in range(1,args.repetitions+1):
            stem=folder/f'rps{rate}_rep{rep}'
            summ=stem.with_suffix('.summary.json')
            raw=stem.with_suffix('.requests.jsonl')
            if not summ.is_file() or not raw.is_file():return False
            try:
                data=json.loads(summ.read_text())
                if data.get('offered_requests')!=round(rate*args.seconds):return False
                if sum(data.get(k,0) for k in ('successful_requests','failed_requests','timed_out_requests','dropped_requests'))!=data['offered_requests']:return False
                if raw.stat().st_size==0:return False
            except (OSError,ValueError,KeyError,TypeError):return False
    return True

def ready(url,proc=None,timeout=30):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if proc is not None and proc.poll() is not None:return False
        try:
            with urllib.request.urlopen(url,timeout=1) as r:
                if r.status==200:return True
        except Exception:pass
        time.sleep(.25)
    return False

def inference_ready(model, backend, timeout=30):
    golden=LR_GOLD if model=='lr' else PILOT/'rf_golden_v2_adapted.json'
    entry=json.loads(golden.read_text())['records'][0]
    req={'request_id':'wp1-preflight-oracle','tenant_id':0,'model':model,'features':entry['features']}
    payload=json.dumps(req).encode()
    until=time.monotonic()+timeout
    last_error='unavailable'
    while time.monotonic()<until:
        try:
            x=urllib.request.Request(f'http://127.0.0.1:{GATEWAY_PORT}/infer',data=payload,
                headers={'Content-Type':'application/json'},method='POST')
            with urllib.request.urlopen(x,timeout=2) as response:
                body=json.loads(response.read())
            if body.get('prediction')==entry['expected_prediction'] and body.get('backend')==backend:
                return True
            last_error=f'Wrong backend or prediction: {body}'
            break
        except Exception as e:
            last_error=str(e);time.sleep(.25)
    raise Blocker(f'{model}/{backend} oracle readiness failed: {last_error}')

def parse_status(pid):
    p=Path('/proc')/str(pid)
    if not p.exists():return {'pid':pid,'missing':True}
    values={'pid':pid}
    try:
        for ln in (p/'status').read_text().splitlines():
            if ln.startswith(('Threads:', 'Cpus_allowed_list:', 'voluntary_ctxt_switches:', 'nonvoluntary_ctxt_switches:', 'VmRSS:')):
                k,v=ln.split(':',1);values[k]=v.strip()
        stat=(p/'stat').read_text(); rest=stat.rsplit(')',1)[1].strip().split()
        values['utime_ticks']=int(rest[11]);values['stime_ticks']=int(rest[12])
        try:values['pss_kib']=next(int(l.split()[1]) for l in (p/'smaps_rollup').read_text().splitlines() if l.startswith('Pss:'))
        except (OSError,StopIteration,ValueError):values['pss_kib']=None
    except (OSError,ValueError):values['missing']=True
    return values

def percent(vals,p):
    if not vals:return None
    s=sorted(vals);return s[math.ceil((len(s)-1)*p)]

def records(path):
    delays=[]; service=[]; late=0; total=0
    with path.open() as f:
        for ln in f:
            if not ln.strip():continue
            r=json.loads(ln);total+=1
            d=r.get('scheduling_delay_ns')
            if isinstance(d,(int,float)):
                delays.append(d/1e6)
                if d>5_000_000:late+=1
            t=r.get('latency_from_dispatch_ns')
            if isinstance(t,(int,float)) and r.get('success'):service.append(t/1e6)
    return {'records':total,'sched_p50_ms':percent(delays,.5),'sched_p95_ms':percent(delays,.95),
            'sched_p99_ms':percent(delays,.99),'dispatch_to_response_p95_ms':percent(service,.95),
            'scheduling_delay_gt_5ms':late}

class Owned:
    def __init__(self):self.ingress=None;self.handle=None;self.container=None
    def close(self):
        if self.ingress is not None:
            if self.ingress.poll() is None:
                try:os.killpg(self.ingress.pid,signal.SIGTERM)
                except ProcessLookupError:pass
                try:self.ingress.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    try:os.killpg(self.ingress.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                    self.ingress.wait(timeout=5)
            self.ingress=None
        if self.handle:
            self.handle.close();self.handle=None
        if self.container:
            try:run(['docker','stop','-t','3',self.container],timeout=30,check=False)
            except Exception:pass
            self.container=None

def docker_pid(name):
    r=run(['docker','inspect','-f','{{.State.Pid}}',name]);return int(r.stdout.strip())

def resources_while(cmd,log,pids,client_cpu,timeout):
    """Collect service AND client process CPU ticks, affinity and thread samples."""
    samples=[];stop=threading.Event()
    env=os.environ.copy();env['COMET_LOADGEN_WORKERS']='1'
    with Path(log).open('w') as f:
        proc=subprocess.Popen(['taskset','-c',str(client_cpu)]+[str(x) for x in cmd],
            cwd=ROOT,env=env,stdout=f,stderr=subprocess.STDOUT,start_new_session=True)
        def worker():
            while not stop.is_set():
                snap={'elapsed_utc':dt.datetime.now(dt.timezone.utc).isoformat()}
                for k,p in {**pids,'loadgen':proc.pid}.items():snap[k]=parse_status(p)
                samples.append(snap);stop.wait(.25)
        t=threading.Thread(target=worker,daemon=True);t.start()
        try:
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            try:os.killpg(proc.pid,signal.SIGTERM)
            except ProcessLookupError:pass
            try:proc.wait(timeout=4)
            except subprocess.TimeoutExpired:
                try:os.killpg(proc.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                proc.wait()
            raise Blocker(f'Load generator exceeded {timeout}s; inspect {log}')
        finally:stop.set();t.join(timeout=5)
        must(proc.returncode==0,f'Load generator exited {proc.returncode}; see {log}')
    return samples

def cpu_util(samples,key):
    values=[x.get(key,{}) for x in samples]
    values=[(x.get('utime_ticks',0)+x.get('stime_ticks',0)) for x in values if isinstance(x.get('utime_ticks'),int)]
    # Across sampler timestamps, CPU percent is estimated against wall duration.
    if len(values)<2:return None
    span=(len(samples)-1)*.25
    return round((values[-1]-values[0])/os.sysconf('SC_CLK_TCK')/max(.001,span)*100,2)

def verify_existing():
    must(PILOT.is_dir() and (PILOT/'FINAL_GATE.json').is_file(),'Previously passed RF/SVM pilot is unavailable')
    pilot=json.loads((PILOT/'FINAL_GATE.json').read_text())
    must(pilot.get('status','').startswith('PILOT PASS') and len(pilot.get('runs',[]))==24,'Pilot acceptance evidence does not match')
    must((PILOT/'rf_golden_v2_adapted.json').is_file(),'RF adapted golden reference missing')
    must(all(p.is_file() for p in (GEN,ING,TRACEGEN,LR_GOLD,LR_WASM,RF_WASM)),'Required existing executable or LR/RF artifacts missing')
    must(sha(RF_WASM)==pilot['rf_wasm_sha256'],'RF Wasm artifact differs from passed pilot')
    rf_source=ROOT/'research_enhancement/v2_references/rf_breast_cancer_golden_v1.json'
    must(sha(rf_source)==pilot['rf_golden_sha256'],'RF reference has changed')
    for x in ('taskset','docker'):
        must(shutil.which(x),f'Missing {x}')
    must(run(['docker','info'],check=False,timeout=20).returncode==0,'Docker daemon unavailable')
    image=pilot['rf_image'];image_id=run(['docker','image','inspect','-f','{{.Id}}',image],check=False)
    must(image_id.returncode==0 and image_id.stdout.strip()==pilot['rf_docker_image_id'],'RF Docker image unavailable or changed')
    # Build the existing LR Docker source automatically if the dedicated image is absent;
    # no Rust source modifications or changes to successful prior RF/SVM images.
    lr_image=os.environ.get('COMET_LR_DOCKER_IMAGE','comet-wp1cap-lr:latest')
    lr_result=run(['docker','image','inspect','-f','{{.Id}}',lr_image],check=False)
    if lr_result.returncode:
        lr_dir=ROOT/'docker/lr_server'
        must((lr_dir/'Dockerfile').is_file() and (lr_dir/'src/main.rs').is_file(),
             'LR image absent and known Docker build directory missing')
        print('BUILD existing LR Docker source ->',lr_image,flush=True)
        # Build output goes into a dedicated preflight log below.
        r=run(['docker','build','-t',lr_image,str(lr_dir)],timeout=1800,check=False)
        must(r.returncode==0,f'LR Docker build failed: {r.stdout[-2000:]}')
        lr_result=run(['docker','image','inspect','-f','{{.Id}}',lr_image],check=False)
        must(lr_result.returncode==0,'LR image build did not create an inspectable image')
    return {'rf_pilot':pilot,'images':{'rf':image,'lr':lr_image},'image_ids':{'rf':image_id.stdout.strip(),'lr':lr_result.stdout.strip()}}

def prepare_trace(out,model,count):
    gold=LR_GOLD if model=='lr' else PILOT/'rf_golden_v2_adapted.json'
    path=out/f'{model}_trace_{count}.json'
    if not path.exists():
        run([sys.executable,TRACEGEN,'--golden',gold,'--output',path,'--count',str(count),'--seed','42','--tenants','3'],log=out/f'{model}_generate.log',timeout=180)
    # Official validation-only mode performs a 100-RPS clock dry run, so it
    # is NOT appropriate for long capacity traces (could take many minutes).
    # Validate manifest and oracle explicitly; the real HTTP run also calls
    # the official loadgen's strict validate() and verify_golden().
    obj=json.loads(path.read_text()); reference=json.loads(gold.read_text())
    must(obj.get('schema_version')=='comet-v2-trace-v1' and obj.get('model')==model, 'Trace schema/model mismatch')
    must(obj.get('request_count')==count and len(obj.get('requests',[]))==count,'Incorrect trace count')
    must(obj.get('golden_artifact_sha256')==sha(gold),'Trace golden digest mismatch')
    must(obj.get('golden_model_sha256')==reference.get('model_sha256'),'Model reference mismatch')
    must(obj.get('golden_dataset_sha256')==reference.get('dataset_sha256'),'Dataset fingerprint mismatch')
    return path,gold

def evidence_audit():
    stats=list((ROOT/'research_enhancement/v2_wp1_workloads/experiments').rglob('statistical_summary.json'))
    density=list(ROOT.rglob('density_seven_levels_statistical_summary.csv'))
    wp3=ROOT/'research_enhancement/wp3_kernel_admission'
    wp4=ROOT/'results/processed/wp4_crossover'
    return {'WP1':{'LR_statistical_summary_files':len(stats),'RF_SVM_pilot_exists':(PILOT/'FINAL_GATE.json').is_file()},
            'WP2':{'seven_level_density_tables':len(density),'AOT_vs_JIT_acceptance':'UNVERIFIED'},
            'WP3':{'timing_source_exists':wp3.exists(),'batched_kernel_and_admission_acceptance':'UNVERIFIED'},
            'WP4':{'processed_summary_files':len(list(wp4.glob('*summary*.json'))) if wp4.exists() else 0,
                   'service_level_crossover':'UNVERIFIED'},
            'WP5':{'scheduler_feasibility_evaluation':'NOT STARTED/NOT VERIFIED'},
            'WP6':{'heldout_live_oracle':'NOT STARTED/NOT VERIFIED'}}

# FORMAL SCIENTIFIC STOPPING RULE. Observational unit = independent complete run;
# never use individual request samples as independent CI observations.
FORMAL_MIN_REPS=20
FORMAL_MAX_REPS=60
FORMAL_TARGET=.025
FORMAL_CONFIDENCE=.95
FORMAL_METRICS=('p50_ms','p95_ms','p99_ms','achieved_goodput_rps')

def measured_goodput(request_path, success):
    # Each open-loop trial starts at scheduled offset 0. Completion timestamps
    # are relative to the beginning of the dispatch run, not a nominal 15s.
    # Include late completions, do not silently substitute offered RPS.
    latest=0
    with Path(request_path).open() as f:
        for line in f:
            obj=json.loads(line)
            end=obj.get('completion_ns')
            if isinstance(end,(int,float)) and end>latest:latest=end
    return (success/(latest/1e9)) if latest>0 else None

def formal_ci(rows, seed):
    if student_t is None:
        raise Blocker('scipy required for exact 95% Student-t CIs; install into .venv before running')
    output={}; accepted=True
    for j,metric in enumerate(FORMAL_METRICS):
        values=[r.get(metric) for r in rows]
        if len(values)<2 or any(not isinstance(v,(float,int)) or isinstance(v,bool) or not math.isfinite(v) or v<=0 for v in values):
            output[metric]={'precision_met':False,'reason':'missing_or_nonpositive_run_level_metric'}
            accepted=False;continue
        n=len(values); mu=statistics.mean(values)
        h=float(student_t.ppf(.975,n-1))*statistics.stdev(values)/math.sqrt(n)
        rng=random.Random(seed+j*7919)
        means=sorted(sum(rng.choices(values,k=n))/n for _ in range(2000))
        lo=means[int(.025*len(means))];hi=means[min(len(means)-1,int(.975*len(means)))]
        bh=(hi-lo)/2
        t_rel=h/abs(mu);b_rel=bh/abs(mu)
        passed=t_rel<=FORMAL_TARGET and b_rel<=FORMAL_TARGET
        output[metric]={
            'n_independent_runs':n,'mean':mu,'student_t_ci95':[mu-h,mu+h],
            'student_t_relative_halfwidth':t_rel,
            'run_bootstrap_ci95':[lo,hi],
            'run_bootstrap_relative_halfwidth':b_rel,
            'precision_met':passed}
        if not passed:accepted=False
    full_success=all(r.get('correctness_pass') is True for r in rows)
    return {'n':len(rows),'confidence':FORMAL_CONFIDENCE,
            'target_relative_halfwidth':FORMAL_TARGET,
            'all_metrics_precision_met':accepted,
            'all_runs_correct':full_success,
            'formal_acceptance':accepted and full_success,
            'metrics':output}

def run_auto(args):
    allowed=sorted(os.sched_getaffinity(0))
    must(len(allowed)>=2,'Need two allocated logical CPUs, one service and one client')
    srv=allowed[0] if args.service_cpu is None else args.service_cpu
    cli=allowed[1] if args.client_cpu is None else args.client_cpu
    must(srv!=cli and srv in allowed and cli in allowed,f'Invalid service/client CPU choice from {allowed}')
    must(args.rates and len(set(args.rates))==len(args.rates) and all(1<=r<=10000 for r in args.rates),'Invalid rates')
    must(args.repetitions==FORMAL_MAX_REPS,'Formal campaign requires max repetitions = 60')
    must(student_t is not None,'scipy is required for 95% Student-t confidence intervals; refusing unverified stopping')
    must(5<=args.seconds<=90,'Seconds must be 5..90')
    must(args.noop_multiplier>=2 and args.noop_multiplier<=10,'No-op multiplier must be 2..10')
    must(args.max_inflight>0 and args.max_inflight<=1024,'Invalid max inflight')
    must(wait_free((GATEWAY_PORT,DOCKER_HOST_PORT)), 'Common-ingress or backend loopback port has an active listener; do not interfere.\n'+listener_diagnostics((GATEWAY_PORT,DOCKER_HOST_PORT)))
    existing=verify_existing()
    if args.resume:
        out=Path(args.resume).resolve();must(out.is_dir() and out.is_relative_to(OUTROOT.resolve()),'Resume directory must be an existing run under automated_supervisor_workplan')
        report=json.loads((out/'state.json').read_text())
        params=report['config'];must(params==config(args,srv,cli,existing),'Resume configuration differs; use original settings')
    else:
        timestamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d_%H%M%S')+'_'+str(os.getpid())
        out=OUTROOT/timestamp;out.mkdir(parents=True,exist_ok=False)
        report={'scope':'WP1 capacity evidence only; exploratory sweep parameters are NOT numerically specified by supervisor',
                'config':config(args,srv,cli,existing),'WP1':{'status':'RUNNING','runs':[],'blockers':[]},'other_work_packages':evidence_audit()}
        atomic_json(out/'state.json',report)
    print('COMET AUTOMATED WORKPLAN | WP1 CAPACITY',flush=True)
    print('OUTPUT:',out,flush=True)
    print('MODE: sequential isolated LR/RF, Wasmtime/Docker; no edits to existing sources/results',flush=True)
    print('IMPORTANT: capacity rates/durations are engineering test settings, not numbers prescribed by supervisor',flush=True)
    lockpath=OUTROOT/'.master.lock'
    with lockpath.open('a+') as lock:
        try:fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise Blocker('Another master runner is active')
        owned=Owned()
        try:
            # Generate distinct deterministic traces per rate, identical for both backend paths.
            for model in WP1_MODELS:
                for backend in ('wasmtime','docker'):
                    key=f'{model}_{backend}'
                    if args.resume and backend_complete(out,model,backend,args):
                        print('ALREADY COMPLETE',key,'('+str(len(args.rates)*args.repetitions)+' runs preserved; no services started)',flush=True)
                        continue
                    must(wait_free((GATEWAY_PORT,DOCKER_HOST_PORT)),
                         'Active gateway/backend port listener; refusing to interfere.\n'+listener_diagnostics((GATEWAY_PORT,DOCKER_HOST_PORT)))
                    folder=out/key;folder.mkdir(exist_ok=True)
                    print('\n==',key,'==',flush=True)
                    img=existing['images'][model]
                    if backend=='docker':
                        owned.container=f'comet_wp1cap_{model}_{dt.datetime.now().strftime("%H%M%S")}_{os.getpid()}'
                        run(['docker','run','--rm','-d','--name',owned.container,'--network','bridge',
                             '-p',f'127.0.0.1:{DOCKER_HOST_PORT}:8085','--cpuset-cpus',str(srv),
                             '-e','TOKIO_WORKER_THREADS=1',img],log=folder/'docker_start.log',timeout=90)
                        # Docker backend exposes POST /infer only; gateway loadgen validates readiness/predictions.
                        topology=run(['docker','inspect','-f','{{.HostConfig.NetworkMode}}',owned.container]).stdout.strip()
                        must(topology=='bridge','Docker did not start in bridge networking')
                    route={'backend':backend,'model':model}
                    if backend=='docker':route['url']=f'http://127.0.0.1:{DOCKER_HOST_PORT}/infer'
                    routes=folder/'routes.json';atomic_json(routes,{str(i):route for i in range(3)})
                    env=os.environ.copy();env.update({'COMET_INGRESS_WORKERS':'1','COMET_WASM_WORKERS':'1',
                        'TOKIO_WORKER_THREADS':'1',f'COMET_{model.upper()}_WASM_PATH':str(LR_WASM if model=='lr' else RF_WASM)})
                    owned.handle=(folder/'ingress.log').open('w')
                    owned.ingress=subprocess.Popen(['taskset','-c',str(srv),str(ING),str(routes)],cwd=ROOT,env=env,
                        stdout=owned.handle,stderr=subprocess.STDOUT,start_new_session=True)
                    must(ready(f'http://127.0.0.1:{GATEWAY_PORT}/health',owned.ingress,30),f'{key} gateway not healthy; {folder}/ingress.log')
                    inference_ready(model,backend)
                    pids={'gateway':owned.ingress.pid}
                    if backend=='docker':pids['docker_backend']=docker_pid(owned.container)
                    baseline={k:parse_status(p) for k,p in pids.items()}
                    must(all(b.get('Cpus_allowed_list')==str(srv) for b in baseline.values()),'CPU pinning mismatch')
                    atomic_json(folder/'baseline_resources.json',baseline)
                    # Per supervisor WP1 4.3: no-op FIRST to assess gateway/loadgen headroom.
                    # WP1 4.3: measure no-op gateway/load-generator headroom without
                    # inventing a fixed supervisor cutoff. Retain failed calibrations.
                    # A failed highest-rate test triggers lower-rate diagnostics,
                    # never deletion or an automatic assertion of saturation.
                    fastest=max(args.rates)
                    initial=min(10000,fastest*args.noop_multiplier)
                    headroom_rates=sorted(set([initial,
                        min(10000,round(fastest*1.5)),
                        min(10000,round(fastest*1.25)),
                        fastest]),reverse=True)
                    tested=[]
                    for noop_rate in headroom_rates:
                        # The Rust no-op generator rejects rps*seconds > 15000.
                        # Float rounding at exactly 15000 can exceed the limit
                        # (e.g. 3600 * (15000/3600)). Stay safely below it.
                        noop_count_budget=14900
                        noop_duration=min(10.0, noop_count_budget/noop_rate)
                        must(1 <= round(noop_rate*noop_duration) <= 15000,
                             f'Invalid no-op request budget for {noop_rate} RPS')
                        noop_prefix=folder/f'noop_{noop_rate}'
                        # Preserve v1's original 4800 RPS record without renaming.
                        legacy=folder/'noop_before_inference'
                        if noop_rate==initial and legacy.with_suffix('.summary.json').exists():
                            noop_prefix=legacy
                        if not noop_prefix.with_suffix('.summary.json').exists():
                            print('RUN',key,'NOOP calibration',noop_rate,'RPS',flush=True)
                            noop_cmd=[GEN,'noop',f'http://127.0.0.1:{GATEWAY_PORT}/noop',
                                str(noop_rate),str(noop_duration),'3000','256',str(noop_prefix)]
                            noop_samples=resources_while(noop_cmd,folder/f'noop_{noop_rate}.log',pids,cli,60)
                            atomic_json(folder/f'noop_{noop_rate}.resources.json',noop_samples)
                        noop=json.loads(noop_prefix.with_suffix('.summary.json').read_text())
                        detail=records(noop_prefix.with_suffix('.requests.jsonl'))
                        good=(noop.get('successful_requests')==noop.get('offered_requests') and
                              all(noop.get(z,0)==0 for z in ('failed_requests','timed_out_requests','dropped_requests')))
                        item={'rps':noop_rate,'passed_zero_errors':good,'summary':noop,'details':detail,
                              'file':str(noop_prefix.relative_to(out))}
                        tested.append(item)
                        print('  NOOP',noop_rate,'RPS', 'PASS' if good else 'LOSS',
                              'success',noop.get('successful_requests'),'/',noop.get('offered_requests'),
                              'p99_sched_ms',detail.get('sched_p99_ms'),flush=True)
                        report['WP1'][f'{key}_noop_calibration']=tested
                        atomic_json(out/'state.json',report)
                        if good and noop_rate>fastest:
                            break
                    if not any(z['passed_zero_errors'] and z['rps']>fastest for z in tested):
                        # Not an outright error: inference can still be measured,
                        # but no WP1 acceptance claim is permitted.
                        reason=f'{key}: no verified no-op rate above fastest inference grid ({fastest} RPS)'
                        report['WP1'].setdefault('headroom_unverified',[]).append(reason)
                        print('HEADROOM UNVERIFIED:',reason,'; inference is exploratory',flush=True)
                        atomic_json(out/'state.json',report)
                    for rate in args.rates:
                        # Each model+backend+rate receives distinct but identical seed-42 trace.
                        count=round(rate*args.seconds)
                        trace,gold=prepare_trace(out,model,count)
                        precision_key=f'{model}_{backend}_rps{rate}'
                        formal=report['WP1'].setdefault('formal_precision',{})
                        # Check the persisted stopping report AND all raw artifacts,
                        # never blindly trust an in-memory progress counter.
                        earlier=[r for r in report['WP1']['runs'] if r['model']==model and r['backend']==backend and r['offered_rps']==rate]
                        if len(earlier)>=FORMAL_MIN_REPS:
                            previous=formal_ci(earlier,seed=42+rate)
                            done=previous['formal_acceptance'] or len(earlier)>=FORMAL_MAX_REPS
                            if done:
                                must(all((folder/f'rps{rate}_rep{r["repeat"]}').with_suffix('.summary.json').is_file() and
                                         (folder/f'rps{rate}_rep{r["repeat"]}').with_suffix('.requests.jsonl').is_file() for r in earlier),
                                     'Partial previous results; manual inspection required')
                                formal[precision_key]={**previous,'stopping_reason':
                                    'precision_met_after_minimum' if previous['formal_acceptance'] else 'maximum_60_reached_precision_unmet'}
                                atomic_json(out/'state.json',report)
                                print('RESUME RATE COMPLETE',precision_key,'n',len(earlier),'status',formal[precision_key]['stopping_reason'],flush=True)
                                continue
                        for rep in range(1,FORMAL_MAX_REPS+1):
                            prefix=folder/f'rps{rate}_rep{rep}'
                            if (prefix.with_suffix('.summary.json')).is_file() and (prefix.with_suffix('.requests.jsonl')).is_file():
                                must(any(r['model']==model and r['backend']==backend and r['offered_rps']==rate and r['repeat']==rep
                                         for r in report['WP1']['runs']),
                                     'Existing raw files without indexed result; manual reconciliation required')
                                print('EXISTS',key,rate,rep,'(resume; preserving)',flush=True)
                                continue
                            must(not prefix.with_suffix('.summary.json').exists() and not prefix.with_suffix('.requests.jsonl').exists(),
                                 'Partial previous result: manual investigation needed before resume')
                            # matching noop at fastest offered inference rate, when legal.
                            cmd=[GEN,trace,gold,'http',f'http://127.0.0.1:{GATEWAY_PORT}/infer',backend,
                                 str(rate),'3000',str(args.max_inflight),str(prefix)]
                            print('RUN',key,'rate',rate,'rep',rep,'n',count,flush=True)
                            samples=resources_while(cmd,folder/f'rps{rate}_rep{rep}.log',pids,cli,
                                timeout=max(150,args.seconds*4+40))
                            atomic_json(folder/f'rps{rate}_rep{rep}.resources.json',samples)
                            summary=json.loads(prefix.with_suffix('.summary.json').read_text())
                            raw=records(prefix.with_suffix('.requests.jsonl'))
                            offered=summary.get('offered_requests');success=summary.get('successful_requests',0)
                            correct=offered==count and success==count and all(summary.get(x,0)==0 for x in ('failed_requests','timed_out_requests','dropped_requests'))
                            row={'model':model,'backend':backend,'offered_rps':rate,'repeat':rep,
                                 'offered':offered,'success':success,'fail':summary.get('failed_requests'),
                                 'timeouts':summary.get('timed_out_requests'),'drops':summary.get('dropped_requests'),
                                 'achieved_success_rps_nominal':success/args.seconds,
                                 'achieved_goodput_rps':measured_goodput(prefix.with_suffix('.requests.jsonl'),success),
                                 'p50_ms':summary.get('p50_latency_ms'),
                                 'p95_ms':summary.get('p95_latency_ms'),'p99_ms':summary.get('p99_latency_ms'),
                                 'correctness_pass':correct,**raw,
                                 'loadgen_cpu_pct':cpu_util(samples,'loadgen'),'gateway_cpu_pct':cpu_util(samples,'gateway'),
                                 'docker_cpu_pct':cpu_util(samples,'docker_backend') if backend=='docker' else None,
                                 'max_gateway_threads':max((int(s['gateway'].get('Threads',0)) for s in samples if s.get('gateway') and s['gateway'].get('Threads','').isdigit()),default=None),
                                 'max_docker_threads':max((int(s['docker_backend'].get('Threads',0)) for s in samples if s.get('docker_backend') and s['docker_backend'].get('Threads','').isdigit()),default=None)}
                            report['WP1']['runs'].append(row)
                            atomic_json(out/'state.json',report)
                            print(' ', 'PASS' if correct else 'CAPACITY LOSS',
                                  'success',success,'/',offered,'p95',row['p95_ms'],'p99sched',row['sched_p99_ms'],flush=True)
                            collected=[r for r in report['WP1']['runs'] if r['model']==model and r['backend']==backend and r['offered_rps']==rate]
                            if len(collected)>=FORMAL_MIN_REPS:
                                stats=formal_ci(collected,seed=42+rate)
                                stop=stats['formal_acceptance'] or len(collected)>=FORMAL_MAX_REPS
                                stats['stopping_reason']=('precision_met_after_minimum' if stats['formal_acceptance']
                                   else ('maximum_60_reached_precision_unmet' if len(collected)>=FORMAL_MAX_REPS
                                         else 'continue_sampling'))
                                formal[precision_key]=stats
                                atomic_json(out/'state.json',report)
                                print('FORMAL CI',precision_key,'reps',len(collected),
                                    'precision',stats['all_metrics_precision_met'],'correct',stats['all_runs_correct'],
                                    'reason',stats['stopping_reason'],flush=True)
                                if stop:break
                        # stop rate ramp after all repetitions show definite loss; record lower rate first.
                        rr=[z for z in report['WP1']['runs'] if z['model']==model and z['backend']==backend and z['offered_rps']==rate]
                        if len(rr)>=args.repetitions and all(not z['correctness_pass'] for z in rr[-args.repetitions:]):
                            print('CAPACITY SATURATION CANDIDATE:',key,rate,'RPS; stopping higher rates for this backend',flush=True)
                            break
                    owned.close()
            # Evidence gate intentionally limits claims: supervisor has no fixed numerical cutoff.
            report['WP1']['status']='DATA COLLECTED; ACCEPTANCE REVIEW REQUIRED'
            if report['WP1'].get('headroom_unverified'):
                report['WP1']['status']='DATA COLLECTED; HEADROOM UNVERIFIED; ACCEPTANCE REVIEW REQUIRED'
            report['WP1']['interpretation']='Comparison requires verified achieved throughput, loadgen CPU accounting and substantial no-op headroom; no supervisor numerical cutoff was specified.'
            # Preserve historical blockers but distinguish resolved issues after successful resume.
            if report['WP1'].get('blockers'):
                report['WP1'].setdefault('resolved_previous_blockers',[]).extend(report['WP1']['blockers'])
                report['WP1']['blockers']=[]
        except Exception as e:
            report['WP1']['status']='BLOCKED'
            report['WP1']['blockers'].append(f'{type(e).__name__}: {e}')
            print('BLOCKED:',e,flush=True)
        finally:
            owned.close()
            atomic_json(out/'state.json',report)
            make_csv(out,report)
            make_report(out,report)
            print('\nFINAL:',report['WP1']['status'],'\nRESULTS:',out,flush=True)
            if report['WP1']['blockers']:print('BLOCKERS:',report['WP1']['blockers'],flush=True)
    return 0 if report['WP1']['status'].startswith('DATA COLLECTED') else 2

def config(args,srv,cli,existing):
    return {'rates':args.rates,'seconds':args.seconds,'repetitions':args.repetitions,'min_repetitions':FORMAL_MIN_REPS,'max_repetitions':FORMAL_MAX_REPS,'confidence':FORMAL_CONFIDENCE,'target_relative_halfwidth':FORMAL_TARGET,
            'service_cpu':srv,'client_cpu':cli,'max_inflight':args.max_inflight,
            'noop_multiplier':args.noop_multiplier,'images':existing['image_ids'],
            'loadgen_sha256':sha(GEN),'ingress_sha256':sha(ING),
            'LR_golden_sha256':sha(LR_GOLD),'LR_wasm_sha256':sha(LR_WASM),'RF_wasm_sha256':sha(RF_WASM)}

def make_csv(out,report):
    rows=report.get('WP1',{}).get('runs',[])
    if not rows:return
    cols=list(rows[0].keys())
    with (out/'wp1_capacity_summary.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=cols,extrasaction='ignore')
        writer.writeheader();writer.writerows(rows)

def make_report(out,report):
    lines=['# COMET-Wasm supervisor work-plan automation report','',
           f"WP1 status: **{report['WP1']['status']}**",'',
           '> WP1 acceptance cannot be inferred solely from zero-error runs; the supervisor requires proven gateway/load-generator headroom above the fastest backend and no client-side saturation.','',
           '## WP1 capacity evidence','',
           '| Model | Backend | Offered RPS | Rep | Correct | P95 ms | P99 ms | P99 scheduling ms | Client CPU % |',
           '|---|---|---:|---:|---|---:|---:|---:|---:|']
    for r in report['WP1'].get('runs',[]):
        lines.append('| '+ ' | '.join(str(v) for v in (r.get('model'),r.get('backend'),r.get('offered_rps'),
            r.get('repeat'),r.get('correctness_pass'),r.get('p95_ms'),r.get('p99_ms'),
            r.get('sched_p99_ms'),r.get('loadgen_cpu_pct'))) +' |')
    lines+=['','## Work-package acceptance status','',
            'WP1: '+report['WP1']['status'],
            'WP2: Evidence inventoried; acceptance not established',
            'WP3: Evidence inventoried; acceptance not established',
            'WP4: Existing kernels preserved; service crossover acceptance not established',
            'WP5: Not launched; requires approved WP1–WP4 evidence and scheduler implementation',
            'WP6: Not launched; requires frozen WP5 scheduler and held-out protocol','',
            '## Blockers','']
    lines += ['- '+x for x in report['WP1'].get('blockers',[])] or ['- None encountered in execution; final acceptance review still required.']
    (out/'REPORT.md').write_text('\n'.join(lines)+'\n')

def main():
    ap=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    ap.add_argument('--mode',choices=('auto','audit','status'),default='auto')
    ap.add_argument('--rates',type=int,nargs='+',default=[100,300,600,1200,2400],help='Exploratory RPS grid for WP1 capacity, not prescribed numerically by supervisor')
    ap.add_argument('--seconds',type=int,default=15,help='Seconds per load point, exploratory')
    ap.add_argument('--repetitions',type=int,default=3)
    ap.add_argument('--noop-multiplier',type=int,default=2)
    ap.add_argument('--max-inflight',type=int,default=128)
    ap.add_argument('--service-cpu',type=int)
    ap.add_argument('--client-cpu',type=int)
    ap.add_argument('--resume',type=Path)
    ap.add_argument('--resume-latest',action='store_true',help='Continue newest master run; keep existing measurements')
    args=ap.parse_args()
    if args.resume_latest:
        choices=sorted(OUTROOT.glob('*/state.json'))
        if not choices:
            print('SAFE STOP: No existing master run to resume',file=sys.stderr);return 2
        args.resume=choices[-1].parent
    if args.mode in ('audit','status'):
        print(json.dumps(evidence_audit(),indent=2))
        for x in sorted(OUTROOT.glob('*/state.json'))[-3:]:
            o=json.loads(x.read_text());print(x.parent,'WP1',o.get('WP1',{}).get('status'))
        return 0
    try:return run_auto(args)
    except (Blocker,subprocess.TimeoutExpired,FileNotFoundError,PermissionError) as e:
        print('SAFE STOP:',type(e).__name__,str(e),file=sys.stderr);return 2

if __name__=='__main__':sys.exit(main())
