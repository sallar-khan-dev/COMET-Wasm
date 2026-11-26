use anyhow::{Context,Result};
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
}