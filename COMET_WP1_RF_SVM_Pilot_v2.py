#!/usr/bin/env python3
"""Guarded COMET-Wasm WP1 RF/SVM common-ingress pilot.

Writes derived V2 reference copies and run artifacts only under a fresh run directory.
Starts owned, uniquely named containers and an owned ingress process;
never stops pre-existing processes. Does not alter source or old results.
No claim of supervisor WP1 completion: this is the RF/SVM pilot checkpoint.
"""
import argparse
import csv
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parent
GEN = ROOT/'research_enhancement/v2_loadgen/target/release/comet_v2_loadgen'
ING = ROOT/'serving/common_ingress/target/release/comet_common_ingress'
TRACE_GEN = ROOT/'research_enhancement/v2_workloads/generate_trace.py'
GOLD_DIR = ROOT/'research_enhancement/v2_references'
PORT = 8200
DOCKER_PORT = 18585
MODEL_CONFIG = {
    'rf': {'wasm': ROOT/'wasm/tenant_rf_real/target/wasm32-unknown-unknown/release/tenant_rf_real.wasm',
           'docker_dir': ROOT/'docker/rf_server', 'image':'comet-wp1-rf:latest', 'gold':'rf_breast_cancer_golden_v1.json'},
    'svm': {'wasm': ROOT/'wasm/tenant_svm_real/target/wasm32-unknown-unknown/release/tenant_svm_real.wasm',
           'docker_dir': ROOT/'docker/svm_server', 'image':'comet-wp1-svm:latest', 'gold':'svm_breast_cancer_golden_v1.json'},
}

class Blocked(RuntimeError): pass

def require(condition, message):
    if not condition: raise Blocked(message)

def command(args, *, log=None, env=None, timeout=None, check=True):
    if log is None:
        return subprocess.run([str(x) for x in args], cwd=ROOT, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, timeout=timeout, check=check)
    with open(log,'w') as f:
        result=subprocess.run([str(x) for x in args],cwd=ROOT,env=env,
                              stdout=f,stderr=subprocess.STDOUT,timeout=timeout)
    if check and result.returncode: raise Blocked(f'Command failed with exit {result.returncode}; log: {log}')
    return result

def request(url, payload=None, timeout=2):
    try:
        body=None if payload is None else json.dumps(payload).encode()
        req=urllib.request.Request(url,data=body,headers={'Content-Type':'application/json'} if body else {},method='POST' if body else 'GET')
        with urllib.request.urlopen(req,timeout=timeout) as res:
            return res.status, res.read().decode(errors='replace')
    except Exception: return None,None

def wait_url(url, proc=None, timeout=25):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        if proc is not None and proc.poll() is not None: return False
        code,_=request(url)
        if code==200: return True
        time.sleep(.25)
    return False

def port_free(port):
    sock=socket.socket();sock.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
    try: sock.bind(('127.0.0.1',port));return True
    except OSError: return False
    finally: sock.close()

def cpus():
    allowed=sorted(os.sched_getaffinity(0))
    require(bool(allowed),'No allowed CPU found')
    return allowed[0]

