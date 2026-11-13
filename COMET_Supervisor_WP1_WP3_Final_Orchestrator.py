#!/usr/bin/env python3
"""COMET-Wasm supervisor work plan: full WP1-WP3 experiment orchestrator and stop/go dossier.

Run once on the HPC project root. Existing valid campaigns are retained and audited;
missing entire prescribed campaign(s) are launched with their EXISTING approved
project runners. Never re-run an existing campaign merely to improve results.
DOES NOT declare a scientific GO on incomplete/unequal measurements.

Covered: WP1 common ingress/golden/capacity/no-op, WP2 7-level density,
Docker PSS attribution and Wasmtime JIT-vs-AOT, WP3 batched execution and
cold start vs warm admission. Preserves every source and raw record.
"""
import argparse, csv, datetime as dt, hashlib, json, os, pathlib, subprocess, sys, traceback
from collections import Counter

ROOT=pathlib.Path(__file__).resolve().parent
BASE=ROOT/'research_enhancement/automated_supervisor_workplan'
MODELS=('lr','nb','dt','kmeans','rf','svm','mlp')
LEVELS=(1,5,10,20,50,100,200)
BACKENDS=('wasmtime','docker')


def latest(pattern, required=()):
    found=[]
    for p in BASE.glob(pattern):
        if p.is_dir() and all((p/x).is_file() for x in required):found.append(p)
    return sorted(found, key=lambda p:p.stat().st_mtime)[-1] if found else None


def jread(p):
    try:return json.loads(p.read_text())
    except (OSError,ValueError):return None


def run_existing(script, args, log):
    src=ROOT/script
    if not src.is_file():
        return {'status':'BLOCKED','reason':f'Missing actual project experiment runner: {src}'}
    cmd=[sys.executable,str(src),*args]
    print('RUN FULL EXISTING CAMPAIGN:', ' '.join(cmd),flush=True)
    with log.open('w') as f:
        p=subprocess.run(cmd,cwd=ROOT,stdout=f,stderr=subprocess.STDOUT)
    return {'status':'EXECUTED' if p.returncode==0 else 'BLOCKED', 'returncode':p.returncode,'runner':script,'log':str(log.relative_to(ROOT))}


def density():
    p=ROOT/'results/processed/density/density_seven_levels_statistical_summary.csv'
    if not p.is_file():return {'status':'BLOCKED','reason':'Supervisor WP2 seven-level density statistical summary missing; must use original validated density runner, not reconstruct PSS.'}
    with p.open(newline='') as f:rs=list(csv.DictReader(f))
    seen=Counter();valid=0
    for r in rs:
        try:
            m=r['model'].strip().lower();b=r['backend'].strip().lower();n=int(r['physical_tenants']);x=float(r['pss_mib_mean'])
            if m in MODELS and b in BACKENDS and n in LEVELS and x>=0:
                seen[m,b,n]+=1;valid+=1
        except (KeyError,TypeError,ValueError):pass
    expected={(m,b,n) for m in MODELS for b in BACKENDS for n in LEVELS}
    missing=sorted(expected-set(seen));duplicates=[list(k) for k,v in seen.items() if v!=1]
    return {'status':'EVIDENCE_PRESENT' if not missing and not duplicates else 'BLOCKED','source':str(p.relative_to(ROOT)), 'valid_rows':valid,'required_cells':98,'present_cells':len(expected&set(seen)),'missing_cells':missing,'duplicate_cells':duplicates,
            'interpretation':'Coverage only, full WP2 acceptance also requires base, model, incremental and Docker helper separation, and controlled real worker counts.'}


