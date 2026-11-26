use anyhow::{Context,Result};
use std::{env,fs,thread,time::Duration};
use wasmtime::{Engine,Module,Instance,Store};
fn pss()->Result<f64>{
 let s=fs::read_to_string("/proc/self/smaps_rollup")?;
 let l=s.lines().find(|l|l.starts_with("Pss:")).context("No /proc Pss")?;
 Ok(l.split_whitespace().nth(1).context("No Pss value")?.parse::<f64>()?/1024.)
}
fn settled()->Result<f64>{thread::sleep(Duration::from_millis(50));pss()}
fn main()->Result<()> {
 let a:Vec<String>=env::args().collect();anyhow::ensure!(a.len()==2,"usage: wp2_pss file.wasm");
 let start=settled()?;
 let engine=Engine::default();let after_engine=settled()?;
 let module=Module::from_file(&engine,&a[1])?;let after_module=settled()?;
 let mut held=Vec::new();
 for _ in 0..2 {let mut store=Store::new(&engine,());let instance=Instance::new(&mut store,&module,&[])?;
 held.push((store,instance));}
 let after_two=settled()?;
 println!("{}",serde_json::json!({"process_baseline_pss_mib":start,
 "engine_delta_mib":after_engine-start,"module_delta_mib":after_module-after_engine,
 "two_instances_delta_mib":after_two-after_module,"total_two_instance_pss_mib":after_two}));
 Ok(())
}