#!/usr/bin/env python3
"""Read-only COMET supervisor plan evidence audit (WP1-WP4).

Run from repository root: .venv/bin/python COMET_Supervisor_OneShot_Audit.py
Only Python standard library. No network calls, processes, model inference or writes.
Reports evidence, not unsupported PASS claims. Does not automatically launch experiments.
"""
import csv
import json
import re
from pathlib import Path
from collections import Counter

ROOT = Path.cwd()
RE = ROOT / 'research_enhancement'
OUT = []

def log(s=''): OUT.append(str(s))
def J(p):
    try: return json.loads(p.read_text())
    except (OSError, json.JSONDecodeError): return None

def findfiles(base, pattern, maxn=100000):
    return sorted(base.rglob(pattern))[:maxn] if base.exists() else []

def evidence(name, state, explanation):
    log(f'[{state:10}] {name}: {explanation}')

def peek_stat(d):
    if not isinstance(d, dict): return 'invalid or absent JSON'
    keys=('gate','scope','supervisor_wp1','ci_target_pass','repetitions','offered_requests','successful_requests','failed_requests','dropped_requests','timed_out_requests','late_requests','p95_latency_ms','offered_rps','achieved_rps','throughput_rps','actual_rps','target_rps','mean_rps','relative_ci','relative_95ci','relative_ci_halfwidth','threads','worker_count')
    return '; '.join(f'{k}={d[k]}' for k in keys if k in d)[:320] or f'fields={list(d)[:12]}'

log('COMET-Wasm | Single-run supervisor checkpoint audit')
log('READ ONLY | No inference, network, Docker, process launches or file changes')
log('Repository: '+str(ROOT))
log('')

# WP1: identify code and explicit pass/fail statements.
log('=== WP1: corrected serving, parity, load headroom ===')
for rel in ('serving/common_ingress/src/main.rs', 'serving/common_ingress/src/routes.rs',
            'serving/common_ingress/src/docker_adapter.rs', 'serving/native_lr_server/src/main.rs',
            'research_enhancement/v2_loadgen/src/main.rs','research_enhancement/deterministic_trace.py'):
    f=ROOT/rel
    evidence(rel, 'FOUND' if f.is_file() else 'MISSING', 'source file' if f.is_file() else 'not at expected path')

corrected=RE/'v2_wp1_corrected'
folders=sorted(p for p in corrected.iterdir() if p.is_dir()) if corrected.exists() else []
for p in folders:
    gate=J(p/'GATE.json')
    if isinstance(gate,dict):
        evidence('Corrected WP1 '+p.name, str(gate.get('gate','UNKNOWN')),
                 f"{gate.get('passed_runs','?')}/{gate.get('expected_runs','?')} smoke runs; scope={gate.get('scope','?')}; supervisor_wp1={gate.get('supervisor_wp1','?')}")

for parent in (RE/'v2_foundation_runs',RE/'v2_wp1_combined'):
    sets=sorted((p for p in parent.iterdir() if p.is_dir()),reverse=True) if parent.exists() else []
    if sets:
        d=sets[0]; summaries=list(d.glob('noop*.summary.json'))
        evidence(str(parent.relative_to(ROOT)),'FOUND',f'{len(summaries)} no-op summaries in {d.name} (existence does NOT prove headroom)')
        for f in summaries[:4]: evidence('  '+f.name,'DATA',peek_stat(J(f)))

# Restrict formal scan to summary/aggregate files, not thousands of nested inner reps.
formal=RE/'v2_wp1_workloads'
if formal.exists():
    agg=sorted(p for p in formal.rglob('*') if p.is_file() and p.suffix=='.json' and
          ('statistical_summary' in p.name or p.name in ('GATE.json','outer_summary.json')))
    evidence('Formal WP1 aggregate records','FOUND' if agg else 'MISSING',f'{len(agg)} aggregate/statistical/gate files')
    for p in agg[:12]:
        d=J(p)
        evidence('  '+str(p.relative_to(ROOT)),'DATA',peek_stat(d))
    lrdir=formal/'experiments'
    for label in ('lr_docker_formal_25rps','lr_wasmtime_formal_25rps'):
        x=lrdir/label
        outer=sorted(x.glob('outer_*/outer_summary.json')) if x.exists() else []
        evidence(label,'FOUND' if outer else 'MISSING',f'{len(outer)} outer summaries; formal results are not by themselves proof of complete WP1 acceptance')
        if outer: evidence('  example '+outer[0].parent.name,'DATA',peek_stat(J(outer[0])))

# Look for RF/SVM corrected pilot summaries without huge listing.
for tag in ('rf','svm'):
    hits=[]
    for base in (RE/'v2_wp1_workloads',RE/'v2_wp1_corrected',RE/'v2_wp1_combined'):
        if base.exists():
            hits.extend(p for p in base.rglob('*.summary.json') if re.search(rf'(^|[/_]){tag}([/_]|$)',str(p.relative_to(base)),re.I))
    evidence('Corrected WP1 '+tag.upper()+' runs','FOUND' if hits else 'UNVERIFIED',f'{len(hits)} matching summaries; check parity and acceptance separately')

