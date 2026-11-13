#!/usr/bin/env python3
"""Supervisor WP3 §6.2: separate deployment cold-start and warm admission.

Cold Wasmtime: start existing COMET ingress, compile/load LR module, create
worker, then successful HTTP /infer probe. Cold Docker: `docker run` then
successful HTTP /infer probe. The paths differ structurally; report them
separately, not as equivalent end-to-end services.
Warm Wasmtime: existing Engine+Module, instantiate worker, then successful
HTTP /infer probe in a small companion harness. Warm Docker: `docker create`
outside timing, `docker start` then successful HTTP /infer probe.

Does not alter repository sources or kill unidentified processes; isolates
all own Docker containers, writes output incrementally and fails closed.
"""
import argparse, csv, datetime, fcntl, hashlib, json, os, pathlib, random, shutil, socket, statistics, subprocess, sys, time, urllib.request, urllib.error, traceback

ROOT=pathlib.Path(__file__).resolve().parent
OUTROOT=ROOT/'research_enhancement/automated_supervisor_workplan/wp3_cold_admission'
WASM=ROOT/'wasm/tenant_lr_real/target/wasm32-unknown-unknown/release/tenant_lr_real.wasm'
INGRESS=ROOT/'serving/common_ingress/target/release/comet_common_ingress'
POOL=ROOT/'serving/worker_pool'
GOLDEN=ROOT/'research_enhancement/v2_references/lr_iris_golden_v1.json'
IMAGE='comet-wp1cap-lr:latest'

# Warm harness uses the real project's WasmWorkerPool. A tiny HTTP adapter
# accepts the same functional POST /infer request used to probe Docker.
RUST=r'''use anyhow::{anyhow,Result};
use comet_worker_pool::WasmWorkerPool;
use serde_json::{Value,json};
use std::{env,io::{self,BufRead,Read,Write},net::TcpListener,time::Instant};
use wasmtime::{Engine,Module};
fn respond(mut conn:std::net::TcpStream, worker:&mut comet_worker_pool::WasmWorker)->Result<()> {
  conn.set_read_timeout(Some(std::time::Duration::from_secs(2)))?;
  let mut buf=vec![0_u8;32768];let mut len=0;
  let head_end=loop {let n=conn.read(&mut buf[len..])?;if n==0{return Err(anyhow!("closed request"))}len+=n;
    if let Some(p)=buf[..len].windows(4).position(|w|w==b"\r\n\r\n"){break p+4}
    if len>=buf.len(){return Err(anyhow!("request too large"))}
  };
  let headers=std::str::from_utf8(&buf[..head_end])?;
  if !headers.starts_with("POST /infer "){return Err(anyhow!("invalid probe path"))}
  let length:usize=headers.lines().find_map(|l|{let (k,v)=l.split_once(':')?;
      if k.eq_ignore_ascii_case("content-length"){v.trim().parse().ok()}else{None}}).ok_or_else(||anyhow!("missing length"))?;
  if length>10000{return Err(anyhow!("body too large"))}
  while len-head_end<length {let n=conn.read(&mut buf[len..])?;if n==0{return Err(anyhow!("body eof"))}len+=n;}
  let request:Value=serde_json::from_slice(&buf[head_end..head_end+length])?;
  let f=request["features"].as_array().ok_or_else(||anyhow!("missing features"))?;
  let vals:Vec<f32>=f.iter().map(|v|v.as_f64().map(|n|n as f32).ok_or_else(||anyhow!("bad float"))).collect::<Result<_>>()?;
  let (prediction,execution_time_ns)=worker.infer_timed(&vals)?;
  let result=json!({"prediction":prediction,"execution_time_ns":execution_time_ns});
  let body=result.to_string();
  write!(conn,"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",body.len(),body)?;
  conn.flush()?;Ok(())
}
fn main()->Result<()> {
 let args:Vec<String>=env::args().collect();anyhow::ensure!(args.len()==3,"usage: <cold|warm> <wasm>");
 let listener=TcpListener::bind("127.0.0.1:0")?;
 println!("PORT {}",listener.local_addr()?.port());io::stdout().flush()?;
 if args[1]=="warm" {
   let engine=Engine::default();let module=Module::from_file(&engine,&args[2])?;
   println!("PRELOADED");io::stdout().flush()?;
   let mut line=String::new();io::stdin().lock().read_line(&mut line)?;
   let at=Instant::now();let pool=WasmWorkerPool::new(&engine,&module,1)?;
   println!("INSTANCE_NS {}",at.elapsed().as_nanos());io::stdout().flush()?;
   let w=pool.worker(0).ok_or_else(||anyhow!("missing worker"))?;
   let mut worker=w.lock().map_err(|_|anyhow!("poisoned worker"))?;
   for stream in listener.incoming().take(1) {respond(stream?, &mut worker)?;}
 } else {
   let engine=Engine::default();let module=Module::from_file(&engine,&args[2])?;
   let pool=WasmWorkerPool::new(&engine,&module,1)?;
   let w=pool.worker(0).ok_or_else(||anyhow!("missing worker"))?;
   let mut worker=w.lock().map_err(|_|anyhow!("poisoned worker"))?;
   for stream in listener.incoming().take(1) {respond(stream?, &mut worker)?;}
 }
 Ok(())
}
'''

