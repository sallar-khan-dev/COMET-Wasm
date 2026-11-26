#!/usr/bin/env python3
"""COMET supervisor WP4 §7: run existing independently validated RF/SVM scaled
variants through the SAME corrected common gateway and Rust v2 open-loop
loadgen as WP4 light baseline. NO kernel spoofing, NO new workload family,
NO pre-WP1 legacy multitenant runner. Adaptive student-t 95% CI, 20..60.

Run inside tmux on the HPC server. It is safe to rerun: child runner
checkpoints independently by variant, while completed groups are skipped.
This covers WP4 serving performance, NOT heavy-density measurements.
"""
from __future__ import annotations
import ast, datetime as dt, json, os, re, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
BASE=ROOT/'research_enhancement/wp4_compute_crossover'
BASELINE=ROOT/'COMET_WP4_MLP_SVM_RESUME_20261125.py'
TARGET=ROOT/'research_enhancement/reports/wp4_scaled_gateway_adaptive'
TARGET.mkdir(parents=True,exist_ok=True)
VARIANTS=[f'rf_trees_{n}' for n in (100,200,400)]+[f'svm_c_{c}' for c in ('0p03','0p1','0p3')]
RATES=(100,600,2400)
LEVELS=(1,5,10,20,50,100,200)

class Block(RuntimeError):pass

def store(path,object):
 path.parent.mkdir(parents=True,exist_ok=True)
 temp=path.with_suffix(path.suffix+'.partial')
 temp.write_text(json.dumps(object,indent=2,default=str)+'\n')
 temp.replace(path)

def spec(name):
 family='rf' if name.startswith('rf_') else 'svm'
 directory=BASE/'generated'/name
 golden=BASE/'validation'/f'{name}_golden.json'
 wasm=directory/'wasm/target/wasm32-unknown-unknown/release'/f'tenant_{family}_real.wasm'
 docker=directory/'docker'
 image='comet-wp4-'+(name.replace('rf_trees_','rf-') if family=='rf' else name.replace('_','-'))+':latest'
 return {'name':name,'family':family,'directory':directory,'golden':golden,
         'wasm':wasm,'docker':docker,'image':image}

def validate(s):
 name=s['name']; problems=[]
 for key in ('golden','wasm'):
  if not s[key].is_file():problems.append(f'missing {key}: {s[key]}')
 if not (s['docker']/'Dockerfile').is_file():problems.append(f'missing Docker source: {s["docker"]}')
 if s['golden'].is_file():
  try:
   golden=json.loads(s['golden'].read_text())
   if golden.get('model')!=name or len(golden.get('records',[]))!=569:
    problems.append('Independent golden model/record count mismatch')
   if not golden.get('reference_method') or not golden.get('model_sha256'):
    problems.append('Independent golden provenance incomplete')
   for i,row in enumerate(golden.get('records',[])):
    if not isinstance(row.get('features'),list) or len(row['features'])!=30 or type(row.get('prediction')) is not int:
     problems.append(f'Malformed golden record {i}');break
  except (OSError,ValueError,TypeError) as exc:problems.append('Invalid golden JSON: '+str(exc))
 for backend in ('wasmtime','docker'):
  f=BASE/'validation'/f'{name}_{backend}.json'
  try:
   result=json.loads(f.read_text())
   if result.get('status')!='PASS' or result.get('matched')!=569 or result.get('mismatches')!=0:
    problems.append(f'{backend} golden parity not 569/569: {f}')
  except (OSError,ValueError) as exc:problems.append(f'Missing/malformed {backend} parity: {exc}')
 return problems

def render_variant(source,s):
 # Change only the model artifact + reference + Docker source, preserving all
 # serving, thread-affinity, trace, precision and correctness logic intact.
 begin=source.index('MODELS={')
 end=source.index('MIN_REPS,MAX_REPS=',begin)
 model=s['name']
 replacement=(f'MODELS={{\n {model!r}:{{\n'
   f'  "golden":ROOT/{str(s["golden"].relative_to(ROOT))!r},\n'
   f'  "wasm":ROOT/{str(s["wasm"].relative_to(ROOT))!r},\n'
   f'  "docker":ROOT/{str(s["docker"].relative_to(ROOT))!r},\n'
   f'  "image":{s["image"]!r}\n }}\n}}\n')
 source=source[:begin]+replacement+source[end:]
 root_line="ROOT=Path(__file__).resolve().parent"
 assert source.count(root_line)==1, 'Unexpected baseline ROOT definition'
 source=source.replace(root_line,"ROOT=Path('/home/sallar/wasiMultitenant')")
 old="OUTBASE=ROOT/'research_enhancement/reports/wp4_baseline_adaptive'"
 assert source.count(old)==1, 'Unexpected baseline output path; no experiment run'
 source=source.replace(old,f"OUTBASE=ROOT/'research_enhancement/reports/wp4_scaled_gateway_adaptive/{model}'")
 old="if state.get('scope','').startswith('WP4') and state.get('status')!='BASELINE_COMPLETE':existing.append(path)"
 new="if state.get('scope','').startswith('WP4') and state.get('status')!='BASELINE_COMPLETE':existing.append(path)"
 assert source.count(old)==1
 # Baseline runner prints a baseline message; change only labeling.
 source=source.replace('WP4 existing MLP/SVM baseline COMPLETE;',f'WP4 scaled {model} serving COMPLETE;')
 source=source.replace("'scope':'WP4 §7: EXISTING MLP/SVM light baseline; RF baseline retained from WP1'",f"'scope':'WP4 §7: SCALED {model} matched common-gateway serving'")
 source=source.replace("'not_yet_done':['scaled MLP/RF/SVM models','WP4 heavy density remeasurement','compute crossover validation']", "'not_yet_done':['WP4 scaled density remeasurement','WP4 crossover boundary analysis']")
 assert 'MIN_REPS,MAX_REPS=20,60' in source and 'TARGET_PCT=2.5' in source
 assert "GATE=ROOT/'serving/common_ingress/target/release/comet_common_ingress'" in source
 assert "GEN=ROOT/'research_enhancement/v2_loadgen/target/release/comet_v2_loadgen'" in source
 assert "SERVER_CPU,CLIENT_CPU=0,1" in source
 assert "RATE_GRID=(100,600,2400)" in source
 ast.parse(source)
 return source

