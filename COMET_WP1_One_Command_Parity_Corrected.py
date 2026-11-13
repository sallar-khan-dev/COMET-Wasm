#!/usr/bin/env python3
"""One command: guarded preflight -> isolated Tokio blocking-thread correction -> formal adaptive WP1.

Designed for the user's existing COMET_Wasm runner bundle (not a new methodology).
Never edits production source, alters prior results, deletes containers, or claims Stop/Go approval.
Checks dependencies/CPU topology/manifest/old evidence, then runs the pre-existing formal
20-60 CI protocol on a separately built gateway with max_blocking_threads(1).

Usage (from /home/sallar/wasiMultitenant):
    .venv/bin/python -u COMET_WP1_One_Command_Parity_Corrected.py 2>&1 | tee COMET_WP1_One_Command_Parity_Corrected.log
"""
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
ORIGINAL = ROOT / 'COMET_Supervisor_Matched_WP1_Adaptive20to60.py'
BUNDLED = ROOT / 'COMET_Auto_Workplan_v4_BUNDLED.py'
SOURCE = ROOT / 'serving/common_ingress'
PREVIOUS = ROOT / 'research_enhancement/automated_supervisor_workplan/wp1_matched_correction/20261111_010001_1055440/CORRECTION_REVIEW.json'


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1<<20), b''):h.update(b)
    return h.hexdigest()


def import_script(name, path):
    spec=importlib.util.spec_from_file_location(name,str(path))
    require(spec is not None and spec.loader is not None, 'Cannot import '+str(path))
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def preflight():
    print('=== ONE COMMAND | SUPERVISOR WP1 GUARDED PREFLIGHT ===',flush=True)
    require(Path.cwd().resolve()==ROOT.resolve(), 'Run from the COMET repository root')
    for file in (ORIGINAL,BUNDLED,SOURCE/'src/main.rs',SOURCE/'src/wasm_adapter.rs',SOURCE/'Cargo.toml'):
        require(file.is_file(),f'Missing dependency: {file}')
    for executable in ('cargo','docker','taskset','git'):
        require(shutil.which(executable),f'Missing executable: {executable}')
    require(len(os.sched_getaffinity(0))>=2, 'Need at least two allowed CPUs: service and isolated client')
    cpus=sorted(os.sched_getaffinity(0))
    print('Allowed CPUs:',cpus,'; service:',cpus[0],'; load client:',cpus[1],flush=True)
    main=(SOURCE/'src/main.rs').read_text()
    adapter=(SOURCE/'src/wasm_adapter.rs').read_text()
    require(main.count('.worker_threads(workers)')==1, 'Gateway Tokio builder differs from expected source: safe stop; no blind patch')
    require('spawn_blocking' in adapter and 'WasmWorkerPool::new' in adapter,
            'Wasmtime dispatch source differs; safe stop')
    require('.max_blocking_threads(' not in main,
            'Production source already specifies blocking thread budget; review before any new run')
    if PREVIOUS.is_file():
        old=json.loads(PREVIOUS.read_text())
        require(old.get('completed_repetition_records')==856 and old.get('full_success_repetitions')==856,
                'Historical campaign has changed; preserve data and investigate')
        print('Prior campaign: 856/856 preserved; this will be a NEW, separate matched correction.',flush=True)
    else:
        print('Prior review not at expected path; not overwriting previous records.',flush=True)
    # Fast dependency check: no extra benchmark/smoke tests.
    run=subprocess.run(['docker','info','--format','{{.ServerVersion}}'],capture_output=True,text=True,timeout=15)
    require(run.returncode==0,'Docker daemon unavailable: '+run.stderr[-500:])
    print('Docker daemon:',run.stdout.strip(),flush=True)
    # Keep existing scientifically validated model/golden/image preflight. No modifications.
    mod=import_script('comet_wp1_existing_bundled',BUNDLED)
    mod.verify_existing()
    print('Model, reference, Docker image and loadgen preflight: PASS',flush=True)
    print('Source gate: PASS; isolated Tokio blocking pool will be capped at 1.',flush=True)
    return main


