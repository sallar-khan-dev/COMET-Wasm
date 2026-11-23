#!/usr/bin/env python3
"""One supervised sequence: WP1 corrected serving, WP2 attribution evidence,
WP3 matched common-gateway cold timing, existing warm-admission evidence, STOP/GO.
Only supervisor WP1-WP3 tasks, not WP4/5/6. Never invent scientific acceptance.
"""
import argparse, csv, datetime as dt, fcntl, hashlib, json, os, pathlib, shutil, subprocess, sys, time
ROOT=pathlib.Path(__file__).resolve().parent
BASE=ROOT/'research_enhancement/automated_supervisor_workplan'
OUTBASE=ROOT/'research_enhancement/reports/wp1_wp3_corrective_20261123'
AUDIT=BASE/'wp2_seven_model_controlled_audit_20261123/WP2_Controlled_Audit.json'
CSV=BASE/'wp2_seven_model_controlled_audit_20261123/WP2_Seven_Model_98_Conditions.csv'
JP=ROOT/'research_enhancement/reports/wp2_memory_attribution_20261121/RESULT.json'
WP3=BASE/'wp3_cold_http_ready_seven_models_20261123/RESULT.json'
WP1_SCRIPT=ROOT/'COMET_Auto_Workplan_v4.py'
WP3_SCRIPT=ROOT/'COMET_WP3_Symmetric_Cold_20261123.py'
BRANCH='research/wp1-lr-2026-11-08'

def jload(p):
 try:return json.loads(p.read_text())
 except (OSError,ValueError):return None

def dump(p,obj):
 t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(obj,indent=2,default=str)+'\n');t.replace(p)

def run(argv,log,timeout=None):
 print('RUN', ' '.join(str(x) for x in argv), 'LOG',log,flush=True)
 with log.open('a') as out:
  result=subprocess.run([str(x) for x in argv],cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,timeout=timeout)
 print('EXIT',result.returncode,'LOG',log,flush=True)
 return result.returncode

def gitcmd(args,timeout=100):
 env=dict(os.environ,GIT_TERMINAL_PROMPT='0',GCM_INTERACTIVE='never')
 r=subprocess.run(['git',*args],cwd=ROOT,text=True,capture_output=True,env=env,timeout=timeout)
 return r.returncode,(r.stdout+r.stderr).strip()

def stage_commit_push(out,extra):
 record={'branch':BRANCH,'out':str(out),'commit':None,'push':False,'errors':[]}
 if gitcmd(['branch','--show-current'])[1]!=BRANCH:record['errors'].append('Not expected research branch');return record
 code,staged=gitcmd(['diff','--cached','--name-only'])
 if code or staged:record['errors'].append('Preexisting staged changes; Git checkpoint skipped');return record
 files=[ROOT/'COMET_Supervisor_Corrective_One_Run_20261123.py',WP3_SCRIPT]
 files.extend(p for p in out.rglob('*') if p.is_file() and p.suffix in ('.json','.csv','.md','.txt') and p.stat().st_size<=2_000_000)
 # Selected WP1 reports and run summaries: no raw 1GB request traces or generated Rust targets.
 for parent in extra:
  if parent is None or not parent.is_dir():continue
  for p in parent.rglob('*'):
   if not p.is_file() or p.suffix not in ('.json','.csv','.md'):continue
   if p.stat().st_size>2_000_000 or any(t in p.parts for t in ('target','deps','cargo_build','incremental')):continue
   files.append(p)
 files=sorted(set(p.relative_to(ROOT).as_posix() for p in files if p.is_relative_to(ROOT)))
 if not files:record['errors'].append('No files to stage');return record
 for i in range(0,len(files),60):
  c,s=gitcmd(['add','--',*files[i:i+60]])
  if c:record['errors'].append('git add: '+s[-600:]);return record
 c,_=gitcmd(['diff','--cached','--quiet'])
 if c==0:record['status']='NO_NEW_CHANGES';return record
 if c!=1:record['errors'].append('Git index examination failed');return record
 c,s=gitcmd(['commit','-m','checkpoint: supervisor WP1-WP3 corrective evidence and scientific gate'],timeout=120)
 if c:record['errors'].append('git commit: '+s[-1000:]);return record
 record['commit']=gitcmd(['rev-parse','HEAD'])[1]
 c,s=gitcmd(['push','origin',BRANCH],timeout=150);record['push']=c==0;record['push_output']=s[-1000:]
 if c:record['errors'].append('git push: '+s[-800:])
 return record

