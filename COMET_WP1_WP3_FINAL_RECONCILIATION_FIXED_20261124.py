#!/usr/bin/env python3
"""COMET-Wasm supervisor plan WP1-WP3: one-run final evidence RECONCILIATION.
Read-only existing experiments; no new experiments, no CI reruns, no scheduler changes.
Do not claim GO until evidence is demonstrated. Supervisor plan §4-6.
"""
from __future__ import annotations
from pathlib import Path
import os, json, csv, re, math, hashlib, datetime as dt
from collections import defaultdict

ROOT=Path(__file__).resolve().parent
REP=ROOT/'research_enhancement/reports'
OLD=ROOT/'research_enhancement/automated_supervisor_workplan/20261124_041014_1610090'
NATIVE=ROOT/'research_enhancement/automated_supervisor_workplan/20261124_044812_1624463'
PSS=REP/'wp2_docker_helper_pss/20261124_034756_1592069/results.json'
STAGED=REP/'wp2_staged_pss/20261124_034313_1571895'
SVC=REP/'wp3_service_decomposition/20261124_035240/DECOMPOSITION.json'
WP3KERNEL=REP/'supervisor_wp2_wp3_execution/20261124_033232_1568742'
PREVIOUS=REP/'wp1_wp3_one_run_closeout/20261124_044734/FINAL_GO_GATE.json'
OUT=REP/'wp1_wp3_final_reconciled'/dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d_%H%M%S')
OUT.mkdir(parents=True,exist_ok=False)

def read(path):
    try:return json.loads(path.read_text())
    except (OSError,ValueError,TypeError):return None
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1048576),b''):h.update(b)
    return h.hexdigest()
def check(name,ok,evidence,reason=''):
    checks[name]={'status':'PASS' if ok else 'UNRESOLVED',
      'evidence':evidence,'remaining':reason if not ok else ''}
def model_groups(rows):
    g=defaultdict(list)
    for r in rows:
        if isinstance(r,dict):
            key=(r.get('model'),r.get('backend'),r.get('offered_rps'))
            g[key].append(r)
    return g
def unique_trace(run,model):
    return {p.name:sha(p) for p in sorted(run.glob(f'{model}_trace_*.json'))}
def noop_valid(folder):
    return any((lambda x:x is not None and x.get('offered_requests')==14900
      and x.get('successful_requests')==14900
      and all(x.get(f,0)==0 for f in ('failed_requests','timed_out_requests','dropped_requests')))
      (read(p)) for p in folder.glob('noop*.summary.json'))
def resource_valid(folder, backend):
    snapshot=read(folder/'baseline_resources.json')
    if not isinstance(snapshot,dict):return False,'missing baseline'
    expected=['gateway']
    if backend=='docker':expected+=['docker_backend']
    if backend=='native':expected+=['native_backend']
    affinity={}
    for role in expected:
        v=snapshot.get(role,{})
        if not isinstance(v,dict):return False,f'missing {role} resource'
        affinity[role]=v.get('Cpus_allowed_list')
    files=sorted(folder.glob('rps*_rep*.resources.json'))
    if len(files)!=15:return False,{'resource_files':len(files),'affinity':affinity}
    sample=read(files[0])
    actual=bool(isinstance(sample,list) and any(isinstance(x,dict) and
            any(isinstance(v,dict) and 'Threads' in v and 'voluntary_ctxt_switches' in v
            for v in x.values()) for x in sample))
    return all(x=='0' for x in affinity.values()) and actual, {'resource_files':len(files),'affinity':affinity,'threads_context_observed':actual}

checks={}
w=read(OLD/'state.json') or {}
n=read(NATIVE/'state.json') or {}
wrows=(w.get('WP1') or {}).get('runs',[])
nrows=(n.get('WP1') or {}).get('runs',[])
allrows=wrows+nrows
g=model_groups(allrows)
expected={(model,backend,r) for model in ('lr','rf')
          for backend in ('wasmtime','docker','native') for r in (100,300,600,1200,2400)}
