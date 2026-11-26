#!/usr/bin/env python3
"""COMET-Wasm supervisor WP1-3 single-command evidence-first checkpoint.

No fabricated GO: measures/audits what is verifiable; explicitly records method
limitations; may run existing guarded WP1 parity diagnostic to fill a missing
bounded resource observation. Preserves raw results. Never starts WP4/WP5.
"""
import argparse, csv, datetime as dt, json, math, os, pathlib, shutil, subprocess, sys, traceback, fcntl
from collections import defaultdict

ROOT=pathlib.Path(__file__).resolve().parent
BASE=ROOT/'research_enhancement'
AUT=BASE/'automated_supervisor_workplan'
REPORTS=BASE/'reports'
MODELS=('logistic_regression','naive_bayes','decision_tree','kmeans','random_forest','svm','mlp')
DENSITIES=(1,5,10,20,50,100,200)
BACKENDS=('wasmtime','docker')


def readj(p):
    try:return json.loads(p.read_text())
    except (OSError,ValueError,TypeError):return None

def rows(p):
    try:
        with p.open(newline='') as f:return list(csv.DictReader(f))
    except (OSError,csv.Error):return []

def asfloat(v):
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except (ValueError,TypeError):return None

def latest(glob,required=()):
    candidates=[p for p in ROOT.glob(glob) if p.is_dir() and all((p/f).is_file() for f in required)]
    return max(candidates,key=lambda p:p.stat().st_mtime) if candidates else None

def fmt(x):return f'{x:.3f}' if x is not None else 'unavailable'

def runcommand(args, logfile=None, timeout=3600):
    if logfile:
        with logfile.open('w') as f:
            z=subprocess.run(args,stdout=f,stderr=subprocess.STDOUT,cwd=ROOT,timeout=timeout)
        return z.returncode
    return subprocess.run(args,cwd=ROOT,timeout=timeout,capture_output=True,text=True)

def density_check():
    p=AUT/'wp2_seven_model_controlled_audit_20261123/WP2_Seven_Model_98_Conditions.csv'
    raw=rows(p); groups={}; invalid=[]
    for i,r in enumerate(raw,2):
        try:
            key=(r['model'],r['backend'],int(r['tenants']))
            if key in groups:invalid.append(f'duplicate {key}')
            groups[key]=r
            t=asfloat(r['student_t_pct']); b=asfloat(r['bootstrap_pct']); n=int(r['repetitions']); pss=asfloat(r['mean_pss_mib'])
            if any(z is None for z in (t,b,pss)) or n<20 or n>60 or pss<=0:invalid.append(f'invalid {key}')
            if (t is not None and b is not None) and ((t<=2.5 and b<=2.5)!= (r['precision_met'].strip().lower()=='true')):invalid.append(f'CI flag inconsistent {key}')
        except (KeyError,TypeError,ValueError) as e:invalid.append(f'row {i}: {e}')
    expected={(m,b,n) for m in MODELS for b in BACKENDS for n in DENSITIES}
    missing=sorted(expected-set(groups)); extra=sorted(set(groups)-expected)
    accurate=not invalid and not missing and not extra and len(raw)==98
    ci_met=sum(r.get('precision_met','').strip().lower()=='true' for r in raw)
    observations=[]; fits=[]
    if accurate:
        for m in MODELS:
            for b in BACKENDS:
                vec=[(n,asfloat(groups[(m,b,n)]['mean_pss_mib'])) for n in DENSITIES]
                xs=[n for n,v in vec]; ys=[v for n,v in vec]
                xm=sum(xs)/len(xs); ym=sum(ys)/len(ys)
                slope=sum((x-xm)*(y-ym) for x,y in vec)/sum((x-xm)**2 for x in xs)
                intercept=ym-slope*xm
                fits.append({'model':m,'backend':b,'intercept_mib_descriptive':intercept,'incremental_mib_per_tenant_descriptive':slope,'r2_descriptive':1-sum((v-(intercept+slope*n))**2 for n,v in vec)/sum((y-ym)**2 for y in ys) if sum((y-ym)**2 for y in ys) else None})
            low=[n for n in DENSITIES if asfloat(groups[(m,'docker',n)]['mean_pss_mib']) < asfloat(groups[(m,'wasmtime',n)]['mean_pss_mib'])]
            high=[n for n in DENSITIES if asfloat(groups[(m,'wasmtime',n)]['mean_pss_mib']) < asfloat(groups[(m,'docker',n)]['mean_pss_mib'])]
            observations.append({'model':m,'docker_lower_application_pss_densities':low,'wasmtime_lower_application_pss_densities':high})
    audit=readj(AUT/'wp2_seven_model_controlled_audit_20261123/WP2_Controlled_Audit.json') or {}
    helper=readj(REPORTS/'wp2_memory_attribution_20261121/RESULT.json') or {}
    helper_accessible=helper.get('docker_helper_pss')
    return {'passed_coverage':accurate,'raw_conditions':len(raw),'ci_met':ci_met,'missing':missing,'extra':extra,'invalid':invalid[:25],
            'source':str(p.relative_to(ROOT)),'model_curves':observations,'descriptive_linear_fits':fits,
            'readiness_retries':audit.get('readiness_retries_six_model_campaign'),
            'jit_aot':{'reported_aot_reduction_pct':helper.get('observed_aot_pss_reduction_pct'), 'ready_pss_ci_accepted':helper.get('primary_ready_pss_precision_accepted'),'all_component_precision_accepted':helper.get('all_reported_component_precision_accepted')},
            'docker_helper_memory':helper_accessible,
            'limitations':['Fitted intercept/slope describe measured APPLICATION PSS only; they do not isolate OS memory ownership or Docker helper memory.', 'Stage-level JIT/AOT changes measured on LR; do not generalize to every model.', 'Compare physical worker/thread parity at actual experimental serving configurations, not only total thread counts.']}