def preflight():
 missing=[str(p) for p in (AUDIT,CSV,JP,WP3,WP1_SCRIPT,WP3_SCRIPT) if not p.is_file()]
 if missing:return ['Missing '+x for x in missing]
 audit=jload(AUDIT)
 if not isinstance(audit,dict) or audit.get('backend_density_conditions')!=98:return ['WP2 98-cell audit invalid']
 if audit.get('conditions_precision_met')!=98:return ['WP2 precision conditions not fully accepted; review misses']
 if not shutil.which('docker'):return ['Docker CLI missing']
 if not shutil.which('taskset'):return ['taskset missing']
 if len(os.sched_getaffinity(0))<2:return ['WP1 requires separate allocated server/client CPUs']
 if not (ROOT/'serving/common_ingress/src').is_dir():return ['Not COMET repository root']
 for p in (ROOT/'serving/common_ingress/target/release/comet_common_ingress', ROOT/'research_enhancement/v2_loadgen/target/release/comet_v2_loadgen'):
  if not p.is_file():return ['Missing compiled WP1 server/load generator: '+str(p)]
 frozen=jload(BASE/'wp2_lr_controlled_density_20261121/manifest.json') or {}
 wasm=ROOT/'wasm/tenant_lr_real/target/wasm32-unknown-unknown/release/tenant_lr_real.wasm'
 golden=ROOT/'research_enhancement/v2_references/lr_iris_golden_v1.json'
 for p,expected in ((wasm,frozen.get('wasm_sha256')),(golden,frozen.get('golden_sha256'))):
  if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=expected:return ['Frozen WP2 LR artifact changed: '+str(p)]
 image=subprocess.run(['docker','image','inspect','-f','{{.Id}}','comet-wp1cap-lr:latest'],capture_output=True,text=True)
 if image.returncode or image.stdout.strip()!=frozen.get('docker_image_id'):return ['Frozen LR Docker image missing or changed versus WP2']
 docker_info=subprocess.run(['docker','info','--format','{{.ServerVersion}}'],capture_output=True,text=True,timeout=15)
 if docker_info.returncode:return ['Docker daemon unavailable: '+docker_info.stderr.strip()[-200:]]
 try:
  import scipy
 except ImportError:return ['scipy is required to compute 95% Student-t confidence intervals']
 branch=gitcmd(['branch','--show-current'])[1]
 if branch!=BRANCH:return [f'Expected {BRANCH}, actual {branch}']
 return []

def wp1_existing():
 # Only reuse an already completed, methodologically compatible 20-repetition campaign.
 candidates=[]
 for p in BASE.glob('*/state.json'):
  d=jload(p)
  if not isinstance(d,dict):continue
  config=d.get('config',{});wp=d.get('WP1',{})
  if config.get('repetitions')!=20 or config.get('rates')!=[100,300,600,1200,2400]:continue
  if not str(wp.get('status','')).startswith('DATA COLLECTED'):continue
  if not wp.get('runs'):continue
  candidates.append(p)
 return max(candidates,key=lambda p:p.stat().st_mtime) if candidates else None

def summarize_wp1(state):
 if not state:return {'status':'MISSING'}
 d=jload(state) or {};xs=d.get('WP1',{}).get('runs',[]);cfg=d.get('config',{})
 model_set=sorted({(x.get('model'),x.get('backend')) for x in xs})
 return {'status':d.get('WP1',{}).get('status'),'source':str(state.relative_to(ROOT)),
  'run_records':len(xs),'model_backends':model_set,
  'runs_with_correctness':sum(bool(x.get('correctness_pass')) for x in xs),
  'run_failures':sum(not bool(x.get('correctness_pass')) for x in xs),
  'config':cfg,'interpretation':'Serving experiment outcomes must establish measured client/gateway headroom and actual resource parity; data collected is not scientific acceptance.'}

