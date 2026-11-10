use anyhow::{Context,Result};
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
 let module=if mode=="jit" {Module::from_file(&engine,wasm).context("jit module load")?}
 else {unsafe{Module::deserialize_file(&engine,&a[3]).context("aot module deserialize")?}};
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