def hashfile(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()

def prepare_v2_goldens(out):
    """Adapt legacy independent RF/SVM references; never infer predictions.

    Dataset fingerprint is computed over verified (ID, features, label) tuples,
    not claimed to be the SHA-256 of the original dataset file.
    """
    legacy = {}
    for model in ('rf', 'svm'):
        path = GOLD_DIR / MODEL_CONFIG[model]['gold']
        raw = json.loads(path.read_text())
        require(raw.get('dataset') == 'breast_cancer', f'{model} unexpected dataset')
        require(raw.get('schema_version') is None, f'{model} is not legacy format; review instead')
        require(isinstance(raw.get('model_sha256'), str) and len(raw['model_sha256']) == 64,
                f'{model} model fingerprint missing')
        rec = raw.get('records')
        require(isinstance(rec, list) and len(rec) == raw.get('n_records') and len(rec) >= 2,
                f'{model} invalid record count')
        ids = [r.get('id') for r in rec]
        require(ids == list(range(len(rec))), f'{model} rows not sequential from zero')
        for r in rec:
            require(isinstance(r.get('features'), list) and len(r['features']) == 30,
                    f'{model} invalid feature dimensionality')
            require(type(r.get('prediction')) is int and -2**31 <= r['prediction'] < 2**31,
                    f'{model} invalid reference prediction')
            require(all(type(x) in (int, float) and __import__('math').isfinite(x)
                        for x in r['features']), f'{model} nonfinite features')
        legacy[model] = raw

    rf = legacy['rf']['records']
    svm = legacy['svm']['records']
    for a,b in zip(rf,svm):
        require(a['id'] == b['id'] and a['features'] == b['features'],
                f'Dataset mismatch between RF and SVM row {a["id"]}; refusing conversion')
        require(type(a.get('dataset_label')) is int,
                f'RF row {a["id"]} has no independently supplied dataset label')

    # Fingerprint *verified reference rows*, NOT the original dataset file bytes.
    dataset_payload = [{'id':r['id'], 'features':r['features'],
                        'label':r['dataset_label']} for r in rf]
    blob = json.dumps(dataset_payload, sort_keys=True, separators=(',', ':'),
                      allow_nan=False).encode()
    reference_rows_digest = hashlib.sha256(blob).hexdigest()
    paths = {}
    for model in ('rf','svm'):
        original = legacy[model]
        records = [
            {'row_index':r['id'], 'features':r['features'],
             'expected_prediction':r['prediction'],
             'ground_truth_label':rf[i]['dataset_label']}
            for i,r in enumerate(original['records'])
        ]
        prepared = {
            'schema_version':'comet-v2-golden-v1',
            'model':model,
            'dataset':'breast_cancer',
            'reference_method':original.get('reference_method'),
            'reference_status':original.get('reference_status'),
            'model_sha256':original['model_sha256'],
            'dataset_sha256':reference_rows_digest,
            'sample_count':len(records),
            'fingerprint_scope':'sha256 of canonical verified reference (id, features, label) rows, NOT original dataset file',
            'source_legacy_golden_sha256':hashfile(GOLD_DIR / MODEL_CONFIG[model]['gold']),
            'source_reference_status':original.get('reference_status'),
            'records':records,
        }
        target = out / f'{model}_golden_v2_adapted.json'
        with target.open('x') as f:
            json.dump(prepared, f, indent=2, allow_nan=False)
            f.write('\n')
        paths[model] = target
    return paths

def get_count(s):
    return {k:s.get(k) for k in ('offered_requests','successful_requests','failed_requests','timed_out_requests','dropped_requests','p50_latency_ms','p95_latency_ms','p99_latency_ms')}

def validate_summary(path, expected):
    require(path.exists(),f'Load generator produced no summary: {path}')
    obj=json.loads(path.read_text())
    count=get_count(obj)
    require(count['offered_requests']==expected,f'Wrong request count: {count}')
    require(count['successful_requests']==expected and all(count[k]==0 for k in ('failed_requests','timed_out_requests','dropped_requests')),
            f'Correctness/load acceptance failed: {count}')
    require(isinstance(count['p95_latency_ms'],(int,float)),f'Missing P95: {count}')
    return obj

def procinfo(pid):
    p=Path('/proc')/str(pid)
    data={}
    if not p.exists():return data
    for line in (p/'status').read_text().splitlines():
        if line.startswith(('Threads:', 'Cpus_allowed_list:', 'voluntary_ctxt_switches:', 'nonvoluntary_ctxt_switches:')):
            k,v=line.split(':',1); data[k]=v.strip()
    return data

def docker_procinfo(name):
    r=command(['docker','inspect','-f','{{.State.Pid}}',name],check=False)
    if r.returncode:return {'error':'docker inspect failed'}
    try:return procinfo(int(r.stdout.strip()))
    except ValueError:return {'error':'invalid docker pid'}

def start_ingress(routes, run, model, wasm_path, cpu):
    env=os.environ.copy()
    env.update({'COMET_INGRESS_WORKERS':'1','COMET_WASM_WORKERS':'1','TOKIO_WORKER_THREADS':'1',
                f'COMET_{model.upper()}_WASM_PATH':str(wasm_path)})
    logfile=open(run/'ingress.log','w')
    proc=subprocess.Popen(['taskset','-c',str(cpu),str(ING),str(routes)],cwd=ROOT,
                          stdout=logfile,stderr=subprocess.STDOUT,env=env,start_new_session=True)
    if not wait_url(f'http://127.0.0.1:{PORT}/health',proc=proc):
        logfile.close();raise Blocked('Ingress failed health check; inspect ingress.log')
    return proc,logfile

def stop_process(proc,logfile):
    if proc is not None and proc.poll() is None:
        try:os.killpg(proc.pid,signal.SIGTERM)
        except ProcessLookupError:pass
        try:proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:os.killpg(proc.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            proc.wait(timeout=5)
    if logfile and not logfile.closed: logfile.close()

def run_suite(args):
    require(ROOT.name=='wasiMultitenant',f'Expected repo root wasiMultitenant, got {ROOT}')
    for tool in ('docker','taskset','python3'):
        require(shutil.which(tool) is not None,f'Missing {tool}')
    require(GEN.is_file() and os.access(GEN,os.X_OK),f'Missing executable: {GEN}')
    require(ING.is_file() and os.access(ING,os.X_OK),f'Missing executable: {ING}')
    require(TRACE_GEN.is_file(),'Missing deterministic trace generator')
    require(port_free(PORT) and port_free(DOCKER_PORT),f'Port {PORT} or {DOCKER_PORT} busy; will not disturb existing service')
    require(command(['docker','info'],check=False).returncode==0,'Docker daemon inaccessible')
    require(args.requests>=1000 and args.requests<=15000,'--requests must be 1000..15000')
    require(1<=args.tenants<=10,'--tenants must be 1..10')
    require(1<=args.reps<=5,'--reps must be 1..5 (pilot only)')
    require(args.rps and all(1<=r<=1200 for r in args.rps),'RPS must be 1..1200')
    cpu=cpus()
    stem=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d_%H%M%S')+'_'+str(os.getpid())
    out=ROOT/'research_enhancement/wp1_rf_svm_pilot_runs'/stem
    out.mkdir(parents=True,exist_ok=False)
    print('WP1 RF/SVM PILOT | output:',out,flush=True)
    info={'scope':'Supervisor WP1 RF/SVM common-gateway pilot, not full WP1 acceptance',
          'cpu':cpu,'rps':args.rps,'requests':args.requests,'reps':args.reps,'tenants':args.tenants,
          'git_head':command(['git','rev-parse','HEAD']).stdout.strip(), 'runs':[], 'blockers':[], 'status':'INCOMPLETE'}
    (out/'parameters.json').write_text(json.dumps(info,indent=2))
    # Claim an exclusive lock across cooperating WP1 pilots; never touch other process locks.
    lockpath=ROOT/'research_enhancement/.comet_wp1_rf_svm_pilot.lock'
    with open(lockpath,'w') as lock:
      try:fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
      except BlockingIOError:raise Blocked('Another matching WP1 pilot holds the lock')
      container=None;proc=None;logfile=None
      try:
        # Build both images if absent, without modifying source; Docker only uses its internal bridge.
        for model,conf in MODEL_CONFIG.items():
            img=args.rf_image if model=='rf' else args.svm_image
            require(conf['wasm'].is_file(),f'Missing {model} Wasm artifact: {conf["wasm"]}')
            require((GOLD_DIR/conf['gold']).is_file(),f'Missing {model} golden: {conf["gold"]}')
            if command(['docker','image','inspect',img],check=False).returncode:
                require(args.build_images,f'Image {img} missing. Rerun with --build-images or --{model}-image NAME')
                print('Building image',img,flush=True)
                command(['docker','build','-t',img,str(conf['docker_dir'])],log=out/f'build_{model}.log',timeout=1800)
            conf['selected_image']=img
            info[f'{model}_wasm_sha256']=hashfile(conf['wasm'])
            info[f'{model}_golden_sha256']=hashfile(GOLD_DIR/conf['gold'])
            info[f'{model}_image']=img
            info[f'{model}_docker_image_id']=command(['docker','image','inspect','-f','{{.Id}}',img]).stdout.strip()
        adapted_goldens = prepare_v2_goldens(out)
        for model,conf in MODEL_CONFIG.items():
          print('\n=== PILOT',model.upper(),'===',flush=True)
          golden=adapted_goldens[model]
          trace=out/f'{model}.trace.json'
          command([sys.executable,TRACE_GEN,'--golden',golden,'--output',trace,
                   '--count',args.requests,'--seed','42','--tenants',args.tenants],log=out/f'{model}_trace.log')
          command([GEN,trace,golden],log=out/f'{model}_trace_validation.log',timeout=180)
          for backend in ('wasmtime','docker'):
            require(port_free(PORT),f'Ingress port {PORT} already in use')
            require(port_free(DOCKER_PORT),f'Docker mapped port {DOCKER_PORT} already in use')
            if backend=='docker':
                container=f'comet_wp1_{model}_{stem}'
                command(['docker','run','--rm','-d','--name',container,'--network','bridge',
                         '-p',f'127.0.0.1:{DOCKER_PORT}:8085','--cpuset-cpus',str(cpu),
                         '-e','TOKIO_WORKER_THREADS=1',conf['selected_image']],log=out/f'{model}_docker_start.log',timeout=60)
                code,_=request(f'http://127.0.0.1:{DOCKER_PORT}/infer',{'features':[0.0]*30})
                # 200 requires model's HTTP endpoint and first-stage Rust decoder to be live.
                require(code==200,f'{model} Docker backend not reachable on mapped bridge port {DOCKER_PORT}')
                inspect=command(['docker','inspect','-f','{{.HostConfig.NetworkMode}}',container]).stdout.strip()
                require(inspect=='bridge',f'Docker networking is not bridge: {inspect}')
            routes=out/f'{model}_{backend}_routes.json'
            route={'backend':backend,'model':model}
            if backend=='docker':route['url']=f'http://127.0.0.1:{DOCKER_PORT}/infer'
            routes.write_text(json.dumps({str(k):route for k in range(args.tenants)},indent=2))
            try:
              proc,logfile=start_ingress(routes,out,model,conf['wasm'],cpu)
              resources={'ingress':procinfo(proc.pid),'docker':docker_procinfo(container) if container else None}
              (out/f'{model}_{backend}_resources.json').write_text(json.dumps(resources,indent=2))
              require(resources['ingress'].get('Cpus_allowed_list') == str(cpu),
                      f'Ingress CPU affinity differs from expected CPU {cpu}')
              if backend=='docker':
                  require(resources['docker'].get('Cpus_allowed_list') == str(cpu),
                          f'Docker CPU affinity differs from expected CPU {cpu}')
              # Each load run must independently verify golden parity and 0 errors.
              for rps in args.rps:
                for rep in range(1,args.reps+1):
                  name=f'{model}_{backend}_{rps}rps_rep{rep}'
                  prefix=out/name
                  env=os.environ.copy();env['COMET_LOADGEN_WORKERS']='1'
                  print('RUN',name,flush=True)
                  command(['taskset','-c',str(cpu),GEN,trace,golden,'http',
                           f'http://127.0.0.1:{PORT}/infer',backend,str(rps),'3000','64',str(prefix)],
                          log=out/f'{name}.log',env=env,timeout=max(90,int(args.requests/rps)*4+30))
                  result=validate_summary(out/f'{name}.summary.json',args.requests)
                  print(' PASS',get_count(result),flush=True)
                  info['runs'].append({'model':model,'backend':backend,'rps':rps,'rep':rep,**get_count(result)})
                  (out/'checkpoint.json').write_text(json.dumps(info,indent=2))
              # Validate no-op headroom above max offered load; do not assume headroom proof for max server capacity.
              if backend=='wasmtime':
                  noop_rps=min(2400,max(args.rps)*4)
                  noop=out/f'{model}_noop_{noop_rps}'
                  command(['taskset','-c',str(cpu),GEN,'noop',f'http://127.0.0.1:{PORT}/noop',
                           str(noop_rps),'5','3000','128',str(noop)],log=out/f'{model}_noop.log',timeout=40)
                  ns=json.loads((out/f'{model}_noop_{noop_rps}.summary.json').read_text())
                  validate_summary(out/f'{model}_noop_{noop_rps}.summary.json',ns['offered_requests'])
                  info[f'{model}_noop']={'rps':noop_rps,**get_count(ns)}
            finally:
              stop_process(proc,logfile);proc=None;logfile=None
              if container:
                command(['docker','stop','-t','3',container],log=out/f'{model}_docker_stop.log',timeout=15,check=False)
                container=None
          print('MODEL PILOT PASS',model,flush=True)
        info['status']='PILOT PASS - not full supervisor WP1 acceptance'
      except Exception as e:
        info['status']='BLOCKED'
        info['blockers'].append(f'{type(e).__name__}: {e}')
        print('BLOCKED:',e,flush=True)
      finally:
        stop_process(proc,logfile)
        if container:command(['docker','stop','-t','3',container],log=out/'cleanup_docker.log',timeout=15,check=False)
        (out/'FINAL_GATE.json').write_text(json.dumps(info,indent=2))
        with (out/'comparison.csv').open('w',newline='') as f:
            fields=['model','backend','rps','rep','offered_requests','successful_requests','failed_requests','timed_out_requests','dropped_requests','p50_latency_ms','p95_latency_ms','p99_latency_ms']
            w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(info['runs'])
        print('\nFINAL:',info['status'],'\nRESULTS:',out,flush=True)
        if info['blockers']: print('BLOCKERS:',info['blockers'],flush=True)
    return 0 if info['status'].startswith('PILOT PASS') else 2

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--requests',type=int,default=1500,help='Per run, 1000..15000')
    ap.add_argument('--rps',type=int,nargs='+',default=[50,100,300])
    ap.add_argument('--reps',type=int,default=2)
    ap.add_argument('--tenants',type=int,default=3)
    ap.add_argument('--rf-image',default='comet-wp1-rf:latest')
    ap.add_argument('--svm-image',default='comet-wp1-svm:latest')
    ap.add_argument('--build-images',action='store_true',help='Build missing Docker images using existing source Dockerfiles')
    args=ap.parse_args()
    try:return run_suite(args)
    except Exception as e:
        print('PREFLIGHT BLOCKED:',e,file=sys.stderr)
        return 2

if __name__=='__main__':sys.exit(main())