def wp1():
    p=latest('20*/',('state.json','wp1_capacity_summary.csv'))
    if not p:return {'status':'MISSING'}
    state=jread(p/'state.json') or {}
    rows=list(csv.DictReader((p/'wp1_capacity_summary.csv').open(newline='')))
    coverage={(r.get('model'),r.get('backend'),r.get('offered_rps'),r.get('repeat')) for r in rows}
    failed=[]
    for r in rows:
        try:
            if int(r['success'])!=int(r['offered']) or int(r.get('fail') or 0) or int(r.get('drops') or 0) or int(r.get('timeouts') or 0):
                failed.append({k:r.get(k) for k in ('model','backend','offered_rps','repeat','success','offered','fail','drops','timeouts')})
        except (KeyError,ValueError):failed.append({'invalid_row':r})
    noops=[]
    for model in ('lr','rf'):
        for b in BACKENDS:
            for s in (p/f'{model}_{b}').glob('noop*.summary.json'):
                x=jread(s) or {}
                try:
                    offered=int(x['offered_requests']);success=int(x['successful_requests'])
                    noops.append({'file':str(s.relative_to(ROOT)),'offered':offered,'success':success,'loss':offered-success})
                except (KeyError,ValueError,TypeError):noops.append({'file':str(s.relative_to(ROOT)),'unreadable':True})
    return {'status':'EVIDENCE_PRESENT','source':str(p.relative_to(ROOT)), 'state_wp1':(state.get('WP1') or {}).get('status'), 'campaign_cells':len(rows),'unique_cells':len(coverage), 'failed_cells':failed,'noop':noops,
       'acceptance':'REVIEW: 2400 RPS Wasmtime LR in-flight saturation; 4800 no-op RF/Docker losses; gateway/native process and bridge path must be independently established. No numerical headroom threshold is asserted.'}


def wp2_memory():
    p=latest('wp2_memory_attribution/*/',('RESULT.json','trial_summary.csv'))
    if not p:return {'status':'MISSING'}
    data=jread(p/'RESULT.json') or {}
    helper_issue='Helper overhead unresolved; absence of helper evidence must never be treated as zero.'
    return {'status':'EVIDENCE_PRESENT','source':str(p.relative_to(ROOT)), 'result':data, 'acceptance':helper_issue}


def aot():
    p=latest('wp2_jit_aot_pilot/*/',('RESULT.json','trial_summary.csv'))
    if not p:return {'status':'MISSING'}
    return {'status':'EVIDENCE_PRESENT','source':str(p.relative_to(ROOT)),'result':jread(p/'RESULT.json')}


def wp3_kernel():
    p=latest('wp3_batched_kernel/*/',('RESULT.json','samples.csv','manifest.json'))
    if not p:return {'status':'MISSING'}
    data=jread(p/'RESULT.json') or {}; man=jread(p/'manifest.json') or {}
    return {'status':'EVIDENCE_PRESENT','source':str(p.relative_to(ROOT)),'result':data,'batch':man.get('batch'),'rounds':man.get('rounds'),
            'acceptance':'REVIEW: typed-call cost is not pure guest kernel; input copy, HTTP and complete service cost must be decomposed using comparable backend serving measurements.'}


def wp3_startup():
    p=latest('wp3_cold_admission/*/',('RESULT.json','trials.csv','manifest.json'))
    if not p:return {'status':'MISSING'}
    data=jread(p/'RESULT.json') or {};counts={k:(data.get(k) or {}).get('n',0) for k in ('wasmtime_deploy','docker_deploy','wasmtime_admit','docker_admit')}
    return {'status':'EVIDENCE_PRESENT' if all(n>=20 for n in counts.values()) else 'BLOCKED','source':str(p.relative_to(ROOT)), 'counts':counts,'result':data,
       'acceptance':'REVIEW: documented scope difference: common-ingress Wasmtime cold path, direct Docker cold path and separate warm Wasmtime HTTP harness. Do not claim symmetric service readiness until matched.'}