# WP2 baseline density and memory.
log('\n=== WP2: density, PSS, AOT sensitivity ===')
density=ROOT/'results/processed/density'
for f in ('density_seven_levels_statistical_summary.csv','density_uniform_final_comparison.csv'):
    p=density/f
    if not p.exists(): evidence(f,'MISSING','not found');continue
    try:
        with p.open(newline='') as stream:
            reader=csv.DictReader(stream)
            headers=reader.fieldnames or []
            rows=list(reader)
        values=set()
        for row in rows:
            for k,v in row.items():
                if re.search(r'(^n$|tenant.*count|physical_units|density|tenants)', k or '',re.I):
                    if v and re.fullmatch(r'\d+',v.strip()):values.add(int(v))
        evidence(f,'FOUND',f'{len(rows)} rows; density levels={sorted(values) or "not extractable from columns"}; columns={headers[:12]}')
    except Exception as ex: evidence(f,'ERROR',str(ex))

wp2=sorted(p for p in RE.iterdir() if p.is_dir() and ('wp2' in p.name.lower() or 'density' in p.name.lower())) if RE.exists() else []
evidence('WP2 research directories','FOUND' if wp2 else 'UNVERIFIED',', '.join(p.name for p in wp2[:12]) or 'none')
for key in ('aot','precompiled','jit'):
    hits=[p for d in wp2 for p in d.rglob('*') if p.is_file() and key in p.name.lower()]
    evidence('WP2 '+key+' records','FOUND' if hits else 'UNVERIFIED',f'{len(hits)} named files; presence is not validation')

# WP3 source and outputs.
log('\n=== WP3: batched kernel versus startup/admission ===')
wp3=RE/'wp3_kernel_admission'
if wp3.exists():
    fs=sorted(p for p in wp3.rglob('*') if p.is_file() and 'target' not in p.parts and '.venv' not in p.parts)
    evidence('WP3 source/outputs','FOUND' if fs else 'MISSING',f'{len(fs)} files')
    for p in fs[:32]:
        name=str(p.relative_to(ROOT))
        if p.suffix=='.json': evidence('  '+name,'DATA',peek_stat(J(p)))
        elif p.suffix in ('.py','.rs','.csv'): evidence('  '+name,'FOUND','')
else: evidence('WP3 directory','MISSING','')

# WP4 scaled run summaries: exact filename conventions, no guessing.
log('\n=== WP4: scaled kernel measurements ===')
base=ROOT/'results/processed/wp4_crossover'
variants={'MLP':['mlp_width_64','mlp_width_128','mlp_width_256'],
          'RF':['rf_trees_100','rf_trees_200','rf_trees_400'],
          'SVM':['svm_c_0p3','svm_c_0p1','svm_c_0p03']}
log(f"{'Variant':20} {'W us':>10} {'D us':>10} {'W/D':>7} {'W CI%':>8} {'D CI%':>8} {'Gate':>13}")
complete=0; strict=0
for names in variants.values():
    for v in names:
        pair={}; ambiguity=False
        for b in ('wasmtime','docker'):
            found=sorted(base.glob(f'{b}_{v}_execution_time_full_summary.json'))
            if not found: found=sorted(base.glob(f'{b}_{v}_*_execution_time_full_summary.json'))
            if len(found)==1:pair[b]=J(found[0])
            elif len(found)>1:ambiguity=True
        w,d=pair.get('wasmtime'),pair.get('docker')
        if ambiguity or not isinstance(w,dict) or not isinstance(d,dict):
            log(f'{v:20} '+('AMBIGUOUS' if ambiguity else 'MISSING SUMMARY'))
            continue
        try:
            wm=float(w['execution_mean_ns'])/1000;dm=float(d['execution_mean_ns'])/1000
            wc=100*float(w['execution_relative_95ci']);dc=100*float(d['execution_relative_95ci'])
            good=wc<=2.5 and dc<=2.5
            complete+=1;strict+=int(good)
            log(f'{v:20} {wm:10.3f} {dm:10.3f} {wm/dm:7.3f} {wc:8.3f} {dc:8.3f} {"CI PASS" if good else "CI LIMITED":>13}')
        except (KeyError,TypeError,ValueError,ZeroDivisionError): log(f'{v:20} INVALID FIELDS')
evidence('Scaled kernel coverage','FOUND' if complete==9 else 'INCOMPLETE',f'{complete}/9 pairs present, {strict}/9 meet 2.5% relative CI on both sides')

log('\n=== SUPERVISOR CHECKPOINT DECISION ===')
log('A. Existing WP1 smoke GATE=PASS is *not* supervisor WP1 completion: GATE.json explicitly says NOT COMPLETE.')
log('B. Formal LR experiments and corrected code should be audited for thread parity, bridge topology, no-op headroom and RF/SVM before new work.')
log('C. Confirm WP2 N={1,5,10,20,50,100,200} PSS and JIT/AOT evidence, and WP3 batched K plus symmetric tenant admission, before asserting WP4 crossover.')
log('D. WP4 kernel reversal is observational, not a demonstrated same-gateway service-level/P95 crossover.')
log('E. Do not start WP5 or make a claim of a validated crossover based only on this report.')
log('AUDIT COMPLETE (read-only).')
print('\n'.join(OUT))
