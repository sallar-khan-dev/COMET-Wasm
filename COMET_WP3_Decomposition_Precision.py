import ast, csv, hashlib, json, math, os, subprocess, sys
from pathlib import Path
from datetime import datetime, timezone
import numpy as np
from scipy.stats import t

ROOT=Path('/home/sallar/wasiMultitenant')
ORIGINAL=ROOT/'COMET_WP3_Batched_Kernel_Pilot_Ready.py'
WASM=ROOT/'wasm/tenant_lr_real/target/wasm32-unknown-unknown/release/tenant_lr_real.wasm'
TRACE=ROOT/'research_enhancement/v2_workloads/lr_iris_trace_135_seed42_t3.json'
BASE=ROOT/'research_enhancement/automated_supervisor_workplan/wp3_copy_call_decomposition'
CPU=min(os.sched_getaffinity(0))
BATCH=500
MIN_RUNS=20
MAX_RUNS=60
METRICS={'native','wasmtime','host_copy','copy_plus_wasm','noop_typed_call'}

for p in (ORIGINAL,WASM,TRACE):
    if not p.is_file():
        sys.exit(f'BLOCKED: missing {p}')

source=ast.parse(ORIGINAL.read_text())
rust=next((
    ast.literal_eval(n.value)
    for n in source.body
    if isinstance(n,ast.Assign)
    and any(isinstance(x,ast.Name) and x.id=='RUST' for x in n.targets)
),None)

if not isinstance(rust,str):
    sys.exit('BLOCKED: original Rust harness not found')

anchor=' let mut inputs=Vec::new();'
if rust.count(anchor)!=1:
    sys.exit('BLOCKED: harness structure changed')

rust=rust.replace(anchor,r''' let noop_module=Module::new(&engine, "(module (func (export \"noop\") (result i32) i32.const 0))")?;
 let mut noop_store=Store::new(&engine,());
 let noop_instance=Instance::new(&mut noop_store,&noop_module,&[])?;
 let noop=noop_instance.get_typed_func::<(),i32>(&mut noop_store,"noop")?;
'''+anchor,1)

start=rust.find(' let mut writer=csv::Writer::from_path(&a[5])?;')
end=rust.find('\n Ok(())\n}',start)

if start<0 or end<0:
    sys.exit('BLOCKED: original measurement structure changed')

rust=rust[:start]+r''' let mut writer=csv::Writer::from_path(&a[5])?;
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
 writer.flush()?;'''+rust[end:]

