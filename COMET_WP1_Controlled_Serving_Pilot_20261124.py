#!/usr/bin/env python3
"""WP1 §§4.2-4.5: cap Tokio blocking workers and run a NEW, isolated LR/RF pilot.
Writes source backup and new executable, never modifies prior experimental records.
Uses the existing supervisor-workplan v4 harness, identical shared gateway and
varied deterministic golden traces. Not an automatic WP1/WP3 GO decision.
"""
import os,sys,hashlib,subprocess,shutil,json,datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parent
SRC=ROOT/'serving/common_ingress/src/main.rs'
BIN=ROOT/'serving/common_ingress/target/release/comet_common_ingress'
RUNNER=ROOT/'COMET_Auto_Workplan_v4.py'
OUT=ROOT/'research_enhancement/reports/wp1_controlled_serving_pilot'/datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d_%H%M%S")
OUT.mkdir(parents=True,exist_ok=False)
def hashbytes(b):return hashlib.sha256(b).hexdigest()
def command(argv,log):
    print('EXEC:', ' '.join(map(str,argv)),flush=True)
    with log.open('w') as f:
        p=subprocess.run([str(x) for x in argv],cwd=ROOT,stdout=f,stderr=subprocess.STDOUT,check=False)
    if p.returncode:raise RuntimeError(f"Command exited {p.returncode}; {log}")
def fail(msg):
    print('SAFE STOP:',msg,flush=True)
    print('REPORT DIRECTORY:',OUT,flush=True)
    sys.exit(2)
if not SRC.is_file():fail(f"Missing existing gateway source {SRC}")
if not RUNNER.is_file():fail(f"Missing existing supervisor harness {RUNNER}; cannot invent alternate experimental protocol")
if not BIN.is_file():fail(f"Existing ingress binary unavailable: {BIN}")
old=SRC.read_text()
needle='.worker_threads(workers)\n        .enable_all()'
if needle not in old:
    # permit spacing different, but never double-inject or overwrite unexpected source
    if '.max_blocking_threads(1)' in old:
        print('Blocking cap already present',flush=True)
        patched=old
    else:fail("Cannot find exact Tokio builder location, no source changes made")
else:
    patched=old.replace(needle,'.worker_threads(workers)\n        .max_blocking_threads(1)\n        .enable_all()',1)
# Pin binary identity and the specific source change for reproducibility
meta={'source_file':str(SRC),'source_sha256_before':hashbytes(old.encode()),
      'target_sha256':hashbytes(patched.encode()),'old_ingress_binary_sha256':hashbytes(BIN.read_bytes()),
      'effective_tokio_worker_threads':1,'max_tokio_blocking_threads':1,
      'effective_wasm_inference_workers':1,
      'NOTE':'Single CPU lane and bounded Tokio blocking pool. Thread count != active inference capacity. Validate from Linux samples.'}
(OUT/'CONFIG.json').write_text(json.dumps(meta,indent=2)+'\n')
# Keep independent copy in report directory, plus in-repo .bak for reproducibility.
backup=SRC.with_name('main.rs.before_wp1_controlled_20261124')
if backup.exists() and backup.read_text()!=old and old!=patched:
    fail('Prior backup conflicts with current source; refusing to overwrite it')
if not backup.exists():backup.write_text(old)
if old!=patched:SRC.write_text(patched)
print('Gateway code now caps Tokio blocking threads to one; original preserved:',backup,flush=True)
# Safety: compile offline as the existing project does; keep patched source aligned with binary
try:
    manifest=ROOT/'serving/common_ingress/Cargo.toml'
    if not manifest.is_file():fail('Expected gateway Cargo.toml absent')
    command(['cargo','build','--release','--offline','--manifest-path',manifest],OUT/'gateway_build.log')
    if not BIN.is_file():fail('No built gateway executable')
    meta['new_ingress_binary_sha256']=hashbytes(BIN.read_bytes())
    (OUT/'CONFIG.json').write_text(json.dumps(meta,indent=2)+'\n')
except Exception as e:
    if old!=patched:SRC.write_text(old)
    fail(f"{e}; original gateway source restored; old binary may be untouched")
print('Gateway build complete; launching ONE supervisor LR/RF controlled run',flush=True)
print('Rates=100,300,600,1200,2400; 3 repeats per condition; 15 s each',flush=True)
print('This is a new run; original 1027 repetitions remain unmodified',flush=True)
# Current harness explicitly launches Wasmtime (COMET_WASM_WORKERS=1), Docker on
# CPU0, loadgen CPU1; its headroom gate and deterministic traces remain enabled.
env=os.environ.copy()
env['COMET_LR_DOCKER_IMAGE']='comet-wp1cap-lr:latest'
env['PYTHONUNBUFFERED']='1'
runargs=[sys.executable,str(RUNNER),'--mode','auto','--rates','100','300','600','1200','2400',
         '--repetitions','3','--seconds','15','--service-cpu','0','--client-cpu','1']
with (OUT/'pilot.log').open('w') as log:
    proc=subprocess.Popen(runargs,cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
    for line in proc.stdout:
        print(line,end='',flush=True)
        log.write(line)
    rc=proc.wait()
if rc:
    fail(f"Controlled pilot harness exited {rc}. See {OUT/'pilot.log'}. Do not infer fairness or GO.")
print('WP1 CONTROLLED PILOT FINISHED; evidence in',OUT/'pilot.log',flush=True)
print('No WP4 launched; evaluate pilot resource parity, loss and capacity with supervisor criteria.')
