#!/usr/bin/env python3
"""Patch the user's locally validated WP1 runner into a conservative adaptive 20-60 runner.

Preserves historical files and data. No experiment is started by this patcher.
The original WP1 code is owned by the user and is patched at their HPC location.
"""
from pathlib import Path
import ast
import sys

SRC=Path('COMET_Auto_Workplan_RF_Validated_20261123.py')
DST=Path('COMET_Auto_Workplan_RF_Adaptive_20261123.py')

def replace_once(s, old, new, label):
    k=s.count(old)
    if k != 1:
        raise RuntimeError(f'{label}: expected one source anchor, found {k}; refusing to create runner')
    return s.replace(old,new,1)

ADAPTIVE='''
# Additional statistics for the supervisor's 20-60 repeated-run precision protocol.
def adaptive_precision(rows, model, backend, rate, max_reps):
    import random
    import hashlib
    vals = [r for r in rows if r.get('model') == model and
            r.get('backend') == backend and r.get('offered_rps') == rate]
    vals.sort(key=lambda r: r['repeat'])
    n = len(vals)
    result = {'model': model, 'backend': backend, 'rate': rate, 'n': n,
              'target_relative_half_width_pct': 2.5,
              'maximum_repetitions': max_reps, 'metrics': {},
              'precision_accepted': False}
    if n < 20:
        result['decision'] = 'MINIMUM_REPETITIONS_PENDING'
        return result
    if [r['repeat'] for r in vals] != list(range(1, n+1)):
        raise Blocker(f'Noncontiguous or repeated repetition indices: {model}/{backend}/{rate}')
    try:
        from scipy.stats import t as tdist
        critical = float(tdist.ppf(0.975, n - 1))
        method = 'scipy_exact_t'
    except ImportError:
        # Conservative relative to the exact 95% Student-t cutoff for df>=19.
        critical = 2.093024054
        method = 'conservative_t_df19'
    accepted = True
    for metric in ('p50_ms','p95_ms','p99_ms','achieved_success_rps_nominal'):
        xs=[r.get(metric) for r in vals]
        if any(not isinstance(x, (int,float)) or not math.isfinite(x) for x in xs):
            result['metrics'][metric]={'accepted':False,'reason':'non-finite_or_missing'}
            accepted=False
            continue
        mean=statistics.mean(xs)
        if mean <= 0:
            result['metrics'][metric]={'accepted':False,'reason':'non-positive_mean','mean':mean}
            accepted=False
            continue
        t_pct=100*critical*statistics.stdev(xs)/math.sqrt(n)/mean
        seed=int.from_bytes(hashlib.sha256(f'{model}:{backend}:{rate}:{metric}'.encode()).digest()[:8],'big')
        rng=random.Random(seed)
        boots=sorted(statistics.mean(rng.choices(xs,k=n)) for _ in range(1200))
        low,high=boots[29],boots[1169]  # percentile CI, approx 2.5% / 97.5%
        b_pct=100*max(abs(mean-low),abs(high-mean))/mean
        passed=t_pct<=2.5 and b_pct<=2.5
        accepted=accepted and passed
        result['metrics'][metric]={'n':n,'mean':mean,'student_t_half_width_pct':round(t_pct,5),
           'bootstrap_half_width_pct':round(b_pct,5),'accepted':passed,'t_method':method}
    result['precision_accepted']=accepted
    result['decision']='PRECISION_ACCEPTED' if accepted else (
       'MAX_REPETITIONS_PRECISION_NOT_MET' if n>=max_reps else 'EXTEND')
    return result

def save_adaptive_precision(out, report, model, backend, rate, max_reps):
    p=adaptive_precision(report['WP1']['runs'],model,backend,rate,max_reps)
    path=out/'adaptive_precision.json'
    current=json.loads(path.read_text()) if path.is_file() else {}
    current[f'{model}_{backend}_{rate}']=p
    atomic_json(path,current)
    return p
'''


