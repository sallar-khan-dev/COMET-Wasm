#!/usr/bin/env python3
"""Reanalyse existing WP3 common-gateway cold trial CSV without rerunning or overwriting raw evidence.

Fixes bootstrap relative half-width: max(mean - lower, upper - mean) / mean.
This utility does not change experimental definitions or grant supervisor acceptance.
"""
import argparse, csv, json, math, pathlib, random, statistics, sys, datetime

ROOT=pathlib.Path(__file__).resolve().parent
DEFAULT_ROOT=ROOT/'research_enhancement/automated_supervisor_workplan/wp3_symmetric_common_gateway_cold_20261123'
REPORT_BASE=ROOT/'research_enhancement/reports/wp3_cold_precision_reanalysis_20261123'

def ci(vals, seed=123):
    n=len(vals)
    if n<2 or any(not math.isfinite(v) or v<=0 for v in vals):
        return {'n':n,'accepted':False,'error':'insufficient or invalid observations'}
    try:
        from scipy.stats import t
    except ImportError:
        return {'n':n,'accepted':False,'error':'scipy missing: Student-t unavailable'}
    mean=statistics.mean(vals)
    t_pct=100*float(t.ppf(.975,n-1))*statistics.stdev(vals)/math.sqrt(n)/mean
    rng=random.Random(seed)
    bs=sorted(statistics.mean(vals[rng.randrange(n)] for _ in range(n)) for _ in range(2000))
    lo=bs[int(.025*len(bs))]
    hi=bs[int(.975*len(bs))]
    boot_pct=100*max(mean-lo,hi-mean)/mean
    return {'n':n,'mean_ms':mean,'student_t_pct':t_pct,'bootstrap_pct':boot_pct,
            'bootstrap_95ci_ms':[lo,hi], 'accepted':t_pct<=2.5 and boot_pct<=2.5}

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--run',type=pathlib.Path,help='Directory containing immutable trials.csv')
    args=ap.parse_args()
    if args.run: source=args.run.resolve()
    else:
        candidates=sorted(DEFAULT_ROOT.glob('*/COMPLETE.txt'))
        if not candidates:sys.exit('BLOCKED: no completed WP3 common-gateway cold dataset')
        source=candidates[-1].parent
    raw=source/'trials.csv'
    if not raw.is_file():sys.exit('BLOCKED: missing '+str(raw))
    rows=list(csv.DictReader(raw.open(newline='')))
    result={}
    for backend in ('wasmtime','docker'):
        selected=[r for r in rows if r.get('backend')==backend]
        result[backend]={}
        for key in ('gateway_health_ms','first_valid_ms'):
            try:values=[float(r[key]) for r in selected]
            except (ValueError,KeyError) as e:sys.exit(f'BLOCKED: invalid {backend}/{key} CSV: {e}')
            result[backend][key]=ci(values)
    out=REPORT_BASE
    out.mkdir(parents=True,exist_ok=True)
    doc={'source_csv':str(raw.relative_to(ROOT)) if raw.is_relative_to(ROOT) else str(raw),
         'source_row_count':len(rows),'method':'2000 seeded percentile bootstrap resamples; max relative distance from sample mean; two-sided 95% Student-t',
         'correction':'Prior code incorrectly used upper endpoint rather than upper endpoint minus the mean',
         'scope':'Cold deployment through the common gateway; not warm tenant admission',
         'statistics':result,
         'decision':'PRECISION_ACCEPTED_SCOPED_COLD_ONLY' if all(v['accepted'] for metrics in result.values() for v in metrics.values()) else 'PRECISION_NOT_ACCEPTED_AT_COLLECTED_N'}
    (out/'RESULT_CORRECTED.json').write_text(json.dumps(doc,indent=2)+'\n')
    lines=['# WP3 cold precision reanalysis (no new experiment)','',
           f'Source: `{doc["source_csv"]}`; {len(rows)} raw trials.',
           'Corrected a bootstrap confidence-interval implementation error. Original files remain unchanged.','',
           '| Backend | Metric | N | Student-t half-width % | Bootstrap half-width % | Precision accepted |',
           '|---|---|---:|---:|---:|---|']
    for b,ms in result.items():
        for name,v in ms.items():
            lines.append(f'| {b} | {name} | {v["n"]} | {v.get("student_t_pct",float("nan")):.3f} | {v.get("bootstrap_pct",float("nan")):.3f} | {v["accepted"]} |')
    lines+=['',f'**Decision:** `{doc["decision"]}`.','',
            'The original measured readiness comparison is a scope-limited cold-deployment comparison. It does not establish comparable warm admission, complete memory ownership or WP1 capacity equivalence.','']
    (out/'REPORT_CORRECTED.md').write_text('\n'.join(lines))
    print('\n'.join(lines))
    print('REPORT:',out)
    return 0

if __name__=='__main__':sys.exit(main())
