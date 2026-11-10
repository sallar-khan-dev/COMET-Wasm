#!/usr/bin/env python3
"""COMET-Wasm supervisor-plan checkpoint after WP1 capacity collection.

Automated WP2 *processing* and evidence audit, without repeating seven-density runs.
Honours supervisor WP2 N=1,5,10,20,50,100,200, Docker memory attribution,
and JIT/AOT configuration pilot; WP1 acceptance kept separate.
Run from /home/sallar/wasiMultitenant with .venv/bin/python.
No process/container launch; no modification of prior results/source.
"""
import csv, datetime as dt, hashlib, json, math, os, re, sys
from collections import defaultdict
from pathlib import Path
from statistics import mean

ROOT=Path(__file__).resolve().parent
LEVELS=[1,5,10,20,50,100,200]
MODELS=['lr','nb','dt','kmeans','rf','svm','mlp']
BACKENDS=['wasmtime','docker']
OUTROOT=ROOT/'research_enhancement/automated_supervisor_workplan/wp2_processing'


def locate_csv():
    priority=[
        ROOT/'results/processed/density/density_seven_levels_statistical_summary.csv',
        ROOT/'results/processed/density/density_seven_levels_summary.csv',
        ROOT/'results/processed/density_seven_levels_statistical_summary.csv',
    ]
    extra=list((ROOT/'results').glob('**/*density*seven*summary*.csv')) if (ROOT/'results').exists() else []
    extra+=list((ROOT/'research_enhancement').glob('**/*density*seven*summary*.csv')) if (ROOT/'research_enhancement').exists() else []
    seen=set()
    for p in priority+sorted(extra,key=lambda x:len(x.parts)):
        if str(p) in seen:continue
        seen.add(str(p))
        if p.is_file():return p
    return None


def pick(fields, keys):
    low={re.sub('[^a-z0-9]','',k.lower()):k for k in fields}
    for k in keys:
        match=low.get(re.sub('[^a-z0-9]','',k.lower()))
        if match:return match
    return None


def num(v):
    try:
        x=float(v)
        return x if math.isfinite(x) else None
    except (TypeError,ValueError):return None


def same_backend(v):
    s=str(v).lower().strip()
    if 'wasm' in s:return 'wasmtime'
    if 'docker' in s or 'container' in s:return 'docker'
    return s


def load_summary(p):
    with p.open(newline='') as f:
        reader=csv.DictReader(f)
        data=list(reader)
        fields=reader.fieldnames or []
    cols={
        'model':pick(fields,['model','workload','model_name']),
        'backend':pick(fields,['backend','runtime','deployment']),
        'n':pick(fields,['tenants','physical_tenants','physical_units','density','tenant_count','N']),
        'pss':pick(fields,['pss_mib_mean','pss_mean_mib','mean_pss_mib','total_pss_mean_mib','total_pss_mib','mean_pss','pss_mib','pss_mean_kib','mean_pss_kib','pss_kib']),
        'samples':pick(fields,['n_runs','repetitions','samples','n','count']),
        'ci':pick(fields,['pss_mib_ci95_relative_pct','ci95_relative','relative_half_width_percent','relative_ci_halfwidth_percent','ci95_relative_half_width','ci_relative','ci95_halfwidth_mib']),
    }
    if any(cols[k] is None for k in ('model','backend','n','pss')):
        return [],[f'CSV columns unrecognized; fields={fields}; resolved={cols}'],cols
    result=[];errors=[]
    for index,raw in enumerate(data,2):
        try:
            n=int(float(raw[cols['n']]))
            pss=num(raw[cols['pss']])
            if pss is None or pss<0:raise ValueError('invalid PSS')
            if 'kib' in cols['pss'].lower():pss/=1024.0
            row={'model':raw[cols['model']].strip().lower(), 'backend':same_backend(raw[cols['backend']]),'tenants':n,'pss_mib':pss,'source_row':index}
            if cols['samples']:row['samples']=num(raw.get(cols['samples']))
            if cols['ci']:
                row['reported_ci']=num(raw.get(cols['ci']))
                row['ci_units']='percent' if 'pct' in cols['ci'].lower() or 'percent' in cols['ci'].lower() else 'unspecified'
            result.append(row)
        except (ValueError,TypeError,KeyError) as e:errors.append(f'CSV line {index}: {e}')
    return result,errors,cols