def main():
    if not SRC.is_file():raise RuntimeError('Validated RF runner missing; run from repository root')
    if DST.exists():raise RuntimeError(f'{DST} exists; refusing to overwrite a previous version')
    s=SRC.read_text()
    if "image='comet-wp1-rf:validated-20261123'" not in s:
        raise RuntimeError('Input is not the expected RF-validated runner')
    if 'sha256:694b2945ddfb6758e9ebd3f24435cd5ba74a0953faf493e54a0def73d15bbd9f' not in s:
        raise RuntimeError('Frozen RF image ID absent from input')
    s=replace_once(s,"def run_auto(args):",ADAPTIVE+"\ndef run_auto(args):",'add stats')
    s=replace_once(s,
        "must(args.repetitions>=2 and args.repetitions<=20,'Repetitions must be 2..20')",
        "must(args.repetitions==20 and args.max_repetitions==60,'Supervisor protocol requires --repetitions 20 --max-repetitions 60')",
        'bounds')
    s=replace_once(s,
        "ap.add_argument('--repetitions',type=int,default=3)",
        "ap.add_argument('--repetitions',type=int,default=20)\n    ap.add_argument('--max-repetitions',type=int,default=60)",
        'cli')
    s=replace_once(s,
        "'repetitions':args.repetitions,",
        "'repetitions':args.repetitions,'max_repetitions':args.max_repetitions,",
        'freeze config')
    s=replace_once(s,
        "if args.resume and backend_complete(out,model,backend,args):",
        "if False and args.resume and backend_complete(out,model,backend,args):",
        'disable unsafe fixed-count whole-backend skip')
    # The inner repetition loop is uniquely anchored by the rate-specific trace creation.
    s=replace_once(s,
        '''                        trace,gold=prepare_trace(out,model,count)
                        for rep in range(1,args.repetitions+1):
                            prefix=folder/f'rps{rate}_rep{rep}'
                            if (prefix.with_suffix('.summary.json')).is_file() and (prefix.with_suffix('.requests.jsonl')).is_file():
                                print('EXISTS',key,rate,rep,'(resume; preserving)',flush=True);continue''',
        '''                        trace,gold=prepare_trace(out,model,count)
                        for rep in range(1,args.max_repetitions+1):
                            if rep > args.repetitions:
                                current=save_adaptive_precision(out,report,model,backend,rate,args.max_repetitions)
                                if current['precision_accepted']:
                                    print('PRECISION ACCEPTED',key,'rate',rate,'n',current['n'],flush=True)
                                    break
                            prefix=folder/f'rps{rate}_rep{rep}'
                            if (prefix.with_suffix('.summary.json')).is_file() and (prefix.with_suffix('.requests.jsonl')).is_file():
                                if not any(z['model']==model and z['backend']==backend and
                                           z['offered_rps']==rate and z['repeat']==rep for z in report['WP1']['runs']):
                                    raise Blocker(f'Raw files exist without checkpoint row for {key} rate {rate} rep {rep}: reconcile before resume')
                                print('EXISTS',key,rate,rep,'(resume; preserving)',flush=True);continue''',
        'adaptive inner loop and resume')
    s=replace_once(s,
        '''                        # stop rate ramp after all repetitions show definite loss; record lower rate first.
                        rr=[z for z in report['WP1']['runs'] if z['model']==model and z['backend']==backend and z['offered_rps']==rate]
                        if len(rr)>=args.repetitions and all(not z['correctness_pass'] for z in rr[-args.repetitions:]):''',
        '''                        precision=save_adaptive_precision(out,report,model,backend,rate,args.max_repetitions)
                        print('PRECISION',key,rate,precision['decision'],'n',precision['n'],flush=True)
                        # stop rate ramp after all repetitions show definite loss; record lower rate first.
                        rr=[z for z in report['WP1']['runs'] if z['model']==model and z['backend']==backend and z['offered_rps']==rate]
                        if len(rr)>=args.repetitions and all(not z['correctness_pass'] for z in rr[-args.repetitions:]):''',
        'precision reporting')
    # Ensure a bounded non-precision outcome remains non-accepted; the parent already
    # leaves supervisor-level acceptance to separate evidence review.
    ast.parse(s,filename=str(DST))
    DST.write_text(s)
    print('CREATED:',DST)
    print('Validated image preserved, adaptive 20-60 per rate, 95% Student-t + bootstrap, 2.5% criterion')
    print('Existing historical pilot and base runner unchanged; no experiments executed')

if __name__=='__main__':
    try:main()
    except Exception as exc:
        print('PATCH REFUSED:',exc,file=sys.stderr);sys.exit(2)
