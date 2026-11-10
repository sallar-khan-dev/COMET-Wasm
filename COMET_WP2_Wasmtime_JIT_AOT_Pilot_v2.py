#!/usr/bin/env python3
"""COMET-Wasm supervisor WP2 §5.1: real paired Wasmtime JIT/AOT PSS pilot.

Uses exact Wasmtime 44 + repository's WasmWorkerPool implementation, same LR
module, same two deterministic predictions, same pinned CPU, same worker count.
Builds a separate temporary Rust harness; never changes COMET Rust sources.
Records process PSS and base/engine/module/worker attribution observationally.
AOT: Wasmtime Engine::precompile_module + unsafe Module::deserialize_file;
JIT: Module::from_file, both on Engine::default().
"""
import argparse, csv, datetime as dt, fcntl, hashlib, json, os, pathlib, select, shutil, statistics, subprocess, sys, time, traceback

ROOT=pathlib.Path(__file__).resolve().parent
OUTBASE=ROOT/'research_enhancement/automated_supervisor_workplan/wp2_jit_aot_pilot'
SRC=r'''use anyhow::Result;
use comet_worker_pool::WasmWorkerPool;
use std::{env,fs,io::{self,BufRead,Write},time::Instant};
use wasmtime::{Engine,Module};
fn main()->Result<()> {
 let a:Vec<String>=env::args().collect();
 anyhow::ensure!(a.len()>=3,"usage: <mode> <wasm> [precompiled] [workers]");
 let mode=&a[1]; let wasm=&a[2];
 if mode=="precompile" {
   let engine=Engine::default();
   let start=Instant::now();
   let bytes=engine.precompile_module(&fs::read(wasm)?)?;
   fs::write(&a[3],&bytes)?;
   println!("PRECOMPILED bytes={} elapsed_ns={}",bytes.len(),start.elapsed().as_nanos());
   return Ok(())
 }
 anyhow::ensure!(mode=="baseline"||mode=="jit"||mode=="aot","invalid mode");
 let workers:usize=a.get(4).map(|s|s.parse()).transpose()?.unwrap_or(1);
 let mut mark=|stage:&str| {println!("STAGE {}",stage);io::stdout().flush().unwrap(); let mut s=String::new();io::stdin().lock().read_line(&mut s).unwrap();};
 mark("baseline");
 let engine=Engine::default(); mark("engine");
 if mode=="baseline" {mark("ready");return Ok(())}
 let module=if mode=="jit" {Module::from_file(&engine,wasm).map_err(|e| anyhow::anyhow!("jit module load: {e:#}"))?}
 else {unsafe{Module::deserialize_file(&engine,&a[3]).map_err(|e| anyhow::anyhow!("aot module deserialize: {e:#}"))?}};
 mark("module");
 let pool=WasmWorkerPool::new(&engine,&module,workers)?;
 for (features,expected) in [([5.1,3.5,1.4,0.2],0),([6.7,3.0,5.2,2.3],1)] {
   let w=pool.worker(0).unwrap();let mut worker=w.lock().unwrap();
   let (result,_)=worker.infer_timed(&features)?;
   anyhow::ensure!(result==expected,"prediction mismatch {} != {}",result,expected);
 }
 println!("PREDICTIONS PASS");
 mark("ready");
 Ok(())
}
'''

def sha(path):
 h=hashlib.sha256()
 with open(path,'rb') as f:
  for b in iter(lambda:f.read(1<<20),b''):h.update(b)
 return h.hexdigest()
def command(args,**kw):
 p=subprocess.run([str(x) for x in args],capture_output=True,text=True,**kw)
 if p.returncode:raise RuntimeError(f'command failed {args}: {p.stderr[-2000:]} {p.stdout[-500:]}')
 return p
def memory(pid):
 out={'pss_kib':None,'rss_kib':None,'threads':None,'cpu_allowed':None}
 try:
  for line in pathlib.Path(f'/proc/{pid}/smaps_rollup').read_text().splitlines():
   if line.startswith('Pss:'):out['pss_kib']=int(line.split()[1])
   if line.startswith('Rss:'):out['rss_kib']=int(line.split()[1])
  for line in pathlib.Path(f'/proc/{pid}/status').read_text().splitlines():
   if line.startswith('Threads:'):out['threads']=int(line.split()[1])
   if line.startswith('Cpus_allowed_list:'):out['cpu_allowed']=line.split(':',1)[1].strip()
 except OSError as e:out['error']=str(e)
 return out