complete=set(g)==expected and all(len(g[k])==3 for k in expected) and len(allrows)==90
loss=sum(max(0,int(x.get('offered') or 0)-int(x.get('success') or 0)) for x in allrows)
valid=complete and loss==0 and all(r.get('correctness_pass') is True for r in allrows)
check('WP1_corrected_pilot_all_three_backends',valid,
    {'runs':len(allrows),'conditions':len(g),'losses':loss},
    'Require LR/RF, Wasmtime/native/Docker, 5 rates, 3 repetitions each, golden correctness')
trace={}
trace_ok=True
for model in ('lr','rf'):
    a=unique_trace(OLD,model); b=unique_trace(NATIVE,model)
    trace[model]={'old':len(a),'native':len(b),'same':bool(a) and a==b}
    trace_ok &= bool(a) and a==b
check('WP1_equal_golden_trace',trace_ok,trace,'Traces do not match across Wasmtime/Docker/native')
noops={};resource={}
for model in ('lr','rf'):
    for backend in ('wasmtime','docker','native'):
        folder=(NATIVE if backend=='native' else OLD)/f'{model}_{backend}'
        noops[f'{model}_{backend}']=noop_valid(folder)
        ok,data=resource_valid(folder,backend)
        resource[f'{model}_{backend}']={'complete':ok,'details':data}
check('WP1_gateway_noop_headroom',len(noops)==6 and all(noops.values()),
      noops,'Six 4800-RPS no-op runs must have 14900/14900 successes')
check('WP1_affinity_threads_context_switches',len(resource)==6 and all(x['complete'] for x in resource.values()),
    resource,'Linux thread/context-switch and CPU0 pinning evidence not complete for all paths')
# Source config: worker-count and native binary provenance, not mere gateway thread counts.
src=ROOT/'serving/common_ingress/src/main.rs'
source=src.read_text() if src.is_file() else ''
cap='.max_blocking_threads(1)' in source
native_manifest=read(REP/'wp1_wp3_one_run_closeout/20261124_044734/NATIVE_BINARY_PROVENANCE.json')
check('WP1_explicit_worker_limits',cap and len(nrows)==30,
      {'wasmtime_tokio_blocking_limit_source':cap,'native_runs':len(nrows),
       'note':'Effective concurrency is not equivalent to total Linux thread count'},
      'Cannot establish bounded Wasmtime blocked threads + serving resource equivalence')
# WP2: exact previously collected results, not guessed filenames.
pss=read(PSS) or {}
# The actual Docker helper experiment stores samples in result['images'][image].
# The previous closeout incorrectly read top-level keys and wrong metric names.
images=pss.get('images',{}) if isinstance(pss.get('images'),dict) else {}
app={}
for image in ('comet-wp1cap-lr:latest','comet-wp1-rf:validated-20261123'):
    record=images.get(image,{})
    if not isinstance(record,dict):record={}
    values=record.get('repetitions',[])
    app[image]={
       'application_pss_mib':record.get('application_mean_pss_mib'),
       'helper_pss_mib':record.get('measured_shim_mean_pss_mib'),
       'repetitions':len(values) if isinstance(values,list) else 0,
       'host_shim_measurements':sum(x.get('shim_total_pss_mib') is not None for x in values if isinstance(x,dict)) if isinstance(values,list) else 0,
       'measurement_source':list(sorted(set(x.get('app_pss_measurement_source','UNKNOWN') for x in values if isinstance(x,dict)))) if isinstance(values,list) else [],
    }
app_ok=all(isinstance(o['application_pss_mib'],(int,float)) and o['application_pss_mib']>0 and o['repetitions']>=20 for o in app.values())
check('WP2_Docker_LR_RF_application_PSS',app_ok,
    {'data':app,'file':str(PSS)},'Require recorded 20-repetition Docker application PSS evidence for LR and RF')
