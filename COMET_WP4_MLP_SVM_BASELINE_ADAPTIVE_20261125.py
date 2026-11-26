#!/usr/bin/env python3
"""COMET-Wasm WP4 section 7: existing MLP/SVM light-end baselines.

Uses same gateway, Wasmtime and Docker native Rust model implementations,
same deterministic varied inference traces, single pinned CPU for server and
separate load-client CPU, valid golden predictions, and adaptive 20..60
repetitions with a 95% t CI target ±2.5% for P50/P95/P99 latency.

RF light-end baseline has already been collected in WP1. This run does not
claim to create scaled MLP/RF/SVM models, a compute crossover, or WP4 completion.
No source edits, no model training changes, no extrapolation. Save in new dir.
"""
import os, sys, json, csv, math, time, signal, hashlib, shutil, statistics
import subprocess, threading, datetime as dt, urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parent
OUTBASE=ROOT/'research_enhancement/reports/wp4_baseline_adaptive'
OUT=OUTBASE/(dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d_%H%M%S')+'_'+str(os.getpid()))
OUT.mkdir(parents=True,exist_ok=False)
GEN=ROOT/'research_enhancement/v2_loadgen/target/release/comet_v2_loadgen'
GATE=ROOT/'serving/common_ingress/target/release/comet_common_ingress'
RATE_GRID=(100,600,2400)
MODELS={
 'mlp':{'golden':ROOT/'research_enhancement/v2_references/mlp_breast_cancer_golden_v1.json',
        'wasm':ROOT/'wasm/tenant_mlp_real/target/wasm32-unknown-unknown/release/tenant_mlp_real.wasm',
        'docker':ROOT/'docker/mlp_server','image':'comet-wp4-mlp-baseline:20261125'},
 'svm':{'golden':ROOT/'research_enhancement/v2_references/svm_breast_cancer_golden_v1.json',
        'wasm':ROOT/'wasm/tenant_svm_real/target/wasm32-unknown-unknown/release/tenant_svm_real.wasm',
        'docker':ROOT/'docker/svm_server','image':'comet-wp4-svm-baseline:20261125'},
}
MIN_REPS,MAX_REPS=20,60
SECONDS=15
TARGET_PCT=2.5
PORT_GATE,PORT_DOCKER=8200,18585
SERVER_CPU,CLIENT_CPU=0,1

class Block(Exception):pass

def save(path,obj):
 p=Path(path); p.parent.mkdir(parents=True,exist_ok=True)
 q=p.with_suffix(p.suffix+'.writing');q.write_text(json.dumps(obj,indent=2,default=str)+'\n');q.replace(p)
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def run(argv,log=None,timeout=900,env=None,check=True):
 argv=[str(x) for x in argv]
 if log:
  with open(log,'w') as f: p=subprocess.run(argv,cwd=ROOT,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=timeout)
 else:p=subprocess.run(argv,cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=timeout)
 if check and p.returncode:raise Block(f'Exit {p.returncode}: {argv[0]}; {log if log else p.stdout[-1000:]}')
 return p

def ps(pid):
 try:
  d={'pid':pid};base=Path('/proc')/str(pid)
  for l in (base/'status').read_text().splitlines():
   if l.startswith(('Threads:','Cpus_allowed_list:','voluntary_ctxt_switches:','nonvoluntary_ctxt_switches:')):
    k,v=l.split(':',1);d[k]=v.strip()
  return d
 except OSError:return {'pid':pid,'missing':True}

def available(port):
 for f in ('/proc/net/tcp','/proc/net/tcp6'):
  for l in Path(f).read_text().splitlines()[1:]:
   fields=l.split()
   if fields[3]=='0A' and int(fields[1].split(':')[-1],16)==port:return False
 return True

def ready(url,timeout=30):
 until=time.monotonic()+timeout
 while time.monotonic()<until:
  try:
   with urllib.request.urlopen(url,timeout=1) as resp:
    if resp.status==200:return True
  except Exception:time.sleep(.15)
 return False

def p95_ci(x):
 n=len(x);avg=statistics.mean(x)
 if n<2:return {'n':n,'mean_ms':avg,'ci95_relative_halfwidth_pct':None,'precision_ok':False}
 try:
  from scipy.stats import t
  q=float(t.ppf(.975,n-1))
 except ImportError:q=2.0931  # conservative df19 for all n>=20
 half=q*statistics.stdev(x)/(n**.5)
 rel=(100*half/abs(avg) if avg else float('inf'))
 return {'n':n,'mean_ms':avg,'ci95_relative_halfwidth_pct':rel,'precision_ok':rel<=TARGET_PCT}

def golden_v2(model,cfg,folder):
 data=json.loads(cfg['golden'].read_text())
 assert isinstance(data.get('records'),list) and len(data['records'])>=100
 assert data.get('reference_method') and data.get('model_sha256')
 records=[]
 for i,entry in enumerate(data['records']):
  pred=entry.get('prediction')
  if type(pred)!=int:raise Block(f'Invalid independent reference prediction for {model} row {i}')
  records.append({'row_index':int(entry.get('id',i)),'features':entry['features'],
      'expected_prediction':pred,'ground_truth_label':-1})
 # Dataset labels are not reference oracles; sentinel -1 denotes unavailable labels.
 data_sha=hashlib.sha256(json.dumps([x['features'] for x in records],sort_keys=True,separators=(',',':')).encode()).hexdigest()
 g={'schema_version':'comet-v2-golden-v1','model':model,'dataset':'breast_cancer',
    'sample_count':len(records),'model_sha256':data['model_sha256'],
    'dataset_sha256':data_sha,'independent_reference_method':data['reference_method'],
    'note':'Ground-truth labels unavailable in this reference; -1 sentinel; prediction checked against independent reference.',
    'records':records}
 path=folder/f'{model}_golden_v2.json';save(path,g)
 return path

def trace(model,golden,rate,folder):
 prefix=folder/f'{model}_{rate}_trace.json'
 if not prefix.exists():run([sys.executable,ROOT/'research_enhancement/v2_workloads/generate_trace.py',
  '--golden',golden,'--output',prefix,'--count',str(rate*SECONDS),
  '--seed','42','--tenants','3'],folder/f'{model}_{rate}_trace_gen.log',timeout=120)
 return prefix

def sample_during(command,log,pids,timeout=120):
 sample=[];done=threading.Event()
 with open(log,'w') as f:
  p=subprocess.Popen(['taskset','-c',str(CLIENT_CPU)]+[str(x) for x in command],cwd=ROOT,
     stdout=f,stderr=subprocess.STDOUT,start_new_session=True)
  def observe():
   while not done.is_set():
    sample.append({'t_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
      **{k:ps(v) for k,v in {**pids,'loadgen':p.pid}.items()}})
    done.wait(.25)
  worker=threading.Thread(target=observe,daemon=True);worker.start()
  try:p.wait(timeout=timeout)
  except subprocess.TimeoutExpired:
   os.killpg(p.pid,signal.SIGTERM);raise Block('Timed out: '+str(log))
  finally:done.set();worker.join(timeout=2)
 if p.returncode:raise Block(f'Load generator exited {p.returncode}: {log}')
 return sample

class Services:
 def __init__(self):self.gateway=None;self.docker=None;self.log=None
 def stop(self):
  if self.gateway and self.gateway.poll() is None:
   try:os.killpg(self.gateway.pid,signal.SIGTERM)
   except ProcessLookupError:pass
   try:self.gateway.wait(timeout=8)
   except subprocess.TimeoutExpired:
    os.killpg(self.gateway.pid,signal.SIGKILL);self.gateway.wait()
  if self.log:self.log.close()
  if self.docker:
   run(['docker','stop','-t','2',self.docker],timeout=30,check=False)
  self.gateway=None;self.docker=None;self.log=None

def main():
 if not shutil.which('docker') or not shutil.which('cargo') or not shutil.which('taskset'):
  raise Block('Required Docker/Cargo/taskset missing')
 if not {SERVER_CPU,CLIENT_CPU}.issubset(os.sched_getaffinity(0)):
  raise Block('CPU0/CPU1 are not in current HPC affinity allocation')
 if not GEN.is_file() or not GATE.is_file():raise Block('Existing Rust loadgen/common ingress executable missing')
 if not available(PORT_GATE) or not available(PORT_DOCKER):
  raise Block('Ports 8200 or 18585 already occupied; refusing to interfere with existing services')
 for model,cfg in MODELS.items():
  for key in ('golden','wasm'):
   if not cfg[key].is_file():raise Block(f'{model}: missing {key} {cfg[key]}')
  if not (cfg['docker']/'Dockerfile').is_file():raise Block(f'{model}: Docker source missing')
 if run(['docker','info'],timeout=20,check=False).returncode:raise Block('Docker daemon not available')
 result={'scope':'WP4 §7: EXISTING MLP/SVM light baseline; RF baseline retained from WP1',
  'precision':{'student_t_ci95_relative_halfwidth_target_pct':TARGET_PCT,'min':MIN_REPS,'max':MAX_REPS,
    'metrics':['P50_ms','P95_ms','P99_ms'],'condition':'model x backend x offered RPS'},
  'rates':RATE_GRID,'seconds_per_repetition':SECONDS,
  'server_cpu':SERVER_CPU,'client_cpu':CLIENT_CPU,'results':[],
  'status':'RUNNING','not_yet_done':['scaled MLP/RF/SVM models','WP4 heavy density remeasurement','compute crossover validation']}
 save(OUT/'STATE.json',result)
 services=Services()
 try:
  for model,cfg in MODELS.items():
   ref=golden_v2(model,cfg,OUT)
   traces={rate:trace(model,ref,rate,OUT) for rate in RATE_GRID}
   for backend in ('wasmtime','docker'):
    if not available(PORT_GATE) or not available(PORT_DOCKER):raise Block('Expected service ports not free')
    section=OUT/f'{model}_{backend}';section.mkdir()
    try:
     if backend=='docker':
      # Use current Docker Rust implementation without modifying the model.
      if run(['docker','image','inspect',cfg['image']],check=False).returncode:
       print('BUILD Docker model',model,flush=True)
       run(['docker','build','-t',cfg['image'],str(cfg['docker'])],section/'docker_build.log',timeout=3600)
      services.docker=f'comet_wp4_{model}_{os.getpid()}'
      run(['docker','run','--rm','-d','--name',services.docker,'--network','bridge',
       '-p',f'127.0.0.1:{PORT_DOCKER}:8085','--cpuset-cpus',str(SERVER_CPU),cfg['image']],
        section/'docker_launch.log',timeout=60)
     route={'backend':backend,'model':model}
     if backend=='docker':route['url']=f'http://127.0.0.1:{PORT_DOCKER}/infer'
     routes={str(i):route for i in range(3)}
     save(section/'routes.json',routes)
     env=os.environ.copy();env.update({'COMET_INGRESS_WORKERS':'1','COMET_WASM_WORKERS':'1',
      f'COMET_{model.upper()}_WASM_PATH':str(cfg['wasm'])})
     services.log=open(section/'gateway.log','w')
     services.gateway=subprocess.Popen(['taskset','-c',str(SERVER_CPU),str(GATE),str(section/'routes.json')],
      cwd=ROOT,env=env,stdout=services.log,stderr=subprocess.STDOUT,start_new_session=True)
     if not ready(f'http://127.0.0.1:{PORT_GATE}/health'):
      raise Block('Gateway failed: '+str(section/'gateway.log'))
     record=json.loads(ref.read_text())['records'][0]
     body=json.dumps({'request_id':'wp4-oracle','tenant_id':0,'model':model,'features':record['features']}).encode()
     req=urllib.request.Request(f'http://127.0.0.1:{PORT_GATE}/infer',data=body,headers={'content-type':'application/json'})
     with urllib.request.urlopen(req,timeout=5) as response:got=json.loads(response.read())
     if got.get('backend')!=backend or got.get('prediction')!=record['expected_prediction']:
      raise Block(f'{model}/{backend}: reference prediction/origin failed: {got}')
     pids={'gateway':services.gateway.pid}
     if backend=='docker':
      pids['docker_backend']=int(run(['docker','inspect','-f','{{.State.Pid}}',services.docker]).stdout.strip())
     save(section/'baseline_resources.json',{k:ps(v) for k,v in pids.items()})
     print(f'WP4 {model}/{backend}: NOOP headroom 4800 RPS',flush=True)
     noop=section/'noop'
     samples=sample_during([GEN,'noop',f'http://127.0.0.1:{PORT_GATE}/noop',
       '4800',str(14900/4800),'3000','256',noop],section/'noop.log',pids,timeout=90)
     save(section/'noop.resources.json',samples)
     no=json.loads((section/'noop.summary.json').read_text())
     if no.get('offered_requests')!=no.get('successful_requests') or no.get('successful_requests')!=14900:
      raise Block(f'{model}/{backend}: no-op headroom failed, review {section}')
     for rate in RATE_GRID:
      records=[]
      for rep in range(1,MAX_REPS+1):
       prefix=section/f'rps{rate}_rep{rep:02d}'
       arguments=[GEN,traces[rate],ref,'http',f'http://127.0.0.1:{PORT_GATE}/infer',
         backend,str(rate),'3000','128',prefix]
       samples=sample_during(arguments,section/f'rps{rate}_rep{rep:02d}.log',pids,timeout=120)
       save(section/f'rps{rate}_rep{rep:02d}.resources.json',samples)
       d=json.loads(prefix.with_suffix('.summary.json').read_text())
       row={'model':model,'backend':backend,'rate':rate,'repetition':rep,
        'offered':d.get('offered_requests'),'success':d.get('successful_requests'),
        'failed':d.get('failed_requests'),'timeouts':d.get('timed_out_requests'),
        'dropped':d.get('dropped_requests'),
        'P50_ms':d.get('p50_latency_ms'),'P95_ms':d.get('p95_latency_ms'),'P99_ms':d.get('p99_latency_ms')}
       records.append(row)
       if rep>=MIN_REPS:
        ci={m:p95_ci([x[m] for x in records]) for m in ('P50_ms','P95_ms','P99_ms')}
        ok=all(z['precision_ok'] for z in ci.values())
        print(f'WP4 {model}/{backend} {rate} RPS run {rep}: '
          f'precision P95 ±{ci["P95_ms"]["ci95_relative_halfwidth_pct"]:.2f}% '
          f'P99 ±{ci["P99_ms"]["ci95_relative_halfwidth_pct"]:.2f}% '
          + ('PASS' if ok else 'CONTINUE'),flush=True)
        if ok or rep==MAX_REPS:
         result['results'].append({'model':model,'backend':backend,'rate':rate,
          'runs':rep,'precision':ci,'all_precision_ok':ok,'lost_requests':sum(x['offered']-x['success'] for x in records)})
         save(OUT/'STATE.json',result)
         break
    finally:services.stop();time.sleep(1)
  result['status']='BASELINE_COMPLETE';save(OUT/'STATE.json',result)
  print('WP4 existing MLP/SVM baseline COMPLETE; saved',OUT/'STATE.json',flush=True)
  print('NEXT per supervisor §7: scale existing MLP/RF/SVM models to span crossover, then repeat seven density levels.',flush=True)
 except Exception as e:
  result['status']='SAFE_STOP';result['blocker']=f'{type(e).__name__}: {e}';save(OUT/'STATE.json',result)
  raise
 finally:services.stop()

if __name__=='__main__':
 try:main()
 except Exception as exc:
  print('SAFE STOP:',exc,file=sys.stderr)
  print('New results preserved at:',OUT,file=sys.stderr)
  sys.exit(2)
