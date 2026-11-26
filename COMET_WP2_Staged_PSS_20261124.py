#!/usr/bin/env python3
"""Supervisor WP2 §5: measured staged Wasmtime base/module/tenant PSS across seven existing models.

Writes new evidence only; never edits existing density samples. Not a full WP1–3 gate.
"""
import csv, datetime as dt, json, os, pathlib, statistics, subprocess, sys
ROOT=pathlib.Path(__file__).resolve().parent
OUTBASE=ROOT/'research_enhancement/reports/wp2_staged_pss'
MODELS={'lr':'logistic_regression','nb':'naive_bayes','dt':'decision_tree',
        'kmeans':'kmeans','rf':'random_forest','svm':'svm','mlp':'mlp'}
RUST=r'''use anyhow::{Context,Result};
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
}'''
def go():
    assert (ROOT/'serving/common_ingress/src/wasm_adapter.rs').is_file(), 'Run from COMET repository root'
    stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d_%H%M%S')+'_'+str(os.getpid())
    out=OUTBASE/stamp;out.mkdir(parents=True,exist_ok=False)
    pkg=out/'pss_probe';(pkg/'src').mkdir(parents=True)
    (pkg/'Cargo.toml').write_text('[package]\nname="comet_wp2_stage_pss"\nversion="0.1.0"\nedition="2021"\n[dependencies]\nwasmtime="=44.0.0"\nanyhow="1"\nserde_json="1"\n')
    (pkg/'src/main.rs').write_text(RUST)
    env=os.environ.copy();env['CARGO_TARGET_DIR']=str(ROOT/'serving/common_ingress/target')
    build=subprocess.run(['cargo','build','--offline','--release','--manifest-path',str(pkg/'Cargo.toml')],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    (out/'build.log').write_text(build.stdout)
    if build.returncode:raise RuntimeError('Rust build failed: '+str(out/'build.log'))
    bin=pathlib.Path(env['CARGO_TARGET_DIR'])/'release/comet_wp2_stage_pss'
    rows=[]
    for tag,name in MODELS.items():
        wasm=ROOT/f'wasm/tenant_{tag}_real/target/wasm32-unknown-unknown/release/tenant_{tag}_real.wasm'
        if not wasm.is_file():
            # Some validated models use slightly different target naming. Never substitute a model without verification.
            print('MISSING MODEL ARTIFACT',name,wasm,flush=True);continue
        for rep in range(1,21):
            proc=subprocess.run([str(bin),str(wasm)],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,timeout=90)
            if proc.returncode:raise RuntimeError(f'{name} rep {rep}: {proc.stderr[-1000:]}')
            row={'model':name,'wasm_artifact':str(wasm),'repetition':rep,**json.loads(proc.stdout)}
            rows.append(row)
            with (out/'raw.jsonl').open('a') as f:f.write(json.dumps(row)+'\n')
        print('STAGED PSS',name,'20 independent fresh-process repetitions',flush=True)
    if rows:
        with (out/'stages.csv').open('w',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    summary={'scope':'WP2 §5 staged Wasmtime PSS only; non-interchangeable with high-density measurements',
             'measured_models':sorted(set(r['model'] for r in rows)),
             'missing_models':[v for v in MODELS.values() if v not in {r['model'] for r in rows}],
             'repetitions_per_measured_model':20,
             'mean_by_model':{m:{k:statistics.mean(float(r[k]) for r in rows if r['model']==m)
               for k in ('process_baseline_pss_mib','engine_delta_mib','module_delta_mib','two_instances_delta_mib','total_two_instance_pss_mib')}
               for m in sorted(set(r['model'] for r in rows))},
             'unresolved':'Docker application/helper PSS remains unmeasured here; this is not STOP/GO approval'}
    (out/'RESULT.json').write_text(json.dumps(summary,indent=2)+'\n')
    print('RESULT',out,'\n',json.dumps(summary,indent=2))
if __name__=='__main__':
    try:go()
    except Exception as e:print('SAFE STOP:',e,file=sys.stderr);sys.exit(2)
