#!/usr/bin/env python3
"""WP3 §6.1 deterministic native-vs-Wasmtime batched kernel pilot.

Uses repository LR Wasm and its official deterministic trace. This is a WP3
kernel pilot only; it does not implement WP3 startup/admission or close WP2.
"""
import argparse, csv, datetime, hashlib, json, os, pathlib, shutil, subprocess, sys, textwrap
ROOT=pathlib.Path('/home/sallar/wasiMultitenant')
WASM=ROOT/'wasm/tenant_lr_real/target/wasm32-unknown-unknown/release/tenant_lr_real.wasm'
TRACE=ROOT/'research_enhancement/v2_workloads/lr_iris_trace_135_seed42_t3.json'
BASE=ROOT/'research_enhancement/automated_supervisor_workplan/wp3_batched_kernel'
RUST=r'''use anyhow::{anyhow,Result};
use serde::Deserialize;
use std::{fs, hint::black_box, time::Instant};
use wasmtime::{Engine,Module,Store,Instance};
#[derive(Deserialize)] struct Request {features:Vec<f32>,expected_prediction:i32}
#[derive(Deserialize)] struct Trace {requests:Vec<Request>}
fn native(x:&[f32])->i32 {
 let w=[0.5435686295f32,-0.3396157602,1.878629174,2.737636864];
 let mean=[5.835238095f32,3.098095238,3.697142857,1.179047619];
 let scale=[0.8678359459f32,0.4318246894,1.841503379,0.7945882717];
 let mut z=-3.441903479f32;
 for i in 0..4 {z+=w[i]*((x[i]-mean[i])/scale[i]);}
 if 1.0f32/(1.0+(-z).exp())>=0.5 {1} else {0}
}
fn main()->Result<()> {
 let a:Vec<String>=std::env::args().collect();
 if a.len()!=6 {return Err(anyhow!("usage: binary wasm trace batch rounds csv"));}
 let wasm=&a[1];let trace:Trace=serde_json::from_str(&fs::read_to_string(&a[2])?)?;
 let batch:usize=a[3].parse()?;let rounds:usize=a[4].parse()?;
 if trace.requests.is_empty() || batch==0 || rounds==0 {return Err(anyhow!("empty trace or nonpositive batch/rounds"));}
 let engine=Engine::default();let module=Module::from_file(&engine,wasm).map_err(|e|anyhow!("module: {e}"))?;
 let mut store=Store::new(&engine,());let instance=Instance::new(&mut store,&module,&[]).map_err(|e|anyhow!("instance: {e}"))?;
 let memory=instance.get_memory(&mut store,"memory").ok_or_else(||anyhow!("memory export"))?;
 let ptr=instance.get_typed_func::<(),i32>(&mut store,"input_ptr")?.call(&mut store,())?;
 let infer=instance.get_typed_func::<(),i32>(&mut store,"predict")?;
 let mut inputs=Vec::new();
 for item in &trace.requests {
  if item.features.len()!=4 {return Err(anyhow!("unexpected LR features"));}
  let mut b=Vec::new();for x in &item.features {b.extend_from_slice(&x.to_le_bytes());}
  memory.write(&mut store,ptr as usize,&b)?;
  let got=infer.call(&mut store,())?;
  let expected=item.expected_prediction;
  let native_out=native(&item.features);
  if got!=expected || native_out!=expected {return Err(anyhow!("reference mismatch Wasm={got} native={native_out} expected={expected}"));}
  inputs.push(b);
 }
 // Prime both backends; use only confirmed reference-equivalent inputs.
 for i in 0..1000 {let j=i%trace.requests.len();black_box(native(black_box(&trace.requests[j].features)));memory.write(&mut store,ptr as usize,&inputs[j])?;black_box(infer.call(&mut store,())?);}
 let mut writer=csv::Writer::from_path(&a[5])?;
 writer.write_record(["round","backend","sample_count","batch_per_sample","calls","elapsed_ns","ns_per_call","checksum"])?;
 for round in 0..rounds {
  // Alternate order across rounds to reduce systematic drift.
  for mode in if round%2==0 {["native","wasmtime"]} else {["wasmtime","native"]} {
   let mut elapsed:u128=0;let mut checksum:u64=0;
   for (j,item) in trace.requests.iter().enumerate(){
    if mode=="wasmtime" {memory.write(&mut store,ptr as usize,&inputs[j])?;}
    // Batched kernel calls; input representation is prepared before timing.
    let t=Instant::now();
    for _ in 0..batch {
     let p=if mode=="native" {native(black_box(&item.features))}else {infer.call(&mut store,())?};
     checksum=checksum.wrapping_add(black_box(p as u64));
    }
    elapsed+=t.elapsed().as_nanos();
   }
   let calls=batch*trace.requests.len();
   writer.write_record([round.to_string(),mode.to_string(),trace.requests.len().to_string(),batch.to_string(),calls.to_string(),elapsed.to_string(),format!("{:.6}",elapsed as f64/calls as f64),checksum.to_string()])?;
   writer.flush()?;
   println!("ROUND {:02}/{:02} {} calls={} ns/call={:.3} checksum={}",round+1,rounds,mode,calls,elapsed as f64/calls as f64,checksum);
  }
 }
 Ok(())
}
'''
def run(c,**kw):
 p=subprocess.run(c,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,**kw)
 if p.returncode: raise RuntimeError('Command failed: '+str(c)+'\n'+p.stdout[-4000:])
 return p.stdout