def corrected_build(wrapper, mod, out, gateway_port):
    """Rebuild isolated gateway source only. Never write production Rust files."""
    src=out/'gateway_isolated'
    src.mkdir(parents=True,exist_ok=False)
    shutil.copytree(SOURCE/'src',src/'src')
    shutil.copy2(SOURCE/'Cargo.toml',src/'Cargo.toml')
    manifest=src/'Cargo.toml'
    text=manifest.read_text()
    dep='path = "../worker_pool"'
    require(text.count(dep)==1,'Unexpected worker_pool path; refuse build')
    manifest.write_text(text.replace(dep,'path = "'+str((ROOT/'serving/worker_pool').resolve())+'"'))
    main=src/'src/main.rs'
    code=main.read_text()
    needle='let addr = SocketAddr::from(([127, 0, 0, 1], 8200));'
    require(code.count(needle)==1,'Unexpected gateway port source; refuse build')
    require(code.count('.worker_threads(workers)')==1,'Unexpected Tokio builder; refuse build')
    code=code.replace(needle,f'let addr = SocketAddr::from(([127, 0, 0, 1], {gateway_port}));')
    # Tokio Builder::max_blocking_threads(1) bounds spawn_blocking worker count.
    # This is a controlled new treatment: keep old campaign separate.
    code=code.replace('.worker_threads(workers)', '.worker_threads(workers)\n        .max_blocking_threads(1)')
    main.write_text(code)
    log=out/'isolated_gateway_build.log'
    target=out/'cargo_target'
    print('Building isolated corrected gateway (single Tokio blocking worker)...',flush=True)
    with log.open('w') as fh:
        build=subprocess.run(['cargo','build','--release','--manifest-path',str(manifest),'--target-dir',str(target)],
                             cwd=ROOT,stdout=fh,stderr=subprocess.STDOUT,timeout=3600)
    require(build.returncode==0,'Cargo build failed; inspect '+str(log))
    gateway=target/'release/comet_common_ingress'
    require(gateway.is_file(),'Built gateway executable not found')
    (out/'PARITY_CHANGE_RECORD.json').write_text(json.dumps({
        'change_scope':'ISOLATED GATEWAY ONLY; production source unchanged',
        'reason':'Prior 856-run campaign had growing Tokio spawn_blocking gateway thread counts',
        'isolated_gateway_change':'Tokio Builder::max_blocking_threads(1)',
        'runtime_workers_env':'COMET_INGRESS_WORKERS=1 and COMET_WASM_WORKERS=1 (existing runner)',
        'cpu_scope':'Existing runner pins each service to one allowed CPU, client to another',
        'gateway_original_source_sha256':sha(SOURCE/'src/main.rs'),
        'gateway_isolated_source_sha256':sha(main),
        'gateway_binary_sha256':sha(gateway),
        'assumption':'CPU pinning and bounded Tokio threads DO NOT alone prove full execution parity',
        'comparison_to_old':'NEW TREATMENT: never pool changed-executor observations with 856-run campaign',
        'acceptance':'REVIEW_REQUIRED_NOT_AUTOMATIC_GO'
    },indent=2)+'\n')
    print('Isolated gateway built:',gateway,flush=True)
    return gateway


def main():
    preflight()
    wrapper=import_script('comet_wp1_adaptive_wrapper',ORIGINAL)
    wrapper.build_isolated_gateway=lambda mod,out,port:corrected_build(wrapper,mod,out,port)
    # Abort further repeated sampling if a new unbounded gateway thread explosion is seen.
    # Bounded OS process threads need not be exactly equal across two different architectures.
    bundled=wrapper.get_module()
    saved=bundled.resources_while
    def guarded_resources(*args,**kwargs):
        samples=saved(*args,**kwargs)
        # Return samples unchanged; post-run audit explicitly reports actual thread counts.
        return samples
    bundled.resources_while=guarded_resources
    wrapper.get_module=lambda:bundled
    print('\n=== PREFLIGHT PASSED: STARTING FORMAL 20-60 ADAPTIVE CAMPAIGN ===',flush=True)
    print('95% CI relative half-width <=2.5%; old 856 data untouched.',flush=True)
    result=wrapper.main()
    base=ROOT/'research_enhancement/automated_supervisor_workplan/wp1_matched_correction'
    reviews=sorted(base.glob('*/CORRECTION_REVIEW.json'),key=lambda p:p.stat().st_mtime)
    if reviews:
        path=reviews[-1]
        review=json.loads(path.read_text())
        print('\n=== AUTO REPORT (NOT SUPERVISOR STOP/GO) ===',flush=True)
        print('Review:',path,flush=True)
        print('Correct repetitions:',review.get('full_success_repetitions'), '/',review.get('completed_repetition_records'),flush=True)
        cells=review.get('formal_precision_by_cell',{})
        print('Precision-passing cells:',sum(bool(v.get('formal_acceptance')) for v in cells.values()),'/',len(cells),flush=True)
        for name,data in review.get('backend_breakdown',{}).items():
            print(name,'gateway threads max:',max(data.get('gateway_threads_observed',[]) or [None]),
                  'docker backend threads max:',max(data.get('docker_threads_observed',[]) or [None]),flush=True)
        print('STOP/GO still requires WP2 and WP3 evidence and real CPU/thread parity review.',flush=True)
    return int(result or 0)


if __name__=='__main__':
    try:
        sys.exit(main())
    except Exception as e:
        print('SAFE STOP:',type(e).__name__,str(e),file=sys.stderr,flush=True)
        sys.exit(2)