def add(rows,k,v):rows[k]=v;print(f'[{k}] {v["status"]}',flush=True)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--audit-only',action='store_true',help='Only compile dossier; never launch a missing campaign')
    ap.add_argument('--no-wp1-rerun',action='store_true',help='Do not launch WP1 if entire campaign is missing')
    args=ap.parse_args()
    if not (ROOT/'serving/common_ingress').is_dir():sys.exit('BLOCKED: run in actual COMET-Wasm project root')
    out=BASE/'wp1_wp3_stop_go'/f'{dt.datetime.now(dt.timezone.utc):%Y%m%d_%H%M%S}_{os.getpid()}'
    out.mkdir(parents=True,exist_ok=False)
    print('SUPERVISOR WP1-WP3 FULL CAMPAIGN / STOP-GO, OUTPUT:',out,flush=True)
    r={}
    add(r,'WP1',wp1())
    if r['WP1']['status']=='MISSING' and not args.audit_only and not args.no_wp1_rerun:
        r['WP1_full_run']=run_existing('COMET_Auto_Workplan_v4.py',['--mode','auto'],out/'wp1_full_run.log')
        add(r,'WP1',wp1())
    add(r,'WP2_density',density())
    # Existing seven-level measurements must be preserved. Do not invent a replacement runner for missing rows.
    add(r,'WP2_Docker_PSS',wp2_memory())
    if r['WP2_Docker_PSS']['status']=='MISSING' and not args.audit_only:
        r['WP2_PSS_full_run']=run_existing('COMET_WP2_Run_Memory_Experiment.py',[],out/'wp2_pss_full_run.log')
        add(r,'WP2_Docker_PSS',wp2_memory())
    add(r,'WP2_JIT_AOT',aot())
    if r['WP2_JIT_AOT']['status']=='MISSING' and not args.audit_only:
        runner='COMET_WP2_Wasmtime_JIT_AOT_Pilot_v2.py'
        r['WP2_JIT_AOT_full_run']=run_existing(runner,[],out/'wp2_aot_full_run.log')
        add(r,'WP2_JIT_AOT',aot())
    add(r,'WP3_batched_execution',wp3_kernel())
    if r['WP3_batched_execution']['status']=='MISSING' and not args.audit_only:
        runner='COMET_WP3_Batched_Kernel_Pilot_Ready.py' if (ROOT/'COMET_WP3_Batched_Kernel_Pilot_Ready.py').is_file() else 'COMET_WP3_Batched_Kernel_Pilot.py'
        r['WP3_kernel_full_run']=run_existing(runner,[],out/'wp3_kernel_full_run.log')
        add(r,'WP3_batched_execution',wp3_kernel())
    add(r,'WP3_cold_admission',wp3_startup())
    if r['WP3_cold_admission']['status']=='MISSING' and not args.audit_only:
        r['WP3_cold_full_run']=run_existing('COMET_WP3_Cold_Admission_Auto.py',[],out/'wp3_cold_full_run.log')
        add(r,'WP3_cold_admission',wp3_startup())
    blockers=[]
    for k in ('WP1','WP2_density','WP2_Docker_PSS','WP2_JIT_AOT','WP3_batched_execution','WP3_cold_admission'):
        if r[k]['status'] not in ('EVIDENCE_PRESENT',):blockers.append(f'{k}: missing or structurally incomplete evidence')
    # These checks correspond directly to unsatisfied plan criteria, independent of campaign presence.
    blockers.extend([
      'WP1 §4.1/4.3: establish comparable common-ingress native/Wasmtime/Docker attribution and demonstrated generator/gateway headroom without client in-flight bottleneck',
      'WP2 §5: verify base/model/incremental PSS decomposition under matching actual threads, plus independently attributable Docker helpers',
      'WP3 §6.1: separate native kernel, Wasm guest call, copy/host-call and full backend service cost on the same deterministic inputs',
      'WP3 §6.2: reconcile cold and warm timing setup scopes and matched HTTP readiness paths',
    ])
    report={'supervisor_document':'COMET-Wasm Work Plan, sections 4-6, mandatory stop/go checkpoint','project_root':str(ROOT),'out':str(out),'checks':r,'stop_go':'NO_GO_PENDING_EVIDENCE','blockers':blockers,
      'policy':'WP4 as preliminary only; do not redesign WP5 scheduler until WP1-WP3 are trustworthy. No new algorithms, workload models, or acceptance thresholds introduced.'}
    (out/'STOP_GO.json').write_text(json.dumps(report,indent=2,default=str)+'\n')
    lines=['# COMET-Wasm supervisor WP1–WP3 stop/go dossier','','## Full available evidence']
    for k,v in r.items():lines+= [f'- **{k}**: {v.get("status","UNKNOWN")}; {v.get("source",v.get("log",""))}']
    lines+=['','## Mandatory unresolved supervisor-plan criteria']+[f'- {x}' for x in blockers]+['','## Decision','**NO-GO for WP5 scheduler redesign.** WP4 measurements may remain preliminary. This is not a failure of the completed campaigns; evidence is incomplete under the supervisor’s specified comparability requirements.','']
    (out/'STOP_GO.md').write_text('\n'.join(lines))
    print('\nFINAL: NO_GO_PENDING_EVIDENCE (scientific acceptance, not script execution failure)')
    print('DOSSIER:',out/'STOP_GO.md');print('MACHINE REPORT:',out/'STOP_GO.json')
    return 0 if all(r[k]['status']=='EVIDENCE_PRESENT' for k in ('WP1','WP2_density','WP2_Docker_PSS','WP2_JIT_AOT','WP3_batched_execution','WP3_cold_admission')) else 2

if __name__=='__main__':
    try:sys.exit(main())
    except Exception:traceback.print_exc();sys.exit(1)
