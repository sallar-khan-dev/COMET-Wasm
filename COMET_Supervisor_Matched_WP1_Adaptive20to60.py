#!/usr/bin/env python3
"""COMET supervisor WP1 §§4.1-4.5 full matched serving campaign.

Reuses the actual COMET_Auto_Workplan_v4 implementation bundled with this file,
installs an isolated copy of the common gateway with configurable localhost port,
then runs the existing full no-op, gold-oracle, open-loop, process-sampling campaign
for LR + RF, Wasmtime + Docker, all 5 rates, adaptive 20–60 repetitions (95% CI <=2.5%), same inflight.
No new scheduling methods, workloads, benchmarking metrics, or service implementations.

The script is a controlled experiment: a completed campaign does NOT itself
constitute WP1-WP3 supervisor stop/go approval.
"""
import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import traceback

ROOT = Path(__file__).resolve().parent
BUNDLED = ROOT / 'COMET_Auto_Workplan_v4_BUNDLED.py'
SRC = ROOT / 'serving/common_ingress'
RESULT_ROOT = ROOT / 'research_enhancement/automated_supervisor_workplan/wp1_matched_correction'

class CampaignError(Exception):
    pass

def get_module():
    if not BUNDLED.is_file():
        raise CampaignError(f'Bundled, previously used WP1 runner missing: {BUNDLED}')
    spec = importlib.util.spec_from_file_location('comet_wp1_supervisor_existing', BUNDLED)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()

def pick_ports():
    # Choose ports that are not actively listening. The runner's original
    # listener check fails safely if another process claims one later.
    sockets = []
    try:
        for _ in range(2):
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind(('127.0.0.1', 0))
            sockets.append(s)
        ports = [s.getsockname()[1] for s in sockets]
    finally:
        for s in sockets:
            s.close()
    return ports

def build_isolated_gateway(mod, out, gateway_port):
    if not (SRC / 'src/main.rs').is_file():
        raise CampaignError('Missing existing COMET common-ingress source')
    src = out / 'gateway_isolated'
    src.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SRC / 'src', src / 'src')
    shutil.copy2(SRC / 'Cargo.toml', src / 'Cargo.toml')
    manifest = (src / 'Cargo.toml')
    txt = manifest.read_text()
    dep = 'path = "../worker_pool"'
    if txt.count(dep) != 1:
        raise CampaignError('Unexpected worker_pool dependency; no source rewrite performed')
    manifest.write_text(txt.replace(dep, 'path = "' + str((ROOT/'serving/worker_pool').resolve()) + '"'))
    entry = src / 'src/main.rs'
    code = entry.read_text()
    old = 'let addr = SocketAddr::from(([127, 0, 0, 1], 8200));'
    if code.count(old) != 1:
        raise CampaignError('Unexpected common ingress port source; no source rewrite performed')
    entry.write_text(code.replace(old,
        f'let addr = SocketAddr::from(([127, 0, 0, 1], {gateway_port}));'))
    target = out / 'cargo_target'
    buildlog = out / 'isolated_gateway_build.log'
    with buildlog.open('w') as f:
        cmd = ['cargo', 'build', '--release', '--manifest-path', str(manifest), '--target-dir', str(target)]
        print('BUILD isolated gateway from actual repository source',flush=True)
        rc = subprocess.run(cmd, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT, timeout=3600).returncode
    if rc:
        raise CampaignError(f'Gateway cargo build failed, inspect {buildlog}')
    gateway = target / 'release/comet_common_ingress'
    if not gateway.is_file():
        raise CampaignError('Isolated gateway executable missing after successful Cargo build')
    return gateway

def manifest_for(out, gateway, ports, mod):
    d = {
        'supervisor_sections': ['4.1','4.2','4.3','4.4','4.5'],
        'purpose': 'matched full-scale LR/RF Wasmtime/Docker common-ingress correction',
        'models': ['lr','rf'], 'backends': ['wasmtime','docker'],
        'rates_rps': [100,300,600,1200,2400],
        'minimum_independent_repetitions_per_cell': 20,
        'maximum_independent_repetitions_per_cell': 60,
        'confidence_level': 0.95,
        'target_relative_ci_half_width': 0.025,
        'stopping_rule': 'Both Student-t and run-bootstrap 95% CIs on P50/P95/P99/goodput <= 2.5%, and no incorrect/lost runs; otherwise max 60, report unaccepted',
        'offered_seconds_per_trial': 15,
        'max_inflight': 512,
        'loadgen_workers': 1,
        'service_cpu_and_client_cpu': 'chosen by original runner as first two CPUs in available affinity',
        'original_gateway_source_sha256': sha(SRC/'src/main.rs'),
        'isolated_gateway_binary_sha256': sha(gateway),
        'existing_automation_sha256': sha(BUNDLED),
        'original_production_sources_untouched': True,
        'ports': {'gateway':ports[0],'docker_published_loopback':ports[1]},
        'docker_network': 'bridge',
        'native_attribution': 'Already collected separately: 100 runs, not pooled with this adaptive matched campaign',
        'interpretation': 'Matched correction runs require real statistical review; not automatic WP1-WP3 GO.'
    }
    (out/'CORRECTION_MANIFEST.json').write_text(json.dumps(d,indent=2)+'\n')