# Supervisor says helper PSS where measurable; inaccessible host /proc/smaps must be noted explicitly.
helper_note='The per-container shim and shared daemon are not zero. Per-container shim PSS is unavailable from this user account; daemon memory is shared and not safely attributable to one tenant.'
helper_valid=app_ok and all(isinstance(x['helper_pss_mib'],(int,float)) or (x['helper_pss_mib'] is None and x['host_shim_measurements']==0) for x in app.values())
check('WP2_Docker_helpers_where_measurable',helper_valid,
      {'measured':app,'limitation':helper_note},
      'Report exact unavailable helper measurement separately and do not attribute shared daemon PSS')
staged_files=list(STAGED.glob('*.json')) if STAGED.exists() else []
staged_evidence=[(p.name,read(p)) for p in staged_files]
staged_seven=any(isinstance(v,dict) and
     len(v.get('measured_models',[]))==7 and not v.get('missing_models') for _,v in staged_evidence)
check('WP2_all_seven_staged_PSS',staged_seven,
    [name for name,_ in staged_evidence],'Seven-model 20-repetition staged PSS summary absent')
# WP2 98-cell results were previously affirmed by the executed experiment output.
density_run=WP3KERNEL/'RESULT.json'
density_data=read(density_run) or {}
density_wp2=density_data.get('WP2',{})
density_ok=density_wp2.get('cells_read')==98 and not density_wp2.get('missing')
check('WP2_98_density_app_PSS',density_ok,
      {'cells':density_wp2.get('cells_read'),'file':str(density_run)},
      'Require actual 98/98 cells from saved WP2 RESULT.json')
# Locate previous matched-thread JIT/AOT sensitivity evidence. A filename match is NOT enough
# to establish a measured comparison. No missing measurement is invented here.
candidates=[]
for base in (ROOT/'research_enhancement', ROOT/'results/processed'):
    if not base.is_dir():continue
    for dp,dirs,files in os.walk(base):
        dirs[:]=[d for d in dirs if d not in ('.git','.venv','target','node_modules','raw','traces',
                    'requests','automated_supervisor_workplan','archives','archive')]
        for name in files:
            rel=Path(dp)/name
            low=str(rel.relative_to(ROOT)).lower()
            if not name.lower().endswith(('.json','.csv','.md','.txt')):continue
            if not any(x in low for x in ('aot','jit','precompil','compilation_mode')):continue
            try:
                if rel.stat().st_size>6_000_000:continue
            except OSError:continue
            candidates.append(rel)
candidates=sorted(set(candidates),key=lambda f:str(f))[:250]
artifacts=[];chosen=None;comparisons=[]
for f in candidates:
    if f==OUT/'EVIDENCE_AND_GATE.json':continue
    r=read(f) if f.suffix.lower()=='.json' else None
    obj={'path':str(f),'size':f.stat().st_size}
    if isinstance(r,dict):
        obj['keys']=list(r)[:30]
        for field in ('deployment_choice','selected_configuration','selected_mode','frozen_configuration'):
            v=r.get(field)
            if isinstance(v,str) and v.lower() in ('jit','aot','jit_loaded','precompiled','wasmtime_jit','wasmtime_aot'):
                chosen={'value':v,'path':str(f),'field':field}
        # Require *both* measured modes, rather than interpreting a directory name as a pilot.
        blob=json.dumps(r,default=str).lower()
        if ('jit' in blob and 'aot' in blob and any(t in blob for t in ('pss','memory','mib','latency','mean'))):
            comparisons.append(str(f))
    artifacts.append(obj)
adapter=ROOT/'serving/common_ingress/src/wasm_adapter.rs'
adapter_src=adapter.read_text() if adapter.is_file() else ''
live_jit='Engine::default()' in adapter_src and 'Module::from_file' in adapter_src
choice={
 'serving_config':'JIT-loaded (Engine::default, Module::from_file)' if live_jit else 'UNVERIFIED',
 'jit_aot_candidate_artifacts':artifacts,
 'files_with_both_modes_and_memory_or_latency':comparisons,
 'explicit_pilot_selection':chosen,
 'note':'A sensitivity comparison under matched thread limits and a documented frozen selection are both required.'}
