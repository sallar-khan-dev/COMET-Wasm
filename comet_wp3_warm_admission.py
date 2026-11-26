#!/usr/bin/env python3
"""Supervisor WP3 §6.2: warm tenant admission, not whole-deployment cold start.

Wasm: engine+module loaded before timed Store+Instance creation.
Docker: image pre-created as stopped container before timed docker start.
No source edits. No WP1/WP2/WP4 work. Existing results are never overwritten.
"""
import argparse, datetime, json, os, pathlib, shutil, subprocess, sys, tempfile, time

ROOT = pathlib.Path(__file__).resolve().parent
DEFAULT_WASM = ROOT/'wasm/tenant_lr_real/target/wasm32-unknown-unknown/release/tenant_lr_real.wasm'
RUST = r'''use std::{env,time::Instant};
use wasmtime::{Engine,Module,Store,Instance};
fn main()->anyhow::Result<()> {
 let args:Vec<String>=env::args().collect();
 let wasm=&args[1]; let repetitions:usize=args[2].parse()?;
 let engine=Engine::default(); let module=Module::from_file(&engine,wasm)?;
 // Control: engine and module deliberately created before the timed admission loop.
 let mut values=Vec::with_capacity(repetitions);
 for _ in 0..repetitions {
  let t=Instant::now();
  let mut store=Store::new(&engine,());
  let instance=Instance::new(&mut store,&module,&[])?;
  std::hint::black_box(instance);
  values.push(t.elapsed().as_nanos());
 }
 println!("{}",serde_json::to_string(&values)?);
 Ok(())
}'''
CARGO = '''[package]\nname="comet_wp3_warm_admission"\nversion="0.1.0"\nedition="2021"\n[dependencies]\nwasmtime="=44.0.0"\nanyhow="1"\nserde_json="1"\n'''

def call(args, **kw):
    return subprocess.run(list(map(str,args)), check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kw)

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--wasm',type=pathlib.Path,default=DEFAULT_WASM)
    ap.add_argument('--docker-image',required=True,help='Existing validated LR Docker image tag or immutable ID')
    ap.add_argument('--repetitions',type=int,default=60)
    ap.add_argument('--cpu',type=int,default=0)
    ap.add_argument('--output-root',type=pathlib.Path,default=ROOT/'research_enhancement/reports/wp3_warm_admission')
    args=ap.parse_args()
    if not (20 <= args.repetitions <= 60): ap.error('Supervisor campaign repetitions must be 20–60')
    if not args.wasm.is_file(): ap.error('Missing Wasmtime module: '+str(args.wasm))
    for executable in ('docker','cargo','taskset'):
        if not shutil.which(executable): ap.error('Missing '+executable)
    allowed=os.sched_getaffinity(0)
    if args.cpu not in allowed: ap.error('CPU not allocated to this process: '+str(args.cpu))
    image_id=call(['docker','image','inspect','--format','{{.Id}}',args.docker_image]).stdout.strip()
    if not image_id.startswith('sha256:'): ap.error('Docker image could not be frozen')
    run_dir=args.output_root/(datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M%S')+'_'+str(os.getpid()))
    run_dir.mkdir(parents=True,exist_ok=False)
    metadata={'scope':'Supervisor §6.2 warm tenant admission; not deployment cold start',
              'wasm_path':str(args.wasm.resolve()),'docker_image':args.docker_image,'docker_image_id':image_id,
              'repetitions':args.repetitions,'cpu':args.cpu,
              'generated_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
    (run_dir/'metadata.json').write_text(json.dumps(metadata,indent=2)+'\n')
    # Compile outside the existing repository without changing production code.
    # Uses normal Cargo cache; user may set CARGO_TARGET_DIR for a suitable volume.
    with tempfile.TemporaryDirectory(prefix='comet-wp3-warm-') as tmp:
        src=pathlib.Path(tmp); (src/'src').mkdir();(src/'Cargo.toml').write_text(CARGO);(src/'src/main.rs').write_text(RUST)
        build=subprocess.run(['cargo','build','--release','--manifest-path',str(src/'Cargo.toml')],text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        (run_dir/'rust_build.log').write_text(build.stdout)
        if build.returncode: raise RuntimeError('Rust measurement build failed; see '+str(run_dir/'rust_build.log'))
        binary=pathlib.Path(os.environ.get('CARGO_TARGET_DIR',str(src/'target')))/'release/comet_wp3_warm_admission'
        values=json.loads(call(['taskset','-c',args.cpu,binary,args.wasm,args.repetitions]).stdout)
        (run_dir/'wasmtime_store_instance_ns.json').write_text(json.dumps(values,indent=2)+'\n')
    # Container is always pre-created outside the timed interval. `docker start` only is timed.
    docker_values=[]
    for i in range(args.repetitions):
        cname=f'comet_wp3_warm_{os.getpid()}_{i}'
        call(['docker','create','--name',cname,'--network','bridge','--cpuset-cpus',args.cpu,image_id])
        try:
            started=time.perf_counter_ns()
            call(['docker','start',cname])
            docker_values.append(time.perf_counter_ns()-started)
        finally:
            subprocess.run(['docker','rm','-f',cname],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    (run_dir/'docker_precreated_start_ns.json').write_text(json.dumps(docker_values,indent=2)+'\n')
    try:
        import numpy as np
        from scipy.stats import t
        def ci(vals):
            a=np.asarray(vals,dtype=float); mean=float(a.mean())
            half=float(t.ppf(.975,len(a)-1)*a.std(ddof=1)/(len(a)**.5))
            return {'n':len(a),'mean_ms':mean/1e6,'student_t_95_relative_half_width_pct':half/mean*100,'precision_2_5_pct_accepted':half/mean*100<=2.5}
        summary={'wasmtime_warm_admission':ci(values),'docker_warm_start':ci(docker_values)}
    except ImportError:
        import statistics
        summary={'wasmtime_mean_ms':statistics.mean(values)/1e6,'docker_mean_ms':statistics.mean(docker_values)/1e6,'precision':'NOT_EVALUATED: scipy/numpy missing'}
    (run_dir/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print('WP3 WARM ADMISSION MEASURED:',run_dir)
    print(json.dumps(summary,indent=2))
    print('WP1–WP3 STOP/GO unchanged; still requires WP1/WP2 and other WP3 evidence.')
if __name__=='__main__':
    try:main()
    except (subprocess.CalledProcessError,RuntimeError) as e:
        print('BLOCKED:',e,file=sys.stderr)
        sys.exit(2)
