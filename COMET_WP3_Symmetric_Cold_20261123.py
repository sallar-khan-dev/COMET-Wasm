#!/usr/bin/env python3
"""WP3 §6.2: matched client-facing cold-deployment diagnostic, LR, one tenant.

Both backends use the SAME COMET common gateway, GET /health then POST /infer,
identical reference inputs, CPU affinity, route schema and serving worker env.
Wasm process startup vs Docker container + gateway startup is reported accurately.
This does NOT measure WARM TENANT ADMISSION; the gateway is a static route table.
No source changes. Owns only its spawned processes and uniquely named containers.
"""
import argparse, csv, datetime as dt, fcntl, hashlib, json, math, os, pathlib, random, shutil, signal, socket, statistics, subprocess, sys, time, urllib.request
ROOT=pathlib.Path(__file__).resolve().parent
BASE=ROOT/'research_enhancement/automated_supervisor_workplan'
MAN=BASE/'wp2_lr_controlled_density_20261121/manifest.json'
WASM=ROOT/'wasm/tenant_lr_real/target/wasm32-unknown-unknown/release/tenant_lr_real.wasm'
ING=ROOT/'serving/common_ingress/target/release/comet_common_ingress'
GOLD=ROOT/'research_enhancement/v2_references/lr_iris_golden_v1.json'
OUTBASE=BASE/'wp3_symmetric_common_gateway_cold_20261123'
PORT=8200; BACK_PORT=18655