def wp1_check(out,enable):
    script=ROOT/'COMET_WP1_Parity_Headroom_Checkpoint.py'
    gates=list(ROOT.glob('research_enhancement/wp1_parity_headroom/*/FINAL_GATE.json'))
    passed=[p for p in gates if (readj(p) or {}).get('status','').startswith('DIAGNOSTIC PASS')]
    run_info={'attempted':False,'exit_code':None,'runner':str(script.name),'runner_scope':'bounded pilot, not full sustained no-op capacity envelope'}
    if enable and not passed and script.is_file():
        run_info['attempted']=True
        print('WP1: executing guarded parity/headroom diagnostic (if server preflight allows)',flush=True)
        try:run_info['exit_code']=runcommand([sys.executable,str(script)],out/'wp1_guarded_parity.log',1200)
        except (subprocess.TimeoutExpired,OSError) as e:run_info['error']=str(e)
        gates=list(ROOT.glob('research_enhancement/wp1_parity_headroom/*/FINAL_GATE.json'))
        passed=[p for p in gates if (readj(p) or {}).get('status','').startswith('DIAGNOSTIC PASS')]
    selected=max(passed,key=lambda p:p.stat().st_mtime) if passed else None
    data=readj(selected) if selected else {}
    rs=data.get('runs',[]) if data else []
    parity=bool(data and len(rs)==4 and all((r.get('baseline_resources') or {}) for r in rs))
    resource_observed=bool(parity and all((r.get('measurements',{}).get('infer',{}).get('observed_max_threads') or {}).get('ingress') is not None for r in rs))
    noops=bool(rs and all(r.get('measurements',{}).get('noop',{}).get('successful')==r.get('measurements',{}).get('noop',{}).get('offered') for r in rs))
    pilot=REPORTS/'wp1_rf_svm_parity_60runs_20261120/README.md'
    precision_note='RF/SVM 60-run P95 pilot precision 2/8 conditions (report documents 6 misses)' if pilot.exists() else 'RF/SVM 60-run pilot report not found'
    return {'diagnostic':run_info,'successful_diagnostic_path':str(selected.relative_to(ROOT)) if selected else None,
            'recorded_runs':len(rs),'thread_process_observations':resource_observed,'bounded_noop_lossfree':noops,
            'native_evidence':(REPORTS/'wp1_native_20261121/REPORT.md').exists(),'rf_svm_precision_note':precision_note,
            'requirements_not_proven':['Matched total runnable serving resources/worker semantics across full LR/RF/SVM comparable campaigns.', 'Sustained generator + gateway throughput headroom above fastest backend with client CPU sampling and no client saturation.', 'Same port/network/service configuration, input trace and request semantics for compared results.']}

