#!/usr/bin/env python3
"""Supervisor WP2 §5.1: JIT/AOT memory pilot with adaptive precision 20..60,
freeze current deployed mode, then rerun existing supervisor evidence gate.
No previous experiment changes and no automatic WP4 launch.
"""
import os,sys,json,math,statistics,subprocess,datetime as dt,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parent
OUT=(ROOT/'research_enhancement/reports/wp2_jit_aot_precision'/
     (dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d_%H%M%S')+'_'+str(os.getpid())))
OUT.mkdir(parents=True,exist_ok=False)
MODELS={m:ROOT/f'wasm/tenant_{m}_real/target/wasm32-unknown-unknown/release/tenant_{m}_real.wasm'
        for m in ('lr','rf')}
PROBE=r'''use anyhow::{Context,Result};
use wasmtime::{Engine,Module,Instance,Store};
use std::{env,fs,thread,time::Duration,time::Instant};
fn pss()->Result<f64>{
 let s=fs::read_to_string("/proc/self/smaps_rollup")?;
 let l=s.lines().find(|l|l.starts_with("Pss:")).context("No Pss")?;
 Ok(l.split_whitespace().nth(1).context("No Pss value")?.parse::<f64>()?/1024.0)
}
fn settle()->Result<f64>{thread::sleep(Duration::from_millis(50));pss()}
fn main()->Result<()>{
 let a:Vec<String>=env::args().collect();
 anyhow::ensure!(a.len()==4,"usage: prepare|jit|aot input.wasm output.cwasm");
 let eng=Engine::default();
 if a[1]=="prepare"{
    let serialized=eng.precompile_module(&fs::read(&a[2])?)?;
    fs::write(&a[3],&serialized)?;
    println!("{}",serde_json::json!({"compiled_bytes":serialized.len()}));return Ok(())
 }
 anyhow::ensure!(a[1]=="jit"||a[1]=="aot","mode must be jit or aot");
 let after_engine=settle()?;
 let start=Instant::now();
 let module=if a[1]=="jit"{Module::from_file(&eng,&a[2])?}
    else{unsafe{Module::deserialize_file(&eng,&a[3])?}};
 let module_load_ns=start.elapsed().as_nanos();
 let after_module=settle()?;
 let mut held=Vec::new();
 for _ in 0..2{
   let mut st=Store::new(&eng,());
   let i=Instance::new(&mut st,&module,&[])?;
   held.push((st,i));
 }
 let after_instances=settle()?;
 println!("{}",serde_json::json!({
  "module_load_ns":module_load_ns,
  "engine_pss_mib":after_engine,
  "module_incremental_pss_mib":after_module-after_engine,
  "two_instance_incremental_pss_mib":after_instances-after_module,
  "total_pss_mib":after_instances
 }));
 Ok(())
}'''
def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for chunk in iter(lambda:f.read(1048576),b''):h.update(chunk)
 return h.hexdigest()
def run(args,log,env=None,timeout=1200):
 with log.open('w') as f:
  p=subprocess.run([str(a) for a in args],cwd=ROOT,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=timeout)
 if p.returncode:raise RuntimeError('Execution failed, log: '+str(log))
def measurement(exe,mode,wasm,prepared):
 r=subprocess.run([str(exe),mode,str(wasm),str(prepared)],cwd=ROOT,capture_output=True,text=True,timeout=90)
 if r.returncode:raise RuntimeError(f'{mode} measurement failed: {r.stderr[-1000:]}')
 return json.loads(r.stdout)
def student_t(n):
 try:
  from scipy.stats import t
  return float(t.ppf(.975,n-1))
 except ImportError:return 2.0931  # Conservative at n >= 20.
def ci(rows,field):
 a=[float(r[field]) for r in rows]
 n=len(a);avg=statistics.mean(a)
 half=student_t(n)*statistics.stdev(a)/math.sqrt(n) if n>=2 else math.inf
 relative=(100*half/abs(avg)) if avg else math.inf
 return {'n':n,'mean':avg,'CI95_halfwidth':half,'CI95_relative_halfwidth_pct':relative,
         'precision_2_5pct_accepted':relative<=2.5}
def main():
 for m,path in MODELS.items():
  if not path.is_file():raise RuntimeError(f'Missing validated {m} Wasm binary: {path}')
 adapter=ROOT/'serving/common_ingress/src/wasm_adapter.rs'
 if not adapter.is_file() or 'Engine::default()' not in adapter.read_text() or 'Module::from_file' not in adapter.read_text():
  raise RuntimeError('Current deployed JIT module loading not confirmed; cannot freeze')
 gateway=ROOT/'serving/common_ingress/src/main.rs'
 if not gateway.is_file() or '.max_blocking_threads(1)' not in gateway.read_text():
  raise RuntimeError('Bounded Tokio blocking configuration not confirmed')
 pkg=OUT/'probe';(pkg/'src').mkdir(parents=True)
 (pkg/'Cargo.toml').write_text('[package]\nname="comet_wp2_jit_aot_probe"\nversion="0.1.0"\nedition="2021"\n[dependencies]\nwasmtime="=44.0.0"\nanyhow="1"\nserde_json="1"\n')
 (pkg/'src/main.rs').write_text(PROBE)
 env=os.environ.copy();env['CARGO_TARGET_DIR']=str(ROOT/'serving/common_ingress/target')
 print('BUILD matched Wasmtime 44 JIT/AOT probe',flush=True)
 run(['cargo','build','--release','--offline','--manifest-path',pkg/'Cargo.toml'],OUT/'build.log',env)
 exe=Path(env['CARGO_TARGET_DIR'])/'release/comet_wp2_jit_aot_probe'
 if not exe.is_file():raise RuntimeError('Compiled probe binary missing')
 results={};raw=OUT/'RAW.jsonl'
 for model,wasm in MODELS.items():
  prepared=OUT/f'{model}.cwasm'
  run([exe,'prepare',wasm,prepared],OUT/f'{model}_prepare.log')
  results[model]={'wasm_sha256':sha(wasm),'precompiled_sha256':sha(prepared),'modes':{}}
  for mode in ('jit','aot'):
   rows=[]
   for repeat in range(1,61):
    record=measurement(exe,mode,wasm,prepared)
    record.update({'model':model,'mode':mode,'repetition':repeat})
    rows.append(record)
    with raw.open('a') as f:f.write(json.dumps(record)+'\n')
    if repeat>=20 and ci(rows,'total_pss_mib')['precision_2_5pct_accepted'] and ci(rows,'module_incremental_pss_mib')['precision_2_5pct_accepted']:
     break
   results[model]['modes'][mode]={
    metric:ci(rows,metric) for metric in ('total_pss_mib','module_incremental_pss_mib','two_instance_incremental_pss_mib','module_load_ns')}
   print(f'{model} {mode}: {len(rows)} fresh processes, total PSS {ci(rows,"total_pss_mib")["mean"]:.3f} MiB, CI ±{ci(rows,"total_pss_mib")["CI95_relative_halfwidth_pct"]:.2f}%',flush=True)
 pilot={'experiment':'WP2 §5.1 measured matched-thread Wasmtime JIT versus AOT sensitivity pilot',
  'method':'Fresh processes; engine default; two instances; same models and Wasmtime 44 for JIT and precompiled AOT',
  'precision':{'minimum_repetitions':20,'maximum_repetitions':60,'target_relative_CI95_halfwidth_percent':2.5,
   'criteria':['total_pss_mib','module_incremental_pss_mib']},
  'comparison':results,'deployment_choice':'jit','selected_mode':'jit',
  'deployment_choice_reason':'Freeze currently deployed Engine::default + Module::from_file JIT-loaded Wasmtime configuration; do not select a mode because it favours Wasmtime.',
  'frozen_configuration':{'wasmtime_version':'44.0.0','mode':'jit','ingress_tokio_workers':1,'max_blocking_threads':1,'wasm_inference_workers':1,'one_model_per_host':True},
  'limits':['Fresh-process staged sensitivity: not interchangeable with complete gateway density results',
            'Unmet precision at 60 repetitions is reported as uncertainty, never accepted silently'],
  'raw_evidence':str(raw),'utc':dt.datetime.now(dt.timezone.utc).isoformat()}
 target=OUT/'JIT_AOT_COMPARISON.json';target.write_text(json.dumps(pilot,indent=2)+'\n')
 print('WP2 JIT/AOT measured and deployed configuration documented:',target,flush=True)
 gate=ROOT/'COMET_WP1_WP3_FINAL_RECONCILIATION_FIXED_20261124.py'
 if gate.is_file():
  print('RUNNING consolidated WP1–WP3 gate once',flush=True)
  r=subprocess.run([sys.executable,str(gate)],cwd=ROOT,capture_output=True,text=True)
  (OUT/'gate_output.log').write_text(r.stdout+'\n'+r.stderr)
  print(r.stdout,flush=True)
  if r.returncode:print('GATE WARNING: see',OUT/'gate_output.log',flush=True)
 else:print('GATE MISSING: existing pilot saved; no automatic GO',flush=True)
 print('WP4 not launched by this script; supervisor STOP/GO must be satisfied.',flush=True)
if __name__=='__main__':
 try:main()
 except Exception as e:
  print('SAFE STOP:',e,'\nSaved evidence/logs:',OUT,file=sys.stderr)
  sys.exit(2)