def sha(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for c in iter(lambda:f.read(1<<20),b''):h.update(c)
 return h.hexdigest()

def cmd(*args,timeout=45,check=True):
 r=subprocess.run([str(x) for x in args],capture_output=True,text=True,timeout=timeout)
 if check and r.returncode:raise RuntimeError(f'{args[0]} failed ({r.returncode}): {(r.stderr or r.stdout)[-600:]}')
 return r.stdout.strip()

def port_free(port):
 for f in ('/proc/net/tcp','/proc/net/tcp6'):
  try:lines=pathlib.Path(f).read_text().splitlines()[1:]
  except OSError:return False
  if any(x.split()[3]=='0A' and x.split()[1].split(':')[-1].upper()==f'{port:04X}' for x in lines if len(x.split())>3):return False
 return True

def save_json(p,obj):
 t=p.with_suffix(p.suffix+'.writing');t.write_text(json.dumps(obj,indent=2,default=str)+'\n');t.replace(p)

def save_csv(p,rows):
 if not rows:return
 fields=['backend','rep','elapsed_ms','gateway_health_ms','first_valid_ms','host_cpu','docker_image_id','wasm_sha256']
 t=p.with_suffix('.writing')
 with t.open('w',newline='') as f:
  w=csv.DictWriter(f,fields);w.writeheader();w.writerows(rows)
 t.replace(p)

def probe(url,payload=None,expected=None,expected_backend=None,deadline=30):
 last='';end=time.monotonic()+deadline
 while time.monotonic()<end:
  try:
   req=urllib.request.Request(url,data=payload,headers={'Content-Type':'application/json'} if payload else {},method='POST' if payload else 'GET')
   with urllib.request.urlopen(req,timeout=1) as res:
    if res.status!=200:raise ValueError(f'HTTP {res.status}')
    if payload:
     body=json.loads(res.read())
     if body.get('prediction')!=expected:raise RuntimeError('GOLDEN PREDICTION MISMATCH')
     if body.get('backend') != expected_backend:raise RuntimeError(f'WRONG SERVING BACKEND: {body.get("backend")!r}, expected {expected_backend!r}')
    return
  except (OSError,TimeoutError,ConnectionError) as e:last=str(e);time.sleep(.04)
  except RuntimeError:raise
  except Exception as e:last=str(e);time.sleep(.04)
 raise RuntimeError('HTTP readiness timeout: '+last)

def bootstrap_ci(vals,seed=123):
 n=len(vals); mean=statistics.mean(vals)
 if n<2 or mean<=0:return {'n':n,'mean_ms':mean,'student_t_pct':None,'bootstrap_pct':None,'accepted':False}
 # Student-t quantile from scipy when installed, conservative normal approximation if unavailable.
 try:
  from scipy.stats import t
  tcrit=float(t.ppf(.975,n-1)); method='student_t'
 except ImportError:
  return {'n':n,'mean_ms':mean,'student_t_pct':None,'bootstrap_pct':None,'accepted':False,'blocker':'scipy missing; cannot claim 95% Student-t'}
 tt=100*tcrit*statistics.stdev(vals)/(n**.5)/mean
 rng=random.Random(seed);bs=[]
 for _ in range(2000):bs.append(statistics.mean(vals[rng.randrange(n)] for __ in range(n)))
 bs.sort(); b=100*max(mean-bs[int(.025*2000)],bs[int(.975*2000)])/mean
 return {'n':n,'mean_ms':mean,'student_t_pct':tt,'bootstrap_pct':b,'accepted':tt<=2.5 and b<=2.5,'method':method}

def main():
 pa=argparse.ArgumentParser();pa.add_argument('--min-reps',type=int,default=20);pa.add_argument('--max-reps',type=int,default=60);pa.add_argument('--image',default='comet-wp1cap-lr:latest');a=pa.parse_args()
 if a.min_reps!=20 or a.max_reps!=60:pa.error('User-defined sampling policy is exactly 20..60')
 for p in (MAN,WASM,ING,GOLD):
  if not p.is_file():raise RuntimeError(f'preflight missing {p}')
 for tool in ('docker','taskset'):
  if not shutil.which(tool):raise RuntimeError(f'preflight missing {tool}')
 if not port_free(PORT) or not port_free(BACK_PORT):raise RuntimeError('COMET service port already occupied; no interference permitted')
 man=json.loads(MAN.read_text());imageid=cmd('docker','image','inspect','-f','{{.Id}}',a.image)
 if imageid!=man['docker_image_id']:raise RuntimeError('Frozen Docker image ID differs from accepted WP2 LR data')
 if sha(WASM)!=man['wasm_sha256']:raise RuntimeError('Frozen Wasm differs from accepted WP2 LR data')
 # WP2 used multitenant_server, NOT common_ingress. Do not compare the hashes of distinct servers.
 # The ingress SHA is recorded separately and must match across BOTH treatments.
 if sha(GOLD)!=man['golden_sha256']:raise RuntimeError('Frozen golden input differs from accepted WP2 LR data')
 cmd('docker','info','--format','{{.ServerVersion}}')
 cpus=sorted(os.sched_getaffinity(0)); cpu=man['cpu']
 if cpu not in cpus:raise RuntimeError(f'Frozen CPU {cpu} not allowed {cpus}')
 rec=json.loads(GOLD.read_text())['records'][0]
 payload=json.dumps({'request_id':'wp3-cold','tenant_id':0,'model':'lr','features':rec['features']}).encode()
 stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d_%H%M%S')+'_'+str(os.getpid());OUTBASE.mkdir(parents=True,exist_ok=True);out=OUTBASE/stamp;out.mkdir()
 rows=[];report={'work_package':'WP3 §6.2','purpose':'matched HTTP through common COMET gateway; cold deployment only','backend_topology':{'wasmtime':'fresh gateway process+engine+module+worker','docker':'fresh container+fresh gateway process+Docker bridge'},'min_reps':a.min_reps,'max_reps':a.max_reps,'cpu':cpu,'docker_image_id':imageid,'wasm_sha256':sha(WASM),'gateway_sha256':sha(ING),'wp2_server_is_distinct':'WP2 used multitenant_server, not common_ingress','cold_readiness_probes':['GET common-gateway /health','POST common-gateway /infer with golden prediction'],'limitation':'Does not measure warm tenant admission; no dynamic gateway admission API; Docker and Wasm execution units differ intrinsically','status':'RUNNING','blockers':[]}
 save_json(out/'manifest.json',report)
 with (OUTBASE/'.experiment.lock').open('a+') as lock:
  fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
  try:
   for rep in range(1,a.max_reps+1):
    if rep>a.min_reps and all(bootstrap_ci([x[metric] for x in rows if x['backend']==b])['accepted'] for b in ('wasmtime','docker') for metric in ('gateway_health_ms','first_valid_ms')):break
    order=['wasmtime','docker'] if rep%2 else ['docker','wasmtime']
    for backend in order:
     if rep>a.min_reps and all(bootstrap_ci([x[metric] for x in rows if x['backend']==backend])['accepted'] for metric in ('gateway_health_ms','first_valid_ms')):continue
     if not port_free(PORT) or not port_free(BACK_PORT):raise RuntimeError('Port claimed by another service; abort')
     container=f'comet_wp3_sym_{os.getpid()}_{rep}';proc=None;logfile=None
     route={'backend':backend,'model':'lr'}
     if backend=='docker':route['url']=f'http://127.0.0.1:{BACK_PORT}/infer'
     routes=out/f'route_{backend}.json';routes.write_text(json.dumps({'0':route})+'\n')
     env=dict(os.environ,COMET_INGRESS_WORKERS='1',COMET_WASM_WORKERS='1',TOKIO_WORKER_THREADS='1',COMET_LR_WASM_PATH=str(WASM))
     start=time.monotonic()
     try:
      if backend=='docker':
       cmd('docker','run','-d','--rm','--name',container,'--network','bridge','-p',f'127.0.0.1:{BACK_PORT}:8085','--cpuset-cpus',str(cpu),'--memory','128m','--pids-limit','16','-e','TOKIO_WORKER_THREADS=1',a.image,timeout=50)
      logfile=(out/f'{backend}_{rep:03d}_gateway.log').open('w')
      proc=subprocess.Popen(['taskset','-c',str(cpu),str(ING),str(routes)],cwd=ROOT,env=env,stdout=logfile,stderr=subprocess.STDOUT,start_new_session=True)
      probe(f'http://127.0.0.1:{PORT}/health',deadline=30);health=1000*(time.monotonic()-start)
      probe(f'http://127.0.0.1:{PORT}/infer',payload,rec['expected_prediction'],backend,deadline=30);elapsed=1000*(time.monotonic()-start)
      rows.append({'backend':backend,'rep':rep,'elapsed_ms':elapsed,'gateway_health_ms':health,'first_valid_ms':elapsed,'host_cpu':cpu,'docker_image_id':imageid,'wasm_sha256':sha(WASM)})
      save_csv(out/'trials.csv',rows)
      print(f'{backend} rep {rep} / 60 cold HTTP ready {elapsed:.2f} ms',flush=True)
     finally:
      if proc:
       if proc.poll() is None:
        os.killpg(proc.pid,signal.SIGTERM)
        try:proc.wait(timeout=5)
        except subprocess.TimeoutExpired:os.killpg(proc.pid,signal.SIGKILL);proc.wait(timeout=5)
      if logfile:logfile.close()
      if backend=='docker':cmd('docker','rm','-f',container,timeout=30,check=False)
      time.sleep(.08)
   stats={b:{metric:bootstrap_ci([x[metric] for x in rows if x['backend']==b]) for metric in ('gateway_health_ms','first_valid_ms')} for b in ('wasmtime','docker')}
   report['status']='MEASURED_SCOPE_LIMITED';report['statistics']=stats;report['recorded_repetitions']=len(rows)
   save_json(out/'RESULT.json',report)
   (out/'COMPLETE.txt').write_text('Matched cold /infer probe diagnostic completed; warm admission remains independent.\n')
   print('WP3 SYMMETRIC COMMON-GATEWAY COLD COMPLETE',stats,flush=True)
  except Exception as e:
   report['status']='SAFE_STOP';report['blockers'].append(repr(e));save_json(out/'RESULT.json',report);raise
  finally:save_json(out/'manifest.json',report)
if __name__=='__main__':
 try:main()
 except Exception as e:print('SAFE STOP',repr(e),file=sys.stderr);sys.exit(2)