def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--batch',type=int,default=500);ap.add_argument('--rounds',type=int,default=20);args=ap.parse_args()
 if args.batch<2 or args.rounds<2:ap.error('batch and rounds must be >=2')
 for p in [WASM,TRACE]:
  if not p.is_file():raise RuntimeError(f'Required repository artifact missing: {p}')
 if not shutil.which('cargo'):raise RuntimeError('cargo unavailable')
 inputs=json.loads(TRACE.read_text())['requests'];assert len(inputs)>0
 cpus=sorted(os.sched_getaffinity(0));cpu=cpus[0]
 timestamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M%S')
 out=BASE/(timestamp+'_'+str(os.getpid()));src=out/'harness';(src/'src').mkdir(parents=True)
 (src/'Cargo.toml').write_text('[package]\nname="comet_wp3_batched_kernel"\nversion="0.1.0"\nedition="2021"\n[dependencies]\nanyhow="1"\nserde={version="1",features=["derive"]}\nserde_json="1"\ncsv="1"\nwasmtime="44"\n')
 (src/'src/main.rs').write_text(RUST)
 manifest={'model':'lr','experiment':'WP3 6.1 batched native vs Wasmtime call','trace':str(TRACE),'wasm':str(WASM),'wasm_sha256':hashlib.sha256(WASM.read_bytes()).hexdigest(),'trace_sha256':hashlib.sha256(TRACE.read_bytes()).hexdigest(),'batch':args.batch,'rounds':args.rounds,'cpu':cpu,'note':'Excludes HTTP, input-copy and admission; Wasm timed portion includes Wasmtime typed-call overhead. Native compiled in harness release mode. Not full WP3 approval.'}
 (out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
 print('WP3 §6.1 BATCHED KERNEL EXPERIMENT | OUTPUT',out,flush=True)
 print('BUILD Rust harness using Wasmtime 44',flush=True)
 with (out/'build.log').open('w') as f:
  p=subprocess.run(['cargo','build','--release','--offline','--manifest-path',str(src/'Cargo.toml')],stdout=f,stderr=subprocess.STDOUT,cwd=ROOT)
 if p.returncode:
  print('Offline build unavailable; retrying online Cargo cache resolution',flush=True)
  with (out/'build.log').open('a') as f:
   p=subprocess.run(['cargo','build','--release','--manifest-path',str(src/'Cargo.toml')],stdout=f,stderr=subprocess.STDOUT,cwd=ROOT)
 if p.returncode:raise RuntimeError(f'Rust harness compilation failed: {out}/build.log')
 binary=src/'target/release/comet_wp3_batched_kernel'
 # Capture test conditions without changing project source or existing results.
 cmd=['taskset','-c',str(cpu),str(binary),str(WASM),str(TRACE),str(args.batch),str(args.rounds),str(out/'samples.csv')]
 with (out/'run.log').open('w') as f:
  p=subprocess.run(cmd,cwd=ROOT,stdout=f,stderr=subprocess.STDOUT)
 if p.returncode:raise RuntimeError(f'WP3 experiment failed: {out}/run.log')
 rows=list(csv.DictReader((out/'samples.csv').open()))
 import statistics
 summary={}
 for b in ['native','wasmtime']:
  a=[float(r['ns_per_call']) for r in rows if r['backend']==b]
  summary[b]={'rounds':len(a),'mean_ns_per_call':statistics.mean(a),'sd_ns_per_call':statistics.stdev(a)}
 summary['kernel_ratio_wasmtime_to_native']=summary['wasmtime']['mean_ns_per_call']/summary['native']['mean_ns_per_call']
 (out/'RESULT.json').write_text(json.dumps(summary,indent=2)+'\n')
 (out/'REPORT.md').write_text('# WP3 §6.1 batched LR kernel pilot\n\n'+f'- Batches: {args.batch} invocations per input; {len(inputs)} deterministic input rows; {args.rounds} repeated rounds per backend.\n- Native mean: {summary["native"]["mean_ns_per_call"]:.3f} ns/call\n- Wasmtime mean: {summary["wasmtime"]["mean_ns_per_call"]:.3f} ns/call\n- Ratio Wasmtime/native: {summary["kernel_ratio_wasmtime_to_native"]:.3f}\n\nThe Wasmtime measured block includes typed-call overhead, not just guest instructions. It excludes input copy, HTTP and admission. This pilot does not certify WP3 or establish cold start/admission parity.\n')
 print((out/'REPORT.md').read_text(),flush=True)
 print('FINAL: WP3 BATCHED LR PILOT COMPLETE; full WP3 acceptance remains pending',flush=True)
 print('RESULTS:',out,flush=True)
if __name__=='__main__':
 try:main()
 except Exception as e:print('BLOCKED:',str(e),file=sys.stderr);sys.exit(1)