def run_mode(exe,mode,wasm,aot,workers,cpu,rep,nsamples,interval,out):
 args=[exe,mode,wasm,aot,str(workers)]
 p=subprocess.Popen([str(x) for x in args],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1,preexec_fn=lambda:os.sched_setaffinity(0,{cpu}))
 records=[]; stages={};prediction_pass=False
 try:
  for stage in (['baseline','engine','ready'] if mode=='baseline' else ['baseline','engine','module','ready']):
   ready,_,_=select.select([p.stdout],[],[],60)
   if not ready:raise RuntimeError(f'{mode} rep{rep} timeout awaiting {stage}, process={p.poll()}')
   while True:
    s=p.stdout.readline().strip()
    if s=='PREDICTIONS PASS':prediction_pass=True;continue
    if s!=f'STAGE {stage}':raise RuntimeError(f'{mode} rep{rep}: expected {stage}, got {s!r}')
    break
   series=[]
   for j in range(nsamples):
    if j:time.sleep(interval)
    z=memory(p.pid)
    records.append({'mode':mode,'rep':rep,'stage':stage,'sample':j,**z})
    if z['pss_kib'] is not None:series.append(z['pss_kib'])
   if len(series)!=nsamples:raise RuntimeError(f'could not read /proc/{p.pid}/smaps_rollup')
   stages[stage]=statistics.mean(series)
   p.stdin.write('\n');p.stdin.flush()
  p.wait(timeout=10)
  if p.returncode:raise RuntimeError(f'child {mode} exit {p.returncode}: {p.stderr.read()[-500:]}')
  if mode!='baseline' and not prediction_pass:raise RuntimeError('predictions not confirmed')
  return {'mode':mode,'rep':rep,'cpu':cpu,'workers':workers,'predictions_pass':prediction_pass,'pss_baseline_kib':stages['baseline'],'pss_engine_kib':stages['engine'],'pss_module_kib':stages.get('module'),'pss_ready_kib':stages['ready'],'engine_delta_kib':stages['engine']-stages['baseline'],'module_delta_kib':(stages.get('module') or stages['engine'])-stages['engine'],'worker_delta_kib':stages['ready']-(stages.get('module') or stages['engine'])},records
 finally:
  if p.poll() is None:
   p.terminate()
   try:p.wait(timeout=3)
   except subprocess.TimeoutExpired:p.kill();p.wait()
  for f in (p.stdin,p.stdout,p.stderr):
   if f:f.close()