def now():return datetime.datetime.now(datetime.timezone.utc).isoformat()
def cmd(a,timeout=60,check=True,**kw):
 p=subprocess.run([str(x) for x in a],capture_output=True,text=True,timeout=timeout,**kw)
 if check and p.returncode:raise RuntimeError(f'{a[0]} exit={p.returncode}: {p.stderr[-900:]} {p.stdout[-400:]}')
 return p

def hash_file(p):
 h=hashlib.sha256();
 with open(p,'rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()

def probe(url,features,expected,deadline_s=15):
 payload=json.dumps({'features':features}).encode()
 end=time.monotonic()+deadline_s
 last='not attempted'
 while time.monotonic()<end:
  try:
   req=urllib.request.Request(url,payload,{'Content-Type':'application/json'},method='POST')
   with urllib.request.urlopen(req,timeout=.7) as r:
    data=json.loads(r.read());pred=data.get('prediction')
    if pred!=expected:raise RuntimeError(f'prediction mismatch {pred} vs oracle {expected}')
    return data
  except (urllib.error.URLError,TimeoutError,ConnectionError,OSError) as e:last=str(e);time.sleep(.04)
 raise RuntimeError(f'readiness timeout: {url}: {last}')

def cpu_preexec(cpu):return lambda:os.sched_setaffinity(0,{cpu})
def listener_occupied(port):
 with socket.socket() as s:return s.connect_ex(('127.0.0.1',port))==0

def save_csv(p,rows):
 if not rows:return
 keys=list(dict.fromkeys(k for row in rows for k in row))
 with p.open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(rows)

def main():
 pa=argparse.ArgumentParser(description=__doc__)
 pa.add_argument('--repetitions',type=int,default=20)
 pa.add_argument('--cpu',type=int)
 pa.add_argument('--docker-image',default=IMAGE)
 args=pa.parse_args()
 if args.repetitions<2:pa.error('at least 2 trials required')
 avail=sorted(os.sched_getaffinity(0));cpu=args.cpu if args.cpu is not None else avail[0]
 if cpu not in avail:pa.error(f'CPU {cpu} not available: {avail}')
 for p in (WASM,POOL/'Cargo.toml',GOLDEN,INGRESS):
  if not p.exists():raise RuntimeError(f'missing existing repository artifact {p}')
 for executable in ('cargo','docker'):
  if not shutil.which(executable):raise RuntimeError(f'missing {executable}')
 cmd(['docker','image','inspect',args.docker_image],timeout=15)
 if listener_occupied(8200):raise RuntimeError('port 8200 already owned; refusing to replace an unidentified gateway')
 OUTROOT.mkdir(parents=True,exist_ok=True)
 lock=(OUTROOT/'.experiment.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 out=OUTROOT/(datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M%S')+'_'+str(os.getpid()));out.mkdir()
 rows=[];manifest={'task':'Supervisor WP3 §6.2','timestamp':now(),'cpu':cpu,'repetitions':args.repetitions,'wasm_sha256':hash_file(WASM),'docker_image':args.docker_image,'docker_image_id':cmd(['docker','image','inspect','-f','{{.Id}}',args.docker_image]).stdout.strip(),'status':'BUILDING','definitions':{'wasmtime_deploy':'spawn real COMET common_ingress, load engine+module+worker, successful POST /infer','docker_deploy':'docker run new container, successful POST /infer to Docker server','wasmtime_admit':'engine and module already initialized, instantiate actual WasmWorker, then successful POST /infer to measurement harness','docker_admit':'docker create done before timer, docker start then successful POST /infer'},'caveat':'Cold path implementations are structurally different; warm harness HTTP is a small adapter, not COMET ingress. HTTP probe endpoints are matched by method and prediction, but no service-level latency comparison is claimed.'}
 (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
 print('WP3 §6.2 REAL COLD-START / WARM-ADMISSION EXPERIMENT',flush=True)
 print('RESULTS:',out,flush=True)
 project=out/'warm_harness';(project/'src').mkdir(parents=True)
 (project/'Cargo.toml').write_text('[package]\nname="comet_wp3_admission_harness"\nversion="0.1.0"\nedition="2021"\n[dependencies]\nanyhow="1"\nwasmtime="44"\nserde_json="1"\ncomet_worker_pool={path='+json.dumps(str(POOL))+'}\n')
 (project/'src/main.rs').write_text(RUST)
 env=dict(os.environ,CARGO_TARGET_DIR=str(ROOT/'serving/common_ingress/target'))
 with (out/'build.log').open('w') as log:
  p=subprocess.run(['cargo','build','--offline','--release','--manifest-path',str(project/'Cargo.toml')],env=env,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
  if p.returncode:
   print('Offline build unavailable, trying Cargo cache resolution',flush=True)
   p=subprocess.run(['cargo','build','--release','--manifest-path',str(project/'Cargo.toml')],env=env,cwd=ROOT,stdout=log,stderr=subprocess.STDOUT)
 if p.returncode:raise RuntimeError(f'harness build failure: {out}/build.log')
 exe=ROOT/'serving/common_ingress/target/release/comet_wp3_admission_harness'
 if not exe.exists():raise RuntimeError('built harness not found')
 manifest['harness_sha256']=hash_file(exe);manifest['status']='RUNNING';(out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
 rec=json.loads(GOLDEN.read_text())['records'][0]
 features=rec['features'];expected=rec['expected_prediction']
 routes=out/'cold_wasmtime_routes.json';routes.write_text(json.dumps({'0':{'backend':'wasmtime','model':'lr'}},indent=2)+'\n')
 own_containers=set()
 try:
  for rep in range(1,args.repetitions+1):
   # Alternate path order by repetition to reduce systematic drift.
   conditions=['wasmtime_deploy','docker_deploy','wasmtime_admit','docker_admit']
   if rep%2==0:conditions.reverse()
   for condition in conditions:
    name=f'comet_wp3_adm_{os.getpid()}_{rep}'
    service=None;created=False; t0=None
    try:
     if condition=='wasmtime_deploy':
      if listener_occupied(8200):raise RuntimeError('port 8200 unexpectedly occupied')
      cenv=dict(os.environ,COMET_INGRESS_WORKERS='1',COMET_WASM_WORKERS='1',COMET_LR_WASM_PATH=str(WASM))
      t0=time.monotonic_ns()
      log=(out/f'{condition}_rep{rep:02d}.service.log').open('w')
      service=subprocess.Popen(['taskset','-c',str(cpu),str(INGRESS),str(routes)],cwd=ROOT,env=cenv,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
      # COMET requires tenant_id 0 and model lr; Docker accepts features only.
      data={'request_id':f'wp3-{rep}','tenant_id':0,'model':'lr','features':features}
      payload=json.dumps(data).encode();deadline=time.monotonic()+20;err='none'
      while time.monotonic()<deadline:
       if service.poll() is not None:raise RuntimeError('ingress exited before readiness')
       try:
        req=urllib.request.Request('http://127.0.0.1:8200/infer',payload,{'Content-Type':'application/json'},method='POST')
        with urllib.request.urlopen(req,timeout=.7) as r:
         body=json.loads(r.read());
         if body.get('prediction')!=expected or body.get('backend')!='wasmtime':raise RuntimeError('cold Wasmtime readiness prediction/backend mismatch')
         break
       except (urllib.error.URLError,TimeoutError,OSError) as e:err=str(e);time.sleep(.04)
      else:raise RuntimeError('cold Wasmtime gateway readiness timeout '+err)
      elapsed=time.monotonic_ns()-t0;more={'http_probe':'POST common_ingress /infer'}
     elif condition=='docker_deploy':
      own_containers.add(name)
      t0=time.monotonic_ns()
      # Use dynamic port assigned by Docker; discover mapping after run.
      p=cmd(['docker','run','-d','--name',name,'--cpuset-cpus',str(cpu),'-p','127.0.0.1::8085',args.docker_image],timeout=35)
      port=cmd(['docker','port',name,'8085/tcp'],timeout=10).stdout.strip().rsplit(':',1)[-1]
      probe(f'http://127.0.0.1:{port}/infer',features,expected,20)
      elapsed=time.monotonic_ns()-t0;more={'http_probe':'POST Docker /infer','host_port':port}
     elif condition=='docker_admit':
      own_containers.add(name)
      cmd(['docker','create','--name',name,'--cpuset-cpus',str(cpu),'-p','127.0.0.1::8085',args.docker_image],timeout=20)
      created=True
      t0=time.monotonic_ns()
      cmd(['docker','start',name],timeout=25)
      port=cmd(['docker','port',name,'8085/tcp'],timeout=10).stdout.strip().rsplit(':',1)[-1]
      probe(f'http://127.0.0.1:{port}/infer',features,expected,20)
      elapsed=time.monotonic_ns()-t0;more={'http_probe':'POST Docker /infer','host_port':port,'create_excluded':True}
     else:
      service=subprocess.Popen(['taskset','-c',str(cpu),str(exe),'warm',str(WASM)],cwd=ROOT,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=(out/f'{condition}_rep{rep:02d}.stderr.log').open('w'),text=True,bufsize=1,start_new_session=True)
      line=service.stdout.readline().strip()
      if not line.startswith('PORT '):raise RuntimeError('harness did not announce PORT: '+line)
      port=int(line.split()[1]);line=service.stdout.readline().strip()
      if line!='PRELOADED':raise RuntimeError('harness did not preload: '+line)
      t0=time.monotonic_ns();service.stdin.write('START\n');service.stdin.flush()
      probe(f'http://127.0.0.1:{port}/infer',features,expected,20)
      elapsed=time.monotonic_ns()-t0
      inst=service.stdout.readline().strip()
      if not inst.startswith('INSTANCE_NS '):raise RuntimeError('missing instance timing: '+inst)
      more={'http_probe':'POST harness /infer','instance_ns':int(inst.split()[1]),'preloaded_engine_module':True}
     rows.append({'rep':rep,'condition':condition,'elapsed_ms':round(elapsed/1e6,6),'ready':True,'cpu':cpu,**more})
     save_csv(out/'trials.csv',rows)
     print(f'TRIAL {rep:02d}/{args.repetitions} {condition} READY ms={elapsed/1e6:.3f}',flush=True)
    except Exception as e:
     rows.append({'rep':rep,'condition':condition,'ready':False,'error':str(e),'cpu':cpu});save_csv(out/'trials.csv',rows)
     raise
    finally:
     if service:
      if service.poll() is None:
       service.terminate()
       try:service.wait(timeout=3)
       except subprocess.TimeoutExpired:service.kill();service.wait(timeout=2)
      if condition=='wasmtime_deploy':log.close()
      if service.stdin:service.stdin.close()
      if service.stdout:service.stdout.close()
     if name in own_containers:
      cmd(['docker','rm','-f',name],timeout=25,check=False)
      own_containers.remove(name)
  stats={}
  for c in ['wasmtime_deploy','docker_deploy','wasmtime_admit','docker_admit']:
   v=[float(x['elapsed_ms']) for x in rows if x['condition']==c and x.get('ready')]
   stats[c]={'n':len(v),'mean_ms':statistics.mean(v),'median_ms':statistics.median(v),'sd_ms':statistics.stdev(v) if len(v)>1 else None,'min_ms':min(v),'max_ms':max(v)}
  stats['definition_warning']=manifest['caveat'];stats['status']='DATA_COLLECTED_ACCEPTANCE_REVIEW'
  (out/'RESULT.json').write_text(json.dumps(stats,indent=2)+'\n')
  report=['# WP3 §6.2: Deployment cold start vs warm admission','',f'CPU: {cpu}; repetitions: {args.repetitions}; original model: LR.', '', '| Measurement | Mean milliseconds |', '|---|---:|']
  report += [f'| {c} | {stats[c]["mean_ms"]:.3f} |' for c in ('wasmtime_deploy','docker_deploy','wasmtime_admit','docker_admit')]
  report += ['', 'Warm Wasmtime internal instance creation is recorded separately in `trials.csv`.', 'This is a scope-limited WP3 timing experiment; do not combine deployment and admission measurements.', 'Readiness in all cases uses successful HTTP POST /infer and reference prediction.', '**Scope limitation:** '+manifest['caveat'], '**Acceptance:** Requires comparison with full real serving configuration and supervisor WP1–WP3 stop/go validation.', '']
  (out/'REPORT.md').write_text('\n'.join(report))
  manifest['status']='DATA_COLLECTED_ACCEPTANCE_REVIEW';(out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
  print('\nFINAL: WP3 §6.2 MEASUREMENTS COMPLETE; methodological review required',flush=True)
  print('REPORT:',out/'REPORT.md',flush=True)
 finally:
  for name in sorted(own_containers):cmd(['docker','rm','-f',name],timeout=30,check=False)

if __name__=='__main__':
 try:main()
 except Exception as e:
  print('BLOCKED:',e,file=sys.stderr,flush=True)
  traceback.print_exc()
  sys.exit(2)