def wp3_check():
    p=AUT/'wp3_cold_http_ready_seven_models_20261123/RESULT.json'; d=readj(p) or {}; cells=0; misses=[]; n=[]; metric_checks=0
    for m,ns in (d.get('results') or {}).items():
        for tenants,backends in ns.items():
            for backend,metrics in backends.items():
                cells+=1
                for metric,value in metrics.items():
                    metric_checks+=1; n.append(value.get('n',0))
                    if not value.get('accepted',False):misses.append(f'{m}/{tenants}/{backend}/{metric}')
    scope=d.get('scope')
    e=REPORTS/'wp3_evidence_20261121/README.md'
    service=REPORTS/'wp3_service_cost_20261121/README.md'
    return {'direct_endpoint_diagnostic':{'scope':scope,'backend_conditions':cells,'timing_metric_checks':metric_checks,'unaccepted':misses,'repetition_range':([min(n),max(n)] if n else [])},
            'batched_and_decomposed_timing_report_present':e.exists(),'service_cost_report_present':service.exists(),
            'scientific_limitations':['Diagnostic compares direct /infer readiness with different execution topologies, not common-gateway /health parity.', 'Cold deployment vs warm admission scopes differ; the archived warm admission harness is not a symmetric live service topology.', 'Batched kernel/copy/guest-call and full service cost are separate timings; do not equate raw percentile differences with per-request component cost.', 'Previously observed 60-repetition host-copy CI miss should remain reported, not silently called accepted.']}