def do_review(run_dir):
    state = run_dir / 'state.json'
    if not state.is_file():
        return
    x = json.loads(state.read_text())
    rows = x.get('WP1',{}).get('runs',[])
    minimum = 2*2*5*20
    maximum = 2*2*5*60
    noop = {}
    for model in ('lr','rf'):
        for backend in ('wasmtime','docker'):
            key=f'{model}_{backend}'
            rr=[r for r in rows if r.get('model')==model and r.get('backend')==backend]
            noops=x['WP1'].get(f'{key}_noop_calibration', [])
            noop[key] = {
                'repetitions_present':len(rr),
                'full_success_repetitions':sum(1 for r in rr if r.get('correctness_pass') is True),
                'incomplete_repetitions':sum(1 for r in rr if r.get('correctness_pass') is not True),
                'measured_noop_rates':[a.get('rps') for a in noops],
                'zero_error_noop_rates':[a.get('rps') for a in noops if a.get('passed_zero_errors')],
                'gateway_threads_observed':[r.get('max_gateway_threads') for r in rr if r.get('max_gateway_threads') is not None],
                'docker_threads_observed':[r.get('max_docker_threads') for r in rr if r.get('max_docker_threads') is not None]
            }
    result = {
        'supervisor_gate': 'REVIEW_REQUIRED_NOT_AUTOMATIC_GO',
        'campaign_status':x.get('WP1',{}).get('status'),
        'minimum_repetitions':minimum,'maximum_repetitions':maximum,
        'completed_repetition_records':len(rows),
        'full_success_repetitions':sum(r.get('correctness_pass') is True for r in rows),
        'backend_breakdown':noop,
        'formal_precision_by_cell':x.get('WP1',{}).get('formal_precision',{}),
        'remaining_supervisor_gate':[
            'WP1 common-ingress path parity, no-op load generator/gateway headroom, observed thread and CPU parity',
            'WP2 application vs Docker-helper PSS where measurable; current visibility is partial',
            'WP3 guest-call, input-copy, and complete-service timing boundaries without double-counting',
            'WP3 real service cold start and warm admission scope comparability'
        ]
    }
    (run_dir/'CORRECTION_REVIEW.json').write_text(json.dumps(result,indent=2)+'\n')
    lines=['# Supervisor WP1 matched full-scale serving correction','',
        f"- Runner status: **{result['campaign_status']}**",
        f"- Repetitions collected: **{len(rows)}** (adaptive range {minimum}–{maximum})",
        f"- Completely successful repetitions: **{result['full_success_repetitions']} / {len(rows)}**",'',
        '| Model/backend | Repetitions | Full-success | Successful no-op rates (RPS) |',
        '|---|---:|---:|---|']
    for key,v in noop.items():
        lines.append(f"| {key} | {v['repetitions_present']} | {v['full_success_repetitions']} | {', '.join(map(str,v['zero_error_noop_rates'])) or 'none'} |")
    lines += ['', '## Formal independent-run statistical precision',
        '| Model/backend/rate | Runs | 95% CI precision | Correctness | Stopping |',
        '|---|---:|---|---|---|']
    for cell, v in sorted(result['formal_precision_by_cell'].items()):
        lines.append(f"| {cell} | {v.get('n')} | {v.get('all_metrics_precision_met')} | {v.get('all_runs_correct')} | {v.get('stopping_reason')} |")
    lines += ['', '## Scientific limitation',
        'Data collection and file completeness do not establish supervisor acceptance.',
        'Actual thread and CPU observations and complete request series must be evaluated before GO.',
        'Native historical 100-run campaign is preserved separately and is not pooled as a matched campaign.',
        'Docker bridge mode is inspected, but OS-level thread parity must still be reviewed, because the existing Docker LR server uses #[tokio::main] and may not honor TOKIO_WORKER_THREADS.',
        'Precision CI evaluates independent full-run summaries, not independent HTTP requests; failure or load loss prevents a full precision acceptance.',
        '', '## Remaining prescribed evidence']
    lines += ['- '+i for i in result['remaining_supervisor_gate']]
    (run_dir/'CORRECTION_REVIEW.md').write_text('\n'.join(lines)+'\n')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--resume-latest',action='store_true',help='Resume newest run in the dedicated matched-correction directory, preserving already generated measurements')
    args=p.parse_args()
    if not (ROOT/'serving/common_ingress/Cargo.toml').is_file():
        raise CampaignError('Place this script in /home/sallar/wasiMultitenant and run it from there')
    mod=get_module()
    RESULT_ROOT.mkdir(parents=True,exist_ok=True)
    if args.resume_latest:
        dirs=sorted([q for q in RESULT_ROOT.glob('*/CORRECTION_MANIFEST.json')])
        if not dirs:
            raise CampaignError('No matching previous run to resume')
        out=dirs[-1].parent
        previous=json.loads((out/'CORRECTION_MANIFEST.json').read_text())
        port_pair=[previous['ports']['gateway'],previous['ports']['docker_published_loopback']]
        gateway=Path(previous['isolated_gateway_binary_path'])
        if not gateway.is_file() or sha(gateway)!=previous['isolated_gateway_binary_sha256']:
            raise CampaignError('Resume isolated gateway binary missing or changed')
        print('RESUME existing full campaign:',out,flush=True)
    else:
        out=RESULT_ROOT/(dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d_%H%M%S')+'_'+str(os.getpid()))
        out.mkdir(parents=True,exist_ok=False)
        port_pair=pick_ports()
        gateway=build_isolated_gateway(mod,out,port_pair[0])
        manifest_for(out,gateway,port_pair,mod)
    mod.OUTROOT=RESULT_ROOT
    mod.GATEWAY_PORT=port_pair[0]
    mod.DOCKER_HOST_PORT=port_pair[1]
    mod.ING=gateway
    # The existing trial implementation is identical to the completed WP1 v4
    # except for the isolated gateway executable/ports and the full 20 repeats.
    values=argparse.Namespace(
        mode='auto',rates=[100,300,600,1200,2400],seconds=15,repetitions=60,
        noop_multiplier=2,max_inflight=512,service_cpu=None,client_cpu=None,
        resume=out if args.resume_latest else None,resume_latest=False
    )
    print('SUPERVISOR WP1 FORMAL CAMPAIGN: LR/RF x WASMTIME/DOCKER x 5 RPS x ADAPTIVE 20-60 REPS; 95% CI <=2.5%',flush=True)
    print('OUTPUT:',out,flush=True)
    print('COMMON GATEWAY PORT:',port_pair[0],'DOCKER BRIDGE-PUBLISHED PORT:',port_pair[1],flush=True)
    print('NO EXISTING SOURCE OR PRIOR EXPERIMENT WILL BE OVERWRITTEN',flush=True)
    print('CI FORMAL METRICS: independent-run P50, P95, P99, measured goodput; Student-t AND run bootstrap',flush=True)
    result_code=2
    try:
        result_code=mod.run_auto(values)
    finally:
        # Original runner creates its own timestamped result directory in OUTROOT
        # and stores all the raw repeated traces there. Locate by current run only.
        candidates=sorted([q.parent for q in RESULT_ROOT.glob('*/state.json')],key=lambda q:q.stat().st_mtime)
        if candidates:
            target=candidates[-1]
            # Bind the previously created isolated gateway build to the exact
            # actual campaign output so that --resume-latest can find it.
            if not args.resume_latest and (target/'state.json').is_file():
                preparation=json.loads((out/'CORRECTION_MANIFEST.json').read_text())
                preparation['isolated_gateway_binary_path']=str(gateway)
                (target/'CORRECTION_MANIFEST.json').write_text(json.dumps(preparation,indent=2)+'\n')
            do_review(target)
            print('CONSOLIDATED:',target/'CORRECTION_REVIEW.md',flush=True)
            print('RAW STATE:',target/'state.json',flush=True)
    return result_code

if __name__=='__main__':
    try:
        sys.exit(main())
    except Exception as e:
        print('SAFE STOP:',type(e).__name__,str(e),file=sys.stderr)
        traceback.print_exc()
        sys.exit(2)