def save_csv(path,rows):
 if not rows:return
 keys=list(dict.fromkeys(k for r in rows for k in r))
 with open(path,'w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(rows)

def main():
 ap=argparse.ArgumentParser(description=__doc__)
 ap.add_argument('--repetitions',type=int,default=20)
 ap.add_argument('--samples',type=int,default=5)
 ap.add_argument('--interval',type=float,default=0.2)
 ap.add_argument('--workers',type=int,default=1)
 ap.add_argument('--cpu',type=int)
 a=ap.parse_args()
 if min(a.repetitions,a.samples,a.workers)<1 or a.interval<=0:ap.error('positive repetitions/samples/workers and interval needed')
 allowed=sorted(os.sched_getaffinity(0));cpu=a.cpu if a.cpu is not None else allowed[0]
 if cpu not in allowed:ap.error(f'CPU {cpu} not allowed, available {allowed}')
 wasm=ROOT/'wasm/tenant_lr_real/target/wasm32-unknown-unknown/release/tenant_lr_real.wasm'
 pool=ROOT/'serving/worker_pool'
 if not wasm.is_file() or not (pool/'Cargo.toml').is_file():raise RuntimeError('Missing LR wasm or existing worker pool source')
 if not shutil.which('cargo'):raise RuntimeError('cargo is required on HPC')
 OUTBASE.mkdir(parents=True,exist_ok=True)
 lock=open(OUTBASE/'.run.lock','w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 out=OUTBASE/(dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d_%H%M%S')+'_'+str(os.getpid()));out.mkdir()
 project=out/'harness';(project/'src').mkdir(parents=True)
 (project/'Cargo.toml').write_text('[package]\nname="comet_wp2_aot_pss_pilot"\nversion="0.1.0"\nedition="2021"\n\n[dependencies]\nanyhow="1"\nwasmtime="44"\ncomet_worker_pool={path='+json.dumps(str(pool))+'}\n')
 (project/'src/main.rs').write_text(SRC)
 manifest={'scope':'Supervisor WP2 §5.1 Wasmtime JIT-loaded vs precompiled/AOT pilot','model':'lr','wasm_sha256':sha(wasm),'cpu':cpu,'workers':a.workers,'repetitions':a.repetitions,'samples_per_stage':a.samples,'interval_s':a.interval,'wasmtime_version':'44 in Cargo manifest','engine_config':'Engine::default() both conditions','aot_loader':'Engine::precompile_module then unsafe Module::deserialize_file, same engine config','jit_loader':'Module::from_file','source_repo_unchanged':True,'status':'RUNNING'}
 (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
 print('WP2 REAL JIT/AOT EXPERIMENT | output:',out,flush=True)
 print('BUILD separate Rust harness (same Wasmtime 44 and repository worker pool)',flush=True)
 # Reuse existing compiled Wasmtime dependencies while using a distinct binary name.
 env=dict(os.environ,CARGO_TARGET_DIR=str(ROOT/'serving/common_ingress/target'))
 with (out/'build.log').open('w') as log:
  p=subprocess.run(['cargo','build','--release','--manifest-path',str(project/'Cargo.toml')],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
 if p.returncode:raise RuntimeError(f'harness build failed; inspect {out}/build.log')
 exe=ROOT/'serving/common_ingress/target/release/comet_wp2_aot_pss_pilot'
 if not exe.is_file():raise RuntimeError('harness binary missing after build')
 aot=out/'tenant_lr_real.precompiled.cwasm'
 p=command([exe,'precompile',wasm,aot],timeout=90)
 manifest['aot_sha256']=sha(aot);manifest['aot_bytes']=aot.stat().st_size;manifest['precompile_stdout']=p.stdout.strip();manifest['harness_sha256']=sha(exe)
 (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
 results=[];samples=[]
 # Alternate order by repetition to reduce drift from systematic order effects.
 for rep in range(1,a.repetitions+1):
  modes=['baseline','jit','aot'] if rep%2 else ['baseline','aot','jit']
  for mode in modes:
   row,part=run_mode(exe,mode,wasm,aot,a.workers,cpu,rep,a.samples,a.interval,out)
   results.append(row);samples.extend(part)
   save_csv(out/'trial_summary.csv',results);save_csv(out/'samples.csv',samples)
   print(f'TRIAL {rep:02d}/{a.repetitions} {mode.upper()} PSS={row["pss_ready_kib"]:.1f} KiB; engine={row["engine_delta_kib"]:.1f}, module={row["module_delta_kib"]:.1f}, workers={row["worker_delta_kib"]:.1f}',flush=True)
 def values(mode,key):return [float(x[key]) for x in results if x['mode']==mode]
 stats={m:{'n':len(values(m,'pss_ready_kib')),'mean_ready_pss_kib':statistics.mean(values(m,'pss_ready_kib')),'sd_ready_pss_kib':statistics.stdev(values(m,'pss_ready_kib')) if len(values(m,'pss_ready_kib'))>1 else None,'mean_engine_delta_kib':statistics.mean(values(m,'engine_delta_kib')),'mean_module_delta_kib':statistics.mean(values(m,'module_delta_kib')),'mean_worker_delta_kib':statistics.mean(values(m,'worker_delta_kib'))} for m in ('baseline','jit','aot')}
 stats['mean_aot_minus_jit_pss_kib']=stats['aot']['mean_ready_pss_kib']-stats['jit']['mean_ready_pss_kib']
 stats['all_inference_predictions_pass']=all(x['predictions_pass'] for x in results if x['mode']!='baseline')
 stats['interpretation']='Only memory sensitivity of one LR Wasmtime model at one fixed worker count; not all-model WP2 acceptance; precompile artifact built outside benchmark; stage differences are within-process measurements, not independent attribution of OS shared mappings.'
 (out/'RESULT.json').write_text(json.dumps(stats,indent=2)+'\n');manifest['status']='COMPLETED';(out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
 (out/'REPORT.md').write_text('# WP2 §5.1 Wasmtime JIT/AOT measured memory pilot\n\n'+f'- Repetitions per condition: **{a.repetitions}**\n- One CPU: **{cpu}**, workers: **{a.workers}**\n- JIT mean ready PSS: **{stats["jit"]["mean_ready_pss_kib"]:.2f} KiB**\n- AOT mean ready PSS: **{stats["aot"]["mean_ready_pss_kib"]:.2f} KiB**\n- AOT minus JIT: **{stats["mean_aot_minus_jit_pss_kib"]:.2f} KiB**\n- All prediction checks: **{stats["all_inference_predictions_pass"]}**\n\nRaw samples: `samples.csv`; repetitions: `trial_summary.csv`; precompilation provenance: `manifest.json`.\n\nThis is a scoped configuration-sensitivity pilot, not WP2-wide acceptance.\n')
 print('\nFINAL: JIT/AOT REAL MEMORY PILOT COMPLETE',flush=True)
 print('REPORT:',out/'REPORT.md',flush=True)

if __name__=='__main__':
 try:main()
 except Exception as e:
  print('BLOCKED:',e,file=sys.stderr,flush=True)
  traceback.print_exc()
  sys.exit(2)