def git_checkpoint(out, commit):
    state={'requested':commit,'branch':None,'commit':None,'push':None,'detail':None}
    try:
        def cmd(*args):return subprocess.run(['git',*args],cwd=ROOT,capture_output=True,text=True,timeout=120,env={**os.environ,'GIT_TERMINAL_PROMPT':'0'})
        b=cmd('branch','--show-current'); state['branch']=b.stdout.strip()
        if state['branch']!='research/wp1-lr-2026-11-08':state['detail']='Branch differs; no mutation';return state
        if not commit:state['detail']='Git commit disabled; audit only';return state
        chosen=str(out.relative_to(ROOT));p=cmd('add','--',chosen+'/EVIDENCE.json',chosen+'/STOP_GO.md',chosen+'/WP2_LINEAR_DESCRIPTIVE_FITS.csv')
        if p.returncode:state['detail']='git add failed: '+p.stderr[-600:];return state
        diff=cmd('diff','--cached','--name-only'); entries=[x for x in diff.stdout.splitlines() if x]
        if any(not x.startswith(chosen+'/') for x in entries):state['detail']='Other pre-staged files detected; will not include them in a commit';return state
        if entries:
            z=cmd('commit','-m','review: evidence-based WP1-WP3 single-check scientific gate')
            if z.returncode:state['detail']='git commit failed: '+z.stderr[-500:];return state
            state['commit']=cmd('rev-parse','HEAD').stdout.strip()
        else:state['commit']=cmd('rev-parse','HEAD').stdout.strip()
        z=cmd('push','origin',state['branch']);state['push']=z.returncode==0
        state['detail']=(z.stdout+' '+z.stderr)[-1200:]
    except Exception as e:state['detail']=str(e)
    return state

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--no-parity-diagnostic',action='store_true',help='Do not launch the existing guarded WP1 diagnostic when its evidence is missing')
    ap.add_argument('--no-push',action='store_true',help='Do not stage, commit, or push the generated report')
    args=ap.parse_args()
    if not (ROOT/'serving/common_ingress').is_dir() or not (ROOT/'.git').exists():raise SystemExit('Run from real repo root /home/sallar/wasiMultitenant')
    output=REPORTS/'wp1_wp3_one_check_20261123';output.mkdir(parents=True,exist_ok=True)
    lockpath=output/'.checkpoint.lock'
    with lockpath.open('a') as f:
        try:fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise SystemExit('Another checkpoint is already active')
        print('=== COMET SUPERVISOR WP1-WP3 ONE CHECK ===',flush=True)
        evidence={'utc':dt.datetime.now(dt.timezone.utc).isoformat(),'wp1':wp1_check(output,not args.no_parity_diagnostic),'wp2':density_check(),'wp3':wp3_check()}
        blockers=[]
        wp1=evidence['wp1'];wp2=evidence['wp2'];wp3=evidence['wp3']
        if not (wp1['thread_process_observations'] and wp1['bounded_noop_lossfree']):blockers.append('WP1 bounded common-gateway parity/no-op observations missing or blocked.')
        blockers.extend(['WP1 sustained headroom, exact worker parity and comparable serving-path capacity have not been demonstrated by bounded diagnostics.', 'WP2 complete model/base/incremental PSS component OWNERSHIP and Docker helper memory remain unresolved.', 'WP3 same-path symmetric cold /health vs warm admission and common-gateway timing decomposition remain unresolved.'])
        if not wp2['passed_coverage']:blockers.append('WP2 controlled 98-condition coverage integrity invalid.')
        if wp3['direct_endpoint_diagnostic']['backend_conditions']!=42:blockers.append('WP3 direct-endpoint experiment incomplete (expected 42 conditions).')
        evidence['decision']='NO_GO_PENDING_METHODOLOGICAL_ACCEPTANCE' if blockers else 'READY_FOR_SUPERVISOR_GO_REVIEW'
        evidence['blockers']=blockers
        (output/'EVIDENCE.json').write_text(json.dumps(evidence,indent=2,default=str)+'\n')
        with (output/'WP2_LINEAR_DESCRIPTIVE_FITS.csv').open('w',newline='') as f:
            keys=('model','backend','intercept_mib_descriptive','incremental_mib_per_tenant_descriptive','r2_descriptive')
            w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(wp2['descriptive_linear_fits'])
        parts=['# COMET-Wasm WP1-WP3 evidence-first single-run checkpoint','',f'UTC: {evidence["utc"]}','',f'**Decision: {evidence["decision"]}**','',
          '## WP1 serving fairness',f'- Existing bounded parity diagnostic: {wp1["successful_diagnostic_path"] or "not accepted / unavailable"}',f'- Recorded run configurations: {wp1["recorded_runs"]}; threads/proc observable: {wp1["thread_process_observations"]}; bounded no-op loss free: {wp1["bounded_noop_lossfree"]}',f'- {wp1["rf_svm_precision_note"]}',
          '', '## WP2 memory attribution',f'- Seven-model density PSS cells: {wp2["raw_conditions"]}/98; 2.5% CI met: {wp2["ci_met"]}/98.',f'- JIT/AOT LR ready PSS reduction (reported): {fmt(wp2["jit_aot"]["reported_aot_reduction_pct"])} percentage (if available).',f'- Docker helper ownership: {wp2["docker_helper_memory"] or "NOT VERIFIED"}.', '- Descriptive base/slope fits exported to CSV. They are NOT an attribution of memory ownership.',
          '', '## WP3 symmetric startup and timing',f'- Direct-endpoint readiness: {wp3["direct_endpoint_diagnostic"]["backend_conditions"]}/42 conditions; {wp3["direct_endpoint_diagnostic"]["timing_metric_checks"]} timing checks.',f'- Scope: {wp3["direct_endpoint_diagnostic"]["scope"]}.', '- Existing kernel/host-copy/service-cost experiments retained without pooling incompatible serving stacks.',
          '', '## Exact blockers preventing WP4 GO']+[f'{i}. {v}' for i,v in enumerate(blockers,1)]+['',
          '## Scientific interpretation', 'The supervisor explicitly requires STOP/GO after WP1-WP3. Existing experiments are valuable, but measurement precision and file coverage do not by themselves prove comparability or correct subsystem attribution.', 'No WP4/WP5 runner is started. No empirical limitations are silently relabelled as passes.',
          '', '## Source reports', '- research_enhancement/reports/wp1_rf_svm_parity_60runs_20261120/README.md', '- research_enhancement/automated_supervisor_workplan/wp2_seven_model_controlled_audit_20261123/WP2_Controlled_Audit.json','- research_enhancement/reports/wp2_memory_attribution_20261121/RESULT.json','- research_enhancement/reports/wp3_evidence_20261121/README.md','- research_enhancement/automated_supervisor_workplan/wp3_cold_http_ready_seven_models_20261123/RESULT.json','']
        (output/'STOP_GO.md').write_text('\n'.join(parts))
        print('\nDECISION:',evidence['decision'],flush=True)
        print('WP2:',wp2['raw_conditions'],'cells,',wp2['ci_met'],'precision accepted',flush=True)
        print('WP3:',wp3['direct_endpoint_diagnostic']['backend_conditions'],'cells',flush=True)
        for x in blockers:print('BLOCKER:',x,flush=True)
        print('REPORT:',output/'STOP_GO.md',flush=True)
        git=git_checkpoint(output,not args.no_push)
        (output/'GIT_RESULT_LOCAL_ONLY.json').write_text(json.dumps(git,indent=2)+'\n')
        print('GIT:',json.dumps(git),flush=True)
        print('Note: GIT_RESULT_LOCAL_ONLY.json is written AFTER the git checkpoint; it is a local diagnostic, not included in the commit.')
        return 0 if evidence['decision']=='READY_FOR_SUPERVISOR_GO_REVIEW' else 3

if __name__=='__main__':
    try:sys.exit(main())
    except Exception as e:
        print('CHECKPOINT FAILED:',repr(e),file=sys.stderr)
        traceback.print_exc();sys.exit(2)