def wp2_analysis(out):
 audit=jload(AUDIT) or {};jit=jload(JP) or {}
 lines=list(csv.DictReader(CSV.open())); grouping={}
 for r in lines:grouping.setdefault((r['model'],r['backend']),{})[int(r['tenants'])]=float(r['mean_pss_mib'])
 result={'scope':'WP2 §5, §5.1: interpret existing seven-density application PSS and JIT/AOT evidence; no new density repetitions','density_conditions':len(lines),'precision_conditions_met':audit.get('conditions_precision_met'),'models':{},'jit_aot_existing':jit,'helper_memory':'NOT ATTRIBUTABLE when Docker shared daemon/helper PSS is unavailable; never assign zero','ownership_warning':'N=1 PSS includes runtime and resident model; (N=200 - N=1)/199 is an OBSERVATIONAL marginal average, not independently measured component ownership'}
 for model in sorted({m for m,_ in grouping}):
  w=grouping.get((model,'wasmtime'),{});d=grouping.get((model,'docker'),{})
  if len(w)!=7 or len(d)!=7:continue
  result['models'][model]={'wasmtime_N1_application_pss_mib':w[1], 'docker_N1_application_pss_mib':d[1], 'wasmtime_N200_application_pss_mib':w[200], 'docker_N200_application_pss_mib':d[200],
  'wasmtime_observed_mean_increment_per_added_tenant_mib':(w[200]-w[1])/199,
  'docker_observed_mean_increment_per_added_tenant_mib':(d[200]-d[1])/199,
  'memory_crossover_interval':next((f'{a}..{b}' for a,b in zip((1,5,10,20,50,100),(5,10,20,50,100,200)) if (w[a]-d[a])*(w[b]-d[b])<=0),None)}
 dump(out/'WP2_COMPONENT_AND_DENSITY_REVIEW.json',result)
 return result

def wp3_existing():
 d=jload(WP3) or {};xs=d.get('results',{});n=0;ok=0
 for model,tens in xs.items():
  for t,bks in tens.items():
   for backend,metrics in bks.items():
    n+=1
    if all(x.get('accepted') for x in metrics.values()):ok+=1
 return {'conditions':n,'precision_accepted':ok,'scope':d.get('scope'),'source':str(WP3.relative_to(ROOT))}

def latest_cold():
 paths=sorted((BASE/'wp3_symmetric_common_gateway_cold_20261123').glob('*/COMPLETE.txt'))
 return paths[-1].parent if paths else None

def latest_warm():
 base=BASE/'wp3_cold_admission';c=[]
 for p in base.glob('*/RESULT.json'):
  d=jload(p)
  if d and all(isinstance(d.get(k),dict) and d[k].get('n',0)>=20 for k in ('wasmtime_deploy','docker_deploy','wasmtime_admit','docker_admit')):c.append(p)
 return max(c,key=lambda p:p.stat().st_mtime) if c else None