def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1<<20),b''):h.update(b)
    return h.hexdigest()


def matches(root,patterns,max_items=10):
    found=[]
    for pat in patterns:
        for p in sorted(root.glob(pat)):
            if p.is_file() and str(p) not in found:
                found.append(str(p.relative_to(ROOT)))
                if len(found)>=max_items:return found
    return found


def main():
    import argparse
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out',help='Output directory; default new timestamp under wp2_processing')
    args=ap.parse_args()
    if not (ROOT/'research_enhancement').exists():
        raise SystemExit('Run from project root: /home/sallar/wasiMultitenant')
    stamp=dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d_%H%M%S')
    out=Path(args.out).resolve() if args.out else OUTROOT/stamp
    out.mkdir(parents=True,exist_ok=False)
    evidence={'generated_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'work_package':'WP2', 'supervisor_levels':LEVELS,'outputs_are_derived_only':True,'wp1_acceptance':'REVIEW: no-op 4800 RF/Docker loss, 2400 LR/Wasmtime inflight-capacity loss; do not declare WP1 passed','source':None,'checks':{},'remaining':[]}
    lines=['# COMET-Wasm: next supervisor-plan checkpoint','', '## Scope','WP1 capacity data collected but not formally accepted. WP2 permits parallel work after thread control; this checkpoint processes existing WP2 density data without rerunning experiments.','','## WP2 evidence']
    source=locate_csv()
    if source is None:
        evidence['checks']['density_summary']='MISSING'
        evidence['remaining'].append('Locate or generate official seven-level statistical summary from existing raw measurements; do not rerun measurements.')
        lines+=['- **BLOCKED**: Seven-level density statistical summary CSV not found.']
        rows=[];errors=[]
    else:
        evidence['source']={'path':str(source.relative_to(ROOT)),'sha256':sha(source)}
        rows,errors,cols=load_summary(source)
        evidence['columns']=cols
        if errors:lines+=['- Parsing warnings: '+ '; '.join(errors[:4])]
        groups=defaultdict(list)
        for r in rows:groups[(r['model'],r['backend'],r['tenants'])].append(r)
        required={(m,b,n) for m in MODELS for b in BACKENDS for n in LEVELS}
        present=set(groups)
        missing=sorted(required-present)
        duplicate=sorted((k,len(v)) for k,v in groups.items() if len(v)!=1)
        evidence['checks']['density_98_cells']='PASS' if not missing and not duplicate and not errors else 'REVIEW'
        ci_values=[r.get('reported_ci') for r in rows if r.get('reported_ci') is not None]
        evidence['precision']={'reported_ci_cells':len(ci_values),'reported_ci_unit': 'percent' if cols['ci'] and ('pct' in cols['ci'].lower() or 'percent' in cols['ci'].lower()) else 'unknown', 'max_reported_relative_ci_pct':max(ci_values) if ci_values else None, 'ci_over_2p5_pct':sum(v>2.5 for v in ci_values) if ci_values else None}
        lines+=['- Statistical precision: '+str(evidence['precision'])+'; 2.5% is a pre-existing experimental precision target, not a new supervisor WP2 acceptance threshold.']
        evidence['coverage']={'observed_rows':len(rows),'required_cells':98,'present_required_cells':len(required & present),'missing':missing,'duplicate_cells':duplicate,'unrecognized':sorted(present-required)}
        lines+= [f'- Source: `{source.relative_to(ROOT)}` (SHA256 {sha(source)[:16]}...)',f'- Required 7 models × 2 backends × 7 densities = **98 cells**; present {len(required & present)}/98.']
        if missing:lines+=['- Missing cells: '+str(missing[:12])]
        if duplicate:lines+=['- Duplicate cells: '+str(duplicate[:12])]
        profiles=[]
        for m in MODELS:
            for b in BACKENDS:
                curve={n:groups[(m,b,n)][0] for n in LEVELS if len(groups[(m,b,n)])==1}
                if not all(n in curve for n in LEVELS):continue
                base=curve[1]['pss_mib']
                for n in LEVELS:
                    p=curve[n]['pss_mib']
                    profiles.append({'model':m,'backend':b,'tenants':n,'observed_total_pss_mib':round(p,8), 'delta_vs_n1_mib':round(p-base,8), 'average_increment_per_tenant_from_n1_mib':round((p-base)/(n-1),8) if n>1 else None,'data_type':'measured summary (not helper-adjusted)'})
        if profiles:
            with (out/'wp2_derived_curve.csv').open('w',newline='') as f:
                writer=csv.DictWriter(f,fieldnames=list(profiles[0]));writer.writeheader();writer.writerows(profiles)
            lines+=['- Saved **measured** density/delta curves in `wp2_derived_curve.csv`; delta relative to N=1 is not independently measured base/model-resident memory.']
        # No assumptions about original memory provenance.
        memfiles=matches(ROOT,['results/**/*helper*memory*','research_enhancement/**/*helper*pss*','results/**/*daemon*pss*','research_enhancement/**/*base*model*memory*'],15)
        aotfiles=matches(ROOT,['research_enhancement/**/*aot*pilot*','research_enhancement/**/*jit*aot*','results/**/*aot*memory*','results/**/*jit*aot*'],15)
        evidence['candidate_helper_evidence']=memfiles
        evidence['candidate_aot_evidence']=aotfiles
        evidence['checks']['docker_application_plus_helper_pss']='REVIEW' if memfiles else 'NOT_ESTABLISHED'
        evidence['checks']['jit_vs_aot_comparable_pilot']='REVIEW' if aotfiles else 'NOT_ESTABLISHED'
        evidence['checks']['independent_base_and_model_resident_memory']='NOT_ESTABLISHED'
        evidence['checks']['piecewise_in_measured_range']='DESIGN REQUIREMENT: no extrapolation; no production scheduler changes performed'
        lines+=['- Docker daemon/helper PSS evidence: '+(', '.join(f'`{x}`' for x in memfiles) if memfiles else '**not demonstrated by source summary**'),'- Wasmtime JIT/AOT pilot evidence: '+(', '.join(f'`{x}`' for x in aotfiles) if aotfiles else '**not demonstrated by source summary**')]
        if not memfiles:evidence['remaining'].append('WP2: obtain separately attributable Docker application and helper/runtime PSS with consistent process coverage.')
        if not aotfiles:evidence['remaining'].append('WP2 §5.1: run or locate comparable JIT-loaded vs AOT/precompiled Wasmtime pilot under same thread limits.')
        evidence['remaining'].append('WP2: establish base, resident-model and incremental memory attribution separately; N=1 total PSS is not a base-memory measurement.')
        if missing or duplicate or errors:evidence['remaining'].append('WP2: investigate genuine missing/duplicate/corrupt rows in saved data before accepting curves.')
    # The native baseline and headroom remain WP1 gates, not WP2 acceptance.
    lines+=['','## Acceptance and next execution boundary','- **WP1:** REVIEW; the client/gateway no-op envelope and native attribution are not conclusively accepted by current summaries.','- **WP2:** REVIEW; never infer total process, helper, and model-resident memory from a single total-PSS column.','- **WP3:** Not started by this script, because the supervisor requires paired batched-kernel and matched admission timing protocols.','- **WP4:** Existing kernel runs retained. No final service crossover claim.','- **WP5/WP6:** Not started; supervisor stop/go after WP1–WP3 remains in force.','','## Outstanding actions']
    lines.extend(f'- {x}' for x in evidence['remaining'])
    (out/'WP1_WP2_CHECKPOINT.md').write_text('\n'.join(lines)+'\n')
    (out/'evidence.json').write_text(json.dumps(evidence,indent=2)+'\n')
    print('COMET supervisor-plan checkpoint | WP2 corrected existing data processing, NO reruns')
    print('OUT:',out)
    print('WP2 statistical grid:',evidence['checks'].get('density_98_cells','MISSING'))
    print('Docker helper attribution:',evidence['checks'].get('docker_application_plus_helper_pss','MISSING'))
    print('AOT/JIT pilot:',evidence['checks'].get('jit_vs_aot_comparable_pilot','MISSING'))
    print('WP1: ACCEPTANCE REVIEW; WP2: '+ ('DATA PROCESSED, ACCEPTANCE REVIEW' if source else 'SUMMARY MISSING'))
    print('NEXT: Review WP1_WP2_CHECKPOINT.md (single report).')

if __name__=='__main__':main()
