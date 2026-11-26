#!/usr/bin/env python3
"""Read-only supervisor WP1-WP3 STOP/GO evidence inventory.

Does not run experiments, amend measurements, or infer missing successes.
Use on HPC server at repo root: python3 comet_wp1_wp3_checkpoint.py
"""
import json
from pathlib import Path
from datetime import datetime, timezone

ROOT=Path.cwd()
REPORT_DIR=ROOT/'research_enhancement'/'reports'/'supervisor_wp1_wp3_checkpoint'
RUN=ROOT/'research_enhancement'/'automated_supervisor_workplan'/'20261123_184837_1364620'

def load(path):
    try: return json.loads(path.read_text())
    except (OSError,ValueError): return None

def find_names(*terms):
    base=ROOT/'research_enhancement'
    if not base.is_dir(): return []
    found=[]
    for p in base.rglob('*.json'):
        s=str(p).lower()
        if all(t in s for t in terms): found.append(str(p.relative_to(ROOT)))
    return sorted(found)[:15]

report={'timestamp_utc': datetime.now(timezone.utc).isoformat(),
        'supervisor_gate':'WP1-WP3 STOP/GO', 'wp1':{},'wp2':{},'wp3':{},'decision':'NO_GO',
        'reason':'Do not advance unless every required gate is affirmatively supported by evidence.'}
state=load(RUN/'state.json') or {}
wp=(state.get('WP1') or {})
precision=load(RUN/'adaptive_precision.json') or {}
records=wp.get('runs',[])
conditions={}
for name,item in precision.items():
    if isinstance(item,dict):
        conditions[name]={'n':item.get('n'),'decision':item.get('decision'),
                          'failed_metrics':[metric for metric,result in item.get('metrics',{}).items()
                                            if not result.get('accepted',False)]}
report['wp1']={'run':str(RUN.relative_to(ROOT)), 'state':wp.get('status'),
               'records':len(records), 'conditions':len(conditions),
               'precision_accepted':sum(v['decision']=='PRECISION_ACCEPTED' for v in conditions.values()),
               'precision_not_accepted':sum(v['decision']!='PRECISION_ACCEPTED' for v in conditions.values()),
               'conditions_detail':conditions,
               'noop':[k for k in wp if 'noop_calibration' in k],
               'resource_parity':'NOT CERTIFIED: Wasmtime blocking-thread growth observed; requires supervisor 4.2 acceptance',
               'serving_path':'Common gateway implemented for Wasmtime/Docker; native attribution evidence not independently certified',
               'capacity_losses':'5 run records previously identified with unsuccessful requests (verify raw records)',
               'verdict':'NOT ACCEPTED'}
report['wp2']={'density_matrix':'Previously reported 98/98 conditions across seven models',
               'component_pss_attribution':'UNRESOLVED: app/base/helper decomposition',
               'jit_aot_sensitivity':'Previously reported pilot; final freezing and evidence acceptance not certified',
               'verdict':'NOT ACCEPTED'}
report['wp3']={'cold_deployment':'Previously reported symmetric 60+60 run cold readiness, timing precision accepted',
               'warm_admission':'UNRESOLVED: Wasmtime Store/Instance admission vs pre-created Docker container start',
               'batched_kernel_cost':'NOT CERTIFIED: complete native/Wasm/copy/service decomposition',
               'verdict':'NOT ACCEPTED'}

lines=['COMET-Wasm SUPERVISOR WP1-WP3 STOP/GO CHECKPOINT',
       f"Generated UTC: {report['timestamp_utc']}",
       'Decision: NO_GO (insufficient evidence for supervisor acceptance)', '',
       'WP1 - Fix the serving experiment',
       f"  Collection: {report['wp1']['records']} repetitions, {len(conditions)} conditions",
       f"  Precision: {report['wp1']['precision_accepted']}/{len(conditions)} accepted; {report['wp1']['precision_not_accepted']} unresolved",
       '  Outstanding: resource/thread fairness, complete path attribution, precision limitations and losses.',
       '', 'WP2 - Memory density',
       '  Reported: seven-model density matrix completed (98/98).',
       '  Outstanding: PSS base/model/tenant increment and Docker helper separation acceptance.',
       '', 'WP3 - Compute and admission timing',
       '  Reported: symmetric cold deployment readiness results accepted.',
       '  Outstanding: symmetric warm admission and complete batched timing decomposition acceptance.',
       '', 'SUPERVISOR STOP/GO: NO_GO',
       'No WP4/WP5/WP6 experiments initiated; no prior records altered.',
       'This inventory cannot substitute for missing supervisor-mandated experiments.']
REPORT_DIR.mkdir(parents=True,exist_ok=True)
(REPORT_DIR/'checkpoint.json').write_text(json.dumps(report,indent=2)+'\n')
(REPORT_DIR/'checkpoint.txt').write_text('\n'.join(lines)+'\n')
print('\n'.join(lines))
print('\nSaved:',REPORT_DIR/'checkpoint.txt')
