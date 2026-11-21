use anyhow::{anyhow,Result};
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
 let noop_module=Module::new(&engine, "(module (func (export \"noop\") (result i32) i32.const 0))")?;
 let mut noop_store=Store::new(&engine,());
 let noop_instance=Instance::new(&mut noop_store,&noop_module,&[])?;
 let noop=noop_instance.get_typed_func::<(),i32>(&mut noop_store,"noop")?;
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
 writer.write_record(["metric","calls","elapsed_ns","ns_per_call","checksum"])?;
 for _ in 0..1000 {black_box(noop.call(&mut noop_store,())?);}
 let order=["native","wasmtime","host_copy","copy_plus_wasm","noop_typed_call"];
 for step in 0..order.len() {
  let mode=order[(step+rounds)%order.len()];
  let mut elapsed:u128=0;
  let mut checksum:i64=0;
  for (j,item) in trace.requests.iter().enumerate() {
   if mode=="wasmtime" {
    memory.write(&mut store,ptr as usize,&inputs[j])?;
   }
   let start=Instant::now();
   for _ in 0..batch {
    let prediction=match mode {
     "native"=>native(black_box(&item.features)),
     "wasmtime"=>infer.call(&mut store,())?,
     "host_copy"=>{
      memory.write(&mut store,ptr as usize,black_box(&inputs[j]))?;
      0
     },
     "copy_plus_wasm"=>{
      memory.write(&mut store,ptr as usize,black_box(&inputs[j]))?;
      infer.call(&mut store,())?
     },
     "noop_typed_call"=>noop.call(&mut noop_store,())?,
     _=>unreachable!()
    };
    checksum=checksum.wrapping_add(black_box(prediction) as i64);
   }
   elapsed+=start.elapsed().as_nanos();
  }
  let calls=batch*trace.requests.len();
  writer.write_record([
   mode.to_string(),calls.to_string(),elapsed.to_string(),
   format!("{:.9}",elapsed as f64/calls as f64),
   checksum.to_string()
  ])?;
 }
 writer.flush()?;
 Ok(())
}
