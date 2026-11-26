#!/usr/bin/env python3
"""WP3 §6.2 warm Wasmtime admission precision: existing Engine/Module -> Store/Instance.
Batched timing is used to make small admission times measurable (WP3 §6.1 method).
Does not redo Docker, overwrite prior results, or mark overall STOP/GO as passed.
"""
import argparse
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent
WASM = ROOT / 'wasm/tenant_lr_real/target/wasm32-unknown-unknown/release/tenant_lr_real.wasm'
OUT = ROOT / 'research_enhancement/reports/wp3_warm_admission'
RUST = r'''use std::{env, time::Instant, hint::black_box};
use wasmtime::{Engine,Module,Store,Instance};
fn main()->anyhow::Result<()> {
 let a:Vec<String>=env::args().collect();
 let reps:usize=a[2].parse()?; let batch:usize=a[3].parse()?;
 let engine=Engine::default(); let module=Module::from_file(&engine,&a[1])?;
 // Engine/Module are preloaded: timed code is strictly Store+Instance admission.
 let mut per_batch=Vec::with_capacity(reps);
 for _ in 0..reps {
   let start=Instant::now();
   for _ in 0..batch {
     let mut store=Store::new(&engine,());
     let instance=Instance::new(&mut store,&module,&[])?;
     black_box((&store,&instance));
   }
   per_batch.push(start.elapsed().as_nanos() as f64 / batch as f64);
 }
 println!("{}",serde_json::to_string(&per_batch)?);
 Ok(())
}'''
CARGO = '''[package]\nname="comet_wp3_wasm_warm_precision"\nversion="0.1.0"\nedition="2021"\n[dependencies]\nwasmtime="=44.0.0"\nanyhow="1"\nserde_json="1"\n'''

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--wasm',type=Path,default=WASM)
    p.add_argument('--repetitions',type=int,default=60)
    p.add_argument('--batch-size',type=int,default=1000)
    p.add_argument('--cpu',type=int,default=0)
    p.add_argument('--output-root',type=Path,default=OUT)
    a=p.parse_args()
    if not 20<=a.repetitions<=60: p.error('Repetitions must be 20..60')
    if not 10<=a.batch_size<=10000: p.error('Batch size must be 10..10000')
    if a.cpu not in os.sched_getaffinity(0): p.error('CPU not available in process affinity')
    if not a.wasm.is_file(): p.error(f'Wasm artifact missing: {a.wasm}')
    for exe in ('cargo','taskset'):
        if not shutil.which(exe): p.error(f'{exe} missing')
    a.output_root.mkdir(parents=True,exist_ok=True)
    folder=a.output_root/(dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d_%H%M%S')+'_'+str(os.getpid())+'_batched_wasm')
    folder.mkdir(exist_ok=False)
    metadata={'scope':'WP3 §6.2 warm Wasmtime Store+Instance admission (preloaded Engine+Module)',
              'method':'WP3 §6.1 batch timing per independent outer repetition',
              'repetitions':a.repetitions,'batch_size':a.batch_size,'cpu':a.cpu,
              'wasm_sha256':hashlib.sha256(a.wasm.read_bytes()).hexdigest(),
              'prior_docker_warm_start':'PRESERVED_NOT_RERUN',
              'generated_utc':dt.datetime.now(dt.timezone.utc).isoformat()}
    (folder/'metadata.json').write_text(json.dumps(metadata,indent=2)+'\n')
    with tempfile.TemporaryDirectory(prefix='comet-wp3-warm-batch-') as td:
        src=Path(td);(src/'src').mkdir()
        (src/'Cargo.toml').write_text(CARGO)
        (src/'src/main.rs').write_text(RUST)
        cmd=['cargo','build','--release','--manifest-path',str(src/'Cargo.toml')]
        r=subprocess.run(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
        (folder/'rust_build.log').write_text(r.stdout)
        if r.returncode: raise RuntimeError(f'Build failed: {folder}/rust_build.log')
        binary=Path(os.environ.get('CARGO_TARGET_DIR',str(src/'target')))/'release/comet_wp3_wasm_warm_precision'
        r=subprocess.run(['taskset','-c',str(a.cpu),str(binary),str(a.wasm.resolve()),str(a.repetitions),str(a.batch_size)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        if r.returncode: raise RuntimeError(f'Measurement failed: {r.stderr[-1500:]}')
        vals=json.loads(r.stdout)
    if len(vals)!=a.repetitions or any((not math.isfinite(v) or v<=0) for v in vals):
        raise RuntimeError('Invalid per-batch values; no acceptance decision')
    try:
        from scipy.stats import t
    except ImportError:
        raise RuntimeError('SciPy needed for 95% Student-t CI; raw data preserved')
    mean=statistics.mean(vals)
    half=float(t.ppf(.975,len(vals)-1))*statistics.stdev(vals)/math.sqrt(len(vals))
    pct=100*half/mean
    result={'wasmtime_warm_admission_batched':{'n':len(vals),'batch_size':a.batch_size,
       'mean_ms':mean/1e6,'student_t_95_relative_half_width_pct':pct,
       'precision_2_5_pct_accepted':pct<=2.5},
       'docker_warm_start':'Existing accepted result retained; not rerun',
       'wp1_wp3_stop_go':'NO_GO until all supervisor-required evidence is trustworthy'}
    (folder/'wasmtime_per_batch_mean_ns.json').write_text(json.dumps(vals,indent=2)+'\n')
    (folder/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print('WP3 WASMTIME WARM ADMISSION BATCHEd:',folder)
    print(json.dumps(result,indent=2))

if __name__=='__main__':
    try: main()
    except (RuntimeError,subprocess.SubprocessError, OSError, ValueError) as e:
        print('BLOCKED:',str(e),file=sys.stderr)
        sys.exit(2)