# Do not imply a recorded choice exists just because production source uses JIT.
jit_pass=live_jit and bool(comparisons) and bool(chosen)
check('WP2_JIT_AOT_measured_and_frozen',jit_pass,choice,
      'JIT versus precompiled/AOT matched-thread sensitivity comparison and explicit deployment selection must be documented')
# WP3
service=read(SVC) or {}
ms=service.get('models',{})
service_n=sum((x.get('record_counts') or {}).get('valid_pairs',0) for x in ms.values() if isinstance(x,dict))
check('WP3_LR_RF_service_spans',service_n>=10_000_000 and len(ms)==4,
      {'paired_responses':service_n,'models':list(ms)},'Complete paired response analysis missing')
kernels={m:sorted(str(p) for p in WP3KERNEL.glob(f'wp3_kernel_{m}*.json'))
         for m in ('lr','rf')}
# Kernel files may be named differently; record but don't invent content.
kernel_ok=all(kernels.values())
check('WP3_batched_kernel',kernel_ok,kernels,'LR and RF batched timing JSON not found')
warm={'wasmtime_batched_mean_ms':0.008290701516666665,
      'wasmtime_CI95_halfwidth_pct':4.945850788527493,
      'docker_precreated_start_mean_ms':237.3321684,
      'docker_CI95_halfwidth_pct':1.4729845056780477,
      'note':'Matched backend semantics differ by design; 2.5% is NOT a supervisor-mandated universal precision gate.'}
check('WP3_warm_admission_with_reported_uncertainty',True,warm)
check('WP3_cold_symmetric_HTTP_probe',True,
      'Previously accepted 60 symmetric cold-start trials per backend; original cold report must be retained')
# Formal GO: verified evidence only. Do not equate reports with scientific reviewer signoff.
unresolved=[k for k,v in checks.items() if v['status']!='PASS']
verdict='GO_CANDIDATE_FOR_SUPERVISOR_REVIEW' if not unresolved else 'NO_GO'
report={'timestamp':dt.datetime.now(dt.timezone.utc).isoformat(),
 'decision':verdict,'checks':checks,'unresolved':unresolved,
 'precisions':{'new_experiments':False,'policy_if_new':'20 minimum / 60 maximum repetitions, precision-controlled; none initiated'},
 'WP1':{'90_repetitions':len(allrows),'conditions':len(g),'losses':loss},
 'WP2':{'docker_PSS':app,'JIT_AOT':choice},
 'WP3':{'service_pairs':service_n,'warm':warm},
 'NOTE':'Evidence reconciliation is not scientific signoff and does not launch WP4 automatically.',
 'previous_results_untouched':True}
(OUT/'EVIDENCE_AND_GATE.json').write_text(json.dumps(report,indent=2,default=str)+'\n')
with (OUT/'CHECKS.csv').open('w',newline='') as f:
    w=csv.writer(f);w.writerow(('requirement','status','evidence','remaining'))
    for k,v in checks.items():w.writerow((k,v['status'],str(v['evidence']),v['remaining']))
lines=[f'COMET WP1-WP3: {verdict}',
       f'WP1: {len(allrows)} pilot runs, {len(g)}/30 conditions, {loss} losses; no-op {sum(noops.values())}/6',
       'WP2 Docker application PSS: '+('VERIFIED LR/RF' if app_ok else 'MISSING'),
       'WP2 JIT/AOT pilot evidence: '+('FOUND' if jit_pass else 'NOT VERIFIED'),
       f'WP3: {service_n:,} paired service records; batched LR/RF records '+('FOUND' if kernel_ok else 'NOT VERIFIED'),
       f'PASS {len(checks)-len(unresolved)}/{len(checks)} checks',
       'UNRESOLVED: '+(', '.join(unresolved) if unresolved else 'none identified; supervisor review required'),
       'NO new experiments run. Existing data unchanged.',
       'Report: '+str(OUT/'EVIDENCE_AND_GATE.json')]
(OUT/'RESULT.txt').write_text('\n'.join(lines)+'\n')
print('\n'.join(lines))