def previous_complete(name):
 folder=TARGET/name
 for candidate in sorted(folder.glob('*/STATE.json'),reverse=True):
  try:j=json.loads(candidate.read_text())
  except (OSError,ValueError):continue
  if j.get('status')=='BASELINE_COMPLETE' and len(j.get('results',[]))==6:
   return candidate
 return None

def main():
 print('WP4 §7 SCALED RF/SVM - corrected gateway, matched model source, independent golden',flush=True)
 if not BASELINE.is_file():raise Block('Corrected 20..60 WP4 baseline runner missing: '+str(BASELINE))
 source=BASELINE.read_text()
 if 'MIN_REPS,MAX_REPS=20,60' not in source or 'TARGET_PCT=2.5' not in source:
  raise Block('Baseline 20..60 / 95% CI precision methodology changed')
 if "GATE=ROOT/'serving/common_ingress/target/release/comet_common_ingress'" not in source:
  raise Block('Baseline no longer uses WP1 corrected common gateway')
 assert 'for model,cfg in MODELS.items():' in source
 preflight={}
 for name in VARIANTS:
  s=spec(name)
  preflight[name]=validate(s)
  print(f'PREFLIGHT {name}: '+('PASS' if not preflight[name] else 'BLOCKED: '+'; '.join(preflight[name])),flush=True)
 info={'date_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
       'scope':'WP4 §7 scaled RF/SVM: matched Wasmtime and Docker via the corrected common gateway',
       'run_policy':{'confidence':.95,'relative_ci_target_pct':2.5,'min_repetitions':20,'max_repetitions':60,
        'metrics':['P50','P95','P99'],'rates_rps':RATES},
       'variants':VARIANTS,'preflight':preflight,'status':'PREFLIGHT',
       'density_levels_required_later':LEVELS,
       'note':'No unsupported switch to pre-WP1 multitenant_server. MLP scaling to be completed separately if no independent parity validation is present.',
       'completed':[]}
 manifest=TARGET/'MASTER_STATE.json';store(manifest,info)
 if any(preflight.values()):
  raise Block('One or more scaled RF/SVM variants not validated; none started. See '+str(manifest))
 info['status']='RUNNING';store(manifest,info)
 for name in VARIANTS:
  s=spec(name)
  completed=previous_complete(name)
  if completed:
   print(f'SKIP COMPLETED {name}: {completed}',flush=True)
   info['completed'].append({'model':name,'state':str(completed),'reused':True});store(manifest,info)
   continue
  driver=TARGET/f'runner_{name}.py'
  generated=render_variant(source,s)
  if driver.exists():
   if driver.read_text()!=generated:raise Block(f'Existing driver changed, refusing overwrite: {driver}')
  else:driver.write_text(generated)
  print(f'RUN {name}: 2 backends × 3 rates, adaptive 20..60; variants sequential',flush=True)
  runlog=TARGET/f'{name}.master.log'
  # The child emits live progress (unbuffered) and writes its own atomic state.
  with runlog.open('a') as f:
   p=subprocess.Popen([sys.executable,'-u',str(driver)],cwd=ROOT,
     stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
   for line in p.stdout:
    print(line,end='',flush=True)
    f.write(line);f.flush()
   result=p.wait()
  if result:
   info['status']='SAFE_STOP';info['blocker']=f'{name} runner failed exit {result}';store(manifest,info)
   raise Block(info['blocker']+'; preserved '+str(runlog))
  completed=previous_complete(name)
  if not completed:raise Block(f'{name} returned 0 but no complete six-condition state found')
  info['completed'].append({'model':name,'state':str(completed),'reused':False});store(manifest,info)
 info['status']='SCALED_RF_SVM_SERVING_COMPLETE';store(manifest,info)
 print('WP4 SCALED RF/SVM gateway-serving measurements COMPLETE',flush=True)
 print('REPORT:',manifest,flush=True)
 print('WP4 §7 still requires scaled MLP (where practical), crossover interpretation, and seven-level density curves for heavier variants.',flush=True)

if __name__=='__main__':
 try:main()
 except BaseException as e:
  print(f'SAFE STOP ({type(e).__name__}): {e}',file=sys.stderr,flush=True)
  sys.exit(2)