def main():
 ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--preflight',action='store_true');ap.add_argument('--resume',action='store_true');a=ap.parse_args()
 problems=preflight()
 if problems:
  for b in problems:print('PREFLIGHT BLOCKED:',b)
  return 2
 if a.preflight:
  print('PREFLIGHT PASS: WP2 frozen evidence, WP3 seven-model diagnostic, existing WP1/WP3 runners and research branch.')
  print('SCOPE NOTE: endpoint architecture has no dynamic tenant-admission API; warm admission is still not common-gateway equivalent.')
  return 0
 OUTBASE.mkdir(parents=True,exist_ok=True)
 lockfile=OUTBASE/'.exclusive.lock'
 with lockfile.open('a+') as lock:
  try:fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError:print('BLOCKED: another corrective runner is active');return 2
  existing_runs=sorted(p for p in OUTBASE.iterdir() if p.is_dir() and (p/'STATE.json').is_file())
  if a.resume and not existing_runs:
   print('SAFE STOP: no prior corrective run to resume');return 2
  out=existing_runs[-1] if a.resume else OUTBASE/dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d_%H%M%S')
  out.mkdir(exist_ok=a.resume)
  state=jload(out/'STATE.json') or {'started_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'stages':{},'status':'RUNNING'}
  dump(out/'STATE.json',state)
  extras=[]
  def stage(name,detail):
   state['stages'][name]=detail;dump(out/'STATE.json',state);print('STAGE',name,str(detail)[:400],flush=True)
  try:
   old=wp1_existing()
   if old:
    stage('WP1_REUSE',{'source':str(old.relative_to(ROOT)),'note':'Reuse 20-repetition campaign, no new serving rerun'})
   else:
    print('WP1: running prior controlled common-gateway capacity methodology with 20 repeats.',flush=True)
    rc=run([sys.executable,WP1_SCRIPT,'--mode','auto','--repetitions','20'],out/'wp1_capacity.log')
    old=wp1_existing()
    stage('WP1_NEW',{'exit':rc,'source':str(old.relative_to(ROOT)) if old else None})
   if old:extras.append(old.parent)
   wp1=summarize_wp1(old);dump(out/'WP1_REVIEW.json',wp1)
   w2=wp2_analysis(out);stage('WP2',{'precision':w2['precision_conditions_met'],'models':len(w2['models'])})
   # Prior 20-rep Wasmtime JIT/AOT and Docker helper trials are preserved and reused.
   print('WP2: using existing measured helper/JIT-AOT evidence; will not invent Docker helper ownership.',flush=True)
   cur=latest_cold()
   if not cur:
    print('WP3: measuring matched client-facing cold readiness at /health and /infer.',flush=True)
    rc=run([sys.executable,WP3_SCRIPT,'--min-reps','20','--max-reps','60'],out/'wp3_common_gateway_cold.log')
    stage('WP3_NEW_COLD',{'exit':rc});cur=latest_cold()
   if cur:extras.append(cur)
   warm=latest_warm()
   oldwp3=wp3_existing()
   review={'seven_model_direct_endpoint':oldwp3,
    'matched_common_gateway_cold':str(cur.relative_to(ROOT)) if cur else None,
    'warm_admission_existing':str(warm.relative_to(ROOT)) if warm else None,
    'warm_limit':'Existing warm Wasmtime uses preloaded Engine/Module in separate harness; Docker uses precreated container start. These are documented timing operations, not a common-gateway live admission API.',
    'kernel_limit':'Re-use batched kernel and existing service-cost evidence; do not call typed no-op a pure host call.'}
   dump(out/'WP3_REVIEW.json',review);stage('WP3',{'direct_precision':oldwp3,'cold_new':bool(cur),'warm_existing':bool(warm)})
   blockers=[]
   if not old or not wp1.get('status','').startswith('DATA COLLECTED'):blockers.append('WP1 full corrected common-gateway experiment incomplete or failed.')
   else:blockers.append('WP1 actual thread equivalence and demonstrated sustained headroom require review of CPU utilization and throughput measurements; script completion alone is insufficient.')
   if not w2.get('jit_aot_existing',{}).get('primary_ready_pss_precision_accepted'):blockers.append('WP2 JIT/AOT controlled memory precision not established.')
   blockers.append('WP2 total application PSS is precise, but independent model/base/tenant PSS ownership not fully isolated; helper overhead attributable only where observable.')
   if not cur:blockers.append('WP3 same-common-gateway cold readiness not completed.')
   if not warm:blockers.append('WP3 warm tenant admission 20-repetition evidence missing.')
   else:blockers.append('WP3 warm Wasmtime and Docker tests use distinct deployment structures; no dynamic common-ingress admission endpoint exists.')
   blockers.append('WP3 comparable full serving-path cost attribution and host-copy/kernel boundaries require scientific review of existing evidence.')
   stop={'decision':'NO_GO_PENDING_SCIENTIFIC_REVIEW' if blockers else 'GO_FOR_WP4','workplan':'COMET-Wasm Supervisor §§4–6, mandatory STOP/GO before §7','wp1':wp1,'wp2_summary':{'cells':w2['density_conditions'],'precision':w2['precision_conditions_met'],'jit_aot_ready_precision':w2.get('jit_aot_existing',{}).get('primary_ready_pss_precision_accepted')},'wp3':review,'blockers':blockers,'not_warranted':'A completed script must not overrule unsatisfied comparability requirements.'}
   dump(out/'STOP_GO.json',stop)
   md=['# Supervisor WP1–WP3 scientific checkpoint','',f"**Decision: {stop['decision']}**",'',f"- WP1 run status: {wp1.get('status')}",f"- WP2 precise application PSS conditions: {w2['precision_conditions_met']}/98",f"- WP3 direct-endpoint diagnostic: {oldwp3['precision_accepted']}/{oldwp3['conditions']}",f"- WP3 new matched cold readiness folder: {review['matched_common_gateway_cold']}",f"- WP3 earlier warm admission folder: {review['warm_admission_existing']}",'','## Outstanding requirements']+[f'- {x}' for x in blockers]+['','**WP4 gate:** Do not redesign scheduler or select heavy models until WP1-WP3 serving costs, memory curves and compute/startup primitives are trustworthy.','']
   (out/'STOP_GO.md').write_text('\n'.join(md));stage('FINAL',stop['decision'])
  except Exception as e:
   stage('FAILURE',{'type':type(e).__name__,'detail':str(e)});state['status']='SAFE_STOP';dump(out/'STATE.json',state)
  else:state['status']='REPORT_WRITTEN';dump(out/'STATE.json',state)
  gitstatus=stage_commit_push(out,extras)
  dump(out/'GIT_STATUS_LOCAL_ONLY.json',gitstatus)
  print('FINAL:',state['status'],'REPORT:',out/'STOP_GO.md' if (out/'STOP_GO.md').is_file() else 'No STOP_GO.md')
  print('GIT:',json.dumps(gitstatus))
  return 3 if state['status']=='REPORT_WRITTEN' else 2
if __name__=='__main__':sys.exit(main())