out=BASE/(datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')+'_'+str(os.getpid()))
project=out/'harness'
(project/'src').mkdir(parents=True)

(project/'Cargo.toml').write_text(
    '[package]\nname="comet_wp3_cost_decomp"\n'
    'version="0.1.0"\nedition="2021"\n'
    '[dependencies]\nanyhow="1"\n'
    'serde={version="1",features=["derive"]}\n'
    'serde_json="1"\ncsv="1"\nwasmtime="44"\n'
)
(project/'src/main.rs').write_text(rust)

manifest={
    'work_package':'WP3 Section 6.1',
    'model':'LR',
    'cpu':CPU,
    'batch_per_input':BATCH,
    'minimum_processes':MIN_RUNS,
    'maximum_processes':MAX_RUNS,
    'confidence':0.95,
    'target_relative_halfwidth_pct':2.5,
    'bootstrap_resamples':5000,
    'original_rust_sha256':hashlib.sha256(ORIGINAL.read_bytes()).hexdigest(),
    'trace_sha256':hashlib.sha256(TRACE.read_bytes()).hexdigest(),
    'wasm_sha256':hashlib.sha256(WASM.read_bytes()).hexdigest(),
    'scope':'Kernel, copy, typed-call and copy-plus-call; excludes HTTP service',
    'noop_note':'Minimal guest typed-call reference; not a pure host-call measurement'
}
(out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')

print('WP3 COPY/CALL DECOMPOSITION STARTED',flush=True)
print('OUTPUT:',out,flush=True)

env=dict(os.environ,CARGO_TARGET_DIR=str(ROOT/'serving/common_ingress/target'))
with (out/'build.log').open('w') as log:
    build=subprocess.run(
        ['cargo','build','--release','--offline',
         '--manifest-path',str(project/'Cargo.toml')],
        cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT
    )
if build.returncode:
    sys.exit(f'BLOCKED: build failed, see {out}/build.log')

exe=ROOT/'serving/common_ingress/target/release/comet_wp3_cost_decomp'
if not exe.is_file():
    sys.exit('BLOCKED: executable missing')

manifest['executable_sha256']=hashlib.sha256(exe.read_bytes()).hexdigest()
(out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')

trials=[]
metrics=sorted(METRICS)

for rep in range(1,MAX_RUNS+1):
    runfile=out/f'process_{rep:02d}.csv'
    p=subprocess.run(
        ['taskset','-c',str(CPU),str(exe),str(WASM),
         str(TRACE),str(BATCH),str(rep),str(runfile)],
        cwd=ROOT,capture_output=True,text=True,timeout=90
    )
    if p.returncode:
        sys.exit(f'BLOCKED process {rep}: {(p.stderr or p.stdout)[-600:]}')

    with runfile.open() as f:
        rows=list(csv.DictReader(f))

    if len(rows)!=5 or {r['metric'] for r in rows}!=METRICS:
        sys.exit(f'BLOCKED: incomplete process {rep}')

    checks={r['metric']:r['checksum'] for r in rows}
    if len({checks[m] for m in ('native','wasmtime','copy_plus_wasm')})!=1:
        sys.exit(f'BLOCKED: prediction mismatch, process {rep}')

    for r in rows:
        trials.append({
            'process':rep,
            'metric':r['metric'],
            'calls':int(r['calls']),
            'ns_per_call':float(r['ns_per_call']),
            'checksum':r['checksum']
        })

    with (out/'trials.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(trials[0]))
        w.writeheader()
        w.writerows(trials)

    if rep>=MIN_RUNS and (rep==MIN_RUNS or rep%5==0):
        statuses=[]
        for metric in metrics:
            x=np.array([r['ns_per_call'] for r in trials if r['metric']==metric])
            n=len(x)
            avg=float(x.mean())
            if not np.isfinite(x).all() or avg<=0:
                sys.exit(f'BLOCKED: invalid metric {metric}')

            th=float(t.ppf(.975,n-1)*x.std(ddof=1)/math.sqrt(n))
            rng=np.random.default_rng(20261121+metrics.index(metric)*1000+n)
            boot=x[rng.integers(0,n,size=(5000,n))].mean(axis=1)
            bh=float(np.diff(np.quantile(boot,[.025,.975]))[0]/2)

            statuses.append({
                'metric':metric,
                'independent_processes':n,
                'calls_per_process':BATCH*len(json.loads(TRACE.read_text())['requests']),
                'mean_ns_per_call':avg,
                'student_t_relative_halfwidth_pct':100*th/avg,
                'bootstrap_relative_halfwidth_pct':100*bh/avg,
                'accepted':max(th,bh)/avg<=.025
            })

        accepted=sum(s['accepted'] for s in statuses)
        (out/'RESULT.json').write_text(json.dumps({
            'precision':statuses,
            'accepted_metrics':accepted,
            'total_metrics':5,
            'all_accepted':accepted==5,
            'status':'PRECISION_ACCEPTED' if accepted==5 else 'PRECISION_NOT_YET_MET'
        },indent=2)+'\n')

        print(f'PROCESSES={rep} PRECISION={accepted}/5',flush=True)
        for s in statuses:
            print(
                f"{s['metric']}: "
                f"Student-t={s['student_t_relative_halfwidth_pct']:.3f}% "
                f"Bootstrap={s['bootstrap_relative_halfwidth_pct']:.3f}% "
                f"Accepted={s['accepted']}",
                flush=True
            )
        if accepted==5:
            break

print('FINAL REPORT:',out/'RESULT.json',flush=True)
