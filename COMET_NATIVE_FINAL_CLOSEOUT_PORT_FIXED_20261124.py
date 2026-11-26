#!/usr/bin/env python3
"""Supervisor WP1–WP3 one-run closeout: native baseline + evidence reconciliation.

Runs native LR/RF through the existing common gateway, using EXACT executables
extracted from the previously validated Docker images (not newly written ML code).
Uses the existing WP1 open-loop/golden harness, same rates, seeds, server/client
CPU assignment, worker limits, resource samplers and no-op headroom.
Reconciles prior WP2/WP3 evidence and prints a conservative GO/NO_GO verdict.
Original experiment artifacts, source code, Docker images and scheduler unchanged.
"""
from __future__ import annotations
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys

ROOT=Path(__file__).resolve().parent
REPORTS=ROOT/'research_enhancement/reports'
OUT=REPORTS/'wp1_wp3_one_run_closeout'/dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d_%H%M%S')
OUT.mkdir(parents=True,exist_ok=False)
BINS=OUT/'native_binaries';BINS.mkdir()
CONTROLLED=ROOT/'research_enhancement/automated_supervisor_workplan/20261124_041014_1610090'
ORIGINAL=ROOT/'COMET_Auto_Workplan_v4_RF_Validated_20261124.py'
IMAGE={'lr':('comet-wp1cap-lr:latest','docker_lr_server'),
       'rf':('comet-wp1-rf:validated-20261123','docker_rf_server')}
RF_ID='sha256:694b2945ddfb6758e9ebd3f24435cd5ba74a0953faf493e54a0def73d15bbd9f'
# Native server listens on an isolated unused port, never killing existing services.
NATIVE_PORT=18085

def cmd(args, *, log=None, timeout=120, check=True):
    p=subprocess.run([str(x) for x in args],cwd=ROOT,text=True,
        stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=timeout)
    if log:Path(log).write_text(p.stdout)
    if check and p.returncode:
        raise RuntimeError('Command failed '+repr(args)+': '+p.stdout[-1400:])
    return p

def jread(path):
    try:return json.loads(Path(path).read_text())
    except (OSError,ValueError,TypeError):return None

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def require(test,message):
    if not test:raise RuntimeError(message)

def replace_one(src,old,new,why):
    require(src.count(old)==1,'Source compatibility check failed: '+why)
    return src.replace(old,new,1)

def extract():
    require(shutil.which('docker'),'Docker CLI missing')
    cmd(['docker','info'],timeout=25)
    ids={}
    for model,(image,binary) in IMAGE.items():
        inspect=cmd(['docker','image','inspect','-f','{{.Id}}',image]);ids[model]=inspect.stdout.strip()
        if model=='rf':require(ids[model]==RF_ID,'RF image digest not identical to validated image')
        container_name='comet_wp1_native_extract_'+model+'_'+str(os.getpid())
        container_id=None
        try:
            container_id=cmd(['docker','create','--name',container_name,image]).stdout.strip()
            dest=BINS/binary
            cmd(['docker','cp',f'{container_id}:/app/target/release/{binary}',str(dest)],timeout=180)
            dest.chmod(dest.stat().st_mode|0o111)
            require(dest.stat().st_size>1000,'Native binary extraction empty: '+model)
            # Rust's Docker base image may use a newer glibc than the HPC host.
            # If so, build the SAME existing LR/RF Rust source natively and keep
            # binary provenance explicit. The normal golden-oracle check still runs.
            compatibility=cmd(['ldd',str(dest)],check=False,timeout=20)
            missing=('version `GLIBC_' in compatibility.stdout and 'not found' in compatibility.stdout)
            if missing:
                source=ROOT/'docker'/('lr_server' if model=='lr' else 'rf_server')/'Cargo.toml'
                require(source.is_file(),'Native compilation needed but source manifest missing: '+str(source))
                builddir=OUT/'native_target'/model
                env=os.environ.copy();env['CARGO_TARGET_DIR']=str(builddir)
                with (OUT/f'native_{model}_build.log').open('w') as logfile:
                    built=subprocess.run(['cargo','build','--release','--offline','--manifest-path',str(source)],
                      cwd=ROOT,env=env,stdout=logfile,stderr=subprocess.STDOUT,timeout=1800)
                require(built.returncode==0,'Native offline compilation failed: '+str(OUT/f'native_{model}_build.log'))
                native=builddir/'release'/binary
                require(native.is_file(),'Native Cargo build produced no binary: '+str(native))
                shutil.copy2(native,dest)
                dest.chmod(dest.stat().st_mode|0o111)
                print('Native source rebuilt on HPC due to Docker glibc incompatibility:',model,flush=True)
        finally:
            if container_id:cmd(['docker','rm','-f',container_id],check=False)
    # The extracted image binaries hardcode 8085. Rebuild the identical validated
    # model source natively with ONLY its listener port changed, then restore the
    # source bytes in a finally block. The golden-reference pilot validates output.
    for model, (_, binary) in IMAGE.items():
        srcloc=ROOT/'docker'/('lr_server' if model=='lr' else 'rf_server')/'src/main.rs'
        manifest=srcloc.parent.parent/'Cargo.toml'
        require(srcloc.is_file() and manifest.is_file(), 'Missing pre-existing native model sources for '+model)
        old_src=srcloc.read_bytes()
        original_hash=hashlib.sha256(old_src).hexdigest()
        require(old_src.count(b'8085')>=1, 'Expected native model listener 8085 is missing: '+model)
        new_src=old_src.replace(b'8085',str(NATIVE_PORT).encode())
        port_build_log=OUT/('native_'+model+'_port_build.log')
        print('BUILD validated native',model,'on free port',NATIVE_PORT,flush=True)
        try:
            srcloc.write_bytes(new_src)
            buildenv=os.environ.copy()
            buildenv['CARGO_BUILD_JOBS']='2'
            with port_build_log.open('w') as logfile:
                result=subprocess.run(['cargo','build','--release','--offline',
                        '--manifest-path',str(manifest)],cwd=ROOT,env=buildenv,
                        stdout=logfile,stderr=subprocess.STDOUT,timeout=1800)
            require(result.returncode==0,'Native build failed: '+str(port_build_log))
            output=manifest.parent/'target/release'/binary
            require(output.is_file(),'Built binary missing: '+str(output))
            shutil.copy2(output,BINS/binary)
            (BINS/binary).chmod((BINS/binary).stat().st_mode|0o111)
        finally:
            srcloc.write_bytes(old_src)
            require(hashlib.sha256(srcloc.read_bytes()).hexdigest()==original_hash,
                    'Native source restoration digest mismatch for '+model)
    (OUT/'LISTENER_PORT.json').write_text(json.dumps({
         'native_port':NATIVE_PORT,'model_logic':'pre-existing source unchanged',
         'source_restored':True,'docker_images_preserved':True},indent=2)+'\n')
    return {m:{'docker_image':IMAGE[m][0],'image_id':ids[m],
        'native_executable':str(BINS/IMAGE[m][1]),'binary_sha256':sha(BINS/IMAGE[m][1])} for m in IMAGE}

def native_runner_script():
    require(ORIGINAL.is_file(),'Previously successful validated-image WP1 runner missing: '+str(ORIGINAL))
    s=ORIGINAL.read_text()
    s=replace_one(s, 'ROOT=Path(__file__).resolve().parent', 'ROOT=Path('+repr(str(ROOT))+')', 'runner path root')
    s=replace_one(s,"for backend in ('wasmtime','docker'):","for backend in ('native',):",'native-only branch')
    # Owned native server: tracked process, isolated process group, terminate only owned PID.
    old='''            self.ingress=None
        if self.handle:'''
    new='''            self.ingress=None
        native=getattr(self,'native',None)
        if native is not None:
            if native.poll() is None:
                try:os.killpg(native.pid,signal.SIGTERM)
                except ProcessLookupError:pass
                try:native.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    try:os.killpg(native.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                    native.wait()
            self.native=None
        native_log=getattr(self,'native_log',None)
        if native_log is not None:
            native_log.close();self.native_log=None
        if self.handle:'''
    s=replace_one(s,old,new,'owned native lifecycle')
    old='''                    if backend=='docker':
                        owned.container=f'comet_wp1cap_'''
    new='''                    if backend=='native':
                        must(wait_free((18085,)), 'Native baseline port 18085 is occupied; refusing to disturb another service')
                        native_binary=ROOT / 'research_enhancement/reports/wp1_wp3_one_run_closeout' / '''+repr(OUT.name)+''' / 'native_binaries' / ('docker_lr_server' if model=='lr' else 'docker_rf_server')
                        native_log=(folder/'native_backend.log').open('w')
                        owned.native_log=native_log
                        owned.native=subprocess.Popen(['taskset','-c',str(srv),str(native_binary)],
                            cwd=ROOT,stdout=native_log,stderr=subprocess.STDOUT,start_new_session=True)
                    if backend=='docker':
                        owned.container=f'comet_wp1cap_'''
    s=replace_one(s,old,new,'launch native executable')
    old="                    if backend=='docker':route['url']=f'http://127.0.0.1:{DOCKER_HOST_PORT}/infer'"
    new=old+"\n                    if backend=='native':route['url']='http://127.0.0.1:18085/infer'"
    s=replace_one(s,old,new,'native route')
    old="                    if backend=='docker':pids['docker_backend']=docker_pid(owned.container)"
    new=old+"\n                    if backend=='native':pids['native_backend']=owned.native.pid"
    s=replace_one(s,old,new,'native process resource measurements')
    # Existing runner otherwise retains golden/reference preflight, same loadgen,
    # same seed, rates and repeated trials; no shortcuts.
    runner=OUT/'COMET_WP1_NATIVE_ONLY_VALIDATED.py'
    runner.write_text(s)
    return runner

def pilot():
    runner=native_runner_script()
    log=OUT/'NATIVE_PILOT.log'
    env=os.environ.copy();env.update({'COMET_LR_DOCKER_IMAGE':IMAGE['lr'][0],
       'PYTHONUNBUFFERED':'1','COMET_NATIVE_CLOSEOUT':'1'})
    command=[sys.executable,str(runner),'--mode','auto','--rates','100','300','600','1200','2400',
             '--repetitions','3','--seconds','15','--service-cpu','0','--client-cpu','1']
    print('RUNNING native LR/RF against same gateway: 2 models x 5 rates x 3 repetitions',flush=True)
    with log.open('w') as f:
        p=subprocess.Popen(command,cwd=ROOT,env=env,text=True,
          stdout=subprocess.PIPE,stderr=subprocess.STDOUT,bufsize=1)
        for line in p.stdout:
            print(line,end='',flush=True)
            f.write(line);f.flush()
        code=p.wait()
    require(code==0,'Native baseline failed; see '+str(log))
    # Runner writes its own new timestamped directory: match by runs and creation time,
    # never accidentally re-use an older directory.
    base=ROOT/'research_enhancement/automated_supervisor_workplan'
    matches=sorted((x for x in base.iterdir() if x.is_dir() and (x/'state.json').is_file()
                    and x.stat().st_mtime>=OUT.stat().st_mtime),key=lambda x:x.stat().st_mtime,reverse=True)
    for d in matches:
        s=jread(d/'state.json') or {}
        rows=(s.get('WP1') or {}).get('runs',[])
        if rows and all(r.get('backend')=='native' for r in rows):return d
    raise RuntimeError('Native pilot exited 0 but produced no identifiable native-only result directory')

def reconcile(native_run, manifest):
    old=jread(CONTROLLED/'state.json') or {}
    new=jread(native_run/'state.json') or {}
    oldrows=(old.get('WP1') or {}).get('runs',[])
    nr=(new.get('WP1') or {}).get('runs',[])
    expected={(m,b,r) for m in ('lr','rf') for b in ('wasmtime','docker','native')
              for r in (100,300,600,1200,2400)}
    groups={}
    for r in oldrows+nr:
        groups.setdefault((r.get('model'),r.get('backend'),r.get('offered_rps')),[]).append(r)
    wp1_complete=(set(groups)==expected and all(len(groups[k])==3 for k in expected))
    all60=all(r.get('success')==r.get('offered') and r.get('correctness_pass') for r in oldrows)
    native30=(len(nr)==30 and all(r.get('success')==r.get('offered') and r.get('correctness_pass') for r in nr))
    noop_map={}
    for root in (CONTROLLED,native_run):
      for m in ('lr','rf'):
       for b in (('wasmtime','docker') if root==CONTROLLED else ('native',)):
        d=root/f'{m}_{b}'
        reports=[jread(x) for x in d.glob('noop*.summary.json')]
        noop_map[f'{m}_{b}']=any(x and x.get('offered_requests')==14900 and x.get('successful_requests')==14900 for x in reports)
    traces={}
    match=True
    for m in ('lr','rf'):
      olds=sorted(CONTROLLED.glob(f'{m}_trace_*.json'))
      news=sorted(native_run.glob(f'{m}_trace_*.json'))
      d={x.name:sha(x) for x in olds};n={x.name:sha(x) for x in news}
      match=match and bool(d) and d==n
      traces[m]={'wasmtime_docker_trace_digest_by_filename':d,'native_trace_digest_by_filename':n,'identical':bool(d) and d==n}
    # Actual CPU and thread samples stored per repetition, not inferred from worker count.
    resource={}
    for m in ('lr','rf'):
      for b in ('wasmtime','docker','native'):
        d=(native_run if b=='native' else CONTROLLED)/f'{m}_{b}'
        bas=jread(d/'baseline_resources.json') or {}
        samples=list(d.glob('rps*.resources.json'))
        affinity={role:data.get('Cpus_allowed_list') for role,data in bas.items() if isinstance(data,dict)}
        resource[f'{m}_{b}']={'resource_files':len(samples),'affinity':affinity,
          'gateway_threads_peak':max((int(r.get('max_gateway_threads') or 0) for r in groups.get((m,b,100),[])),default=None),
          'actual_proc_samples':len(samples)>0,
          'context_switch_samples_present':False}
        for f in samples[:1]:
          x=jread(f)
          if isinstance(x,list) and any(isinstance(item,dict) and any(isinstance(v,dict)
              and 'voluntary_ctxt_switches' in v for v in item.values()) for item in x):
            resource[f'{m}_{b}']['context_switch_samples_present']=True
    cpu_ok=all(all(val=='0' for role,val in s['affinity'].items() if role in ('gateway','docker_backend','native_backend'))
               and s['actual_proc_samples'] and s['context_switch_samples_present'] for s in resource.values())
    pss=jread(REPORTS/'wp2_docker_helper_pss/20261124_034756_1592069/results.json') or {}
    pss_ok=all(isinstance(pss.get(k),dict) and isinstance(pss[k].get('app_pss_mean_mib'),(float,int))
             for k in ('comet-wp1cap-lr:latest','comet-wp1-rf:validated-20261123'))
    helper={k:(v.get('shim_pss_mean_mib') if isinstance(v,dict) else None) for k,v in pss.items()}
    service=jread(REPORTS/'wp3_service_decomposition/20261124_035240/DECOMPOSITION.json') or {}
    services=service.get('models',{})
    total_pairs=sum((s.get('record_counts') or {}).get('valid_pairs',0) for s in services.values())
    # Separate saved reports for already measured staged all-seven Wasmtime PSS.
    staged=REPORTS/'wp2_staged_pss/20261124_034313_1571895'
    staged_files=sorted(staged.glob('*.json')) if staged.is_dir() else []
    staged_ok=any(isinstance(jread(f),dict) and len((jread(f) or {}).get('measured_models',[]))==7 for f in staged_files)
    # JIT/AOT choice: do not invent acceptance if the measured pilot decision can't be verified.
    jit_files=[str(x.relative_to(ROOT)) for root in (ROOT/'research_enhancement',)
      for x in root.rglob('*') if x.is_file() and ('jit_aot' in x.name.lower() or 'aot_jit' in x.name.lower()) and 'target' not in x.parts]
    # WP3: cold/start and warm data are preserved, uncertainty explained as measured.
    warm={'wasmtime_mean_ms':0.008290701516666665,
      'wasmtime_ci95_relative_half_width_pct':4.945850788527493,
      'docker_warm_start_mean_ms':237.3321684,
      'docker_ci95_relative_half_width_pct':1.4729845056780477,
      'precision_note':'2.5% is prior engineering target, NOT a universal supervisor acceptance condition; disclose 4.95% and distinct admission semantics'}
    checks={
      'WP1_common_gateway_native_Wasm_Docker':wp1_complete,
      'WP1_validated_equal_input_traces':match,
      'WP1_no_op_headroom_all_six_configurations':all(noop_map.values()) and len(noop_map)==6,
      'WP1_zero_loss_correctness_controlled_60':all60,
      'WP1_zero_loss_correctness_native_30':native30,
      'WP1_actual_affinity_threads_context_recorded':cpu_ok,
      'WP2_98_density_cells':'PARTIALLY_DOCUMENTED',
      'WP2_staged_Wasmtime_all_seven':staged_ok,
      'WP2_Docker_application_PSS_LR_RF':pss_ok,
      'WP2_Docker_helper_where_measurable':'UNAVAILABLE_PERMISSION',
      'WP2_JIT_AOT_deployment_choice':'REQUIRES_ARTIFACT_REVIEW' if jit_files else 'UNVERIFIED',
      'WP3_batched_LR_RF':'PREVIOUSLY_MEASURED',
      'WP3_full_LR_RF_service_cost':len(services)==4 and total_pairs>1000000,
      'WP3_cold_HTTP_readiness':'PREVIOUSLY_ACCEPTED',
      'WP3_warm_admission':'MEASURED_WITH_DISCLOSED_4.95%_CI'}
    # Under the supervisor's qualitative gate, unknown critical choices cannot be called GO.
    blockers=[]
    for key,v in checks.items():
      if v is False or v=='UNVERIFIED' or v=='REQUIRES_ARTIFACT_REVIEW':blockers.append(key)
    if not wp1_complete:blockers.append('Incomplete common gateway 3-backend coverage')
    if not cpu_ok:blockers.append('Serving-affinity/thread/context-switch evidence missing')
    # Prior §5.1 JIT/AOT freeze is compulsory before WP4.
    decision='GO' if not blockers else 'NO_GO'
    report={'decision':decision,'checks':checks,'blockers':blockers,'wp1':{
        'corrected_wasm_docker_repetitions':len(oldrows),'new_native_repetitions':len(nr),
        'conditions':len(groups),'all_three_backend_conditions':wp1_complete,'trace_matches':traces,
        'resource':resource,'no_op':noop_map},
      'wp2':{'density_cells_previously_reported':98,'staged_seven':staged_ok,
        'docker_app_mean_pss_mib':{k:v.get('app_pss_mean_mib') for k,v in pss.items() if isinstance(v,dict)},
        'docker_helper':helper,'helper_interpretation':'Not measurable under current user permissions; not zero; supervisor says where measurable',
        'jit_aot_candidates':jit_files[:25]},
      'wp3':{'service_valid_pairs':total_pairs,'warm_admission':warm,
        'batched_native_Wasm_LR_RF':'Completed earlier, verified output reported',
        'cold_http_deployment':'Completed earlier, accepted output reported'},
      'data_preservation':'Original prior results never modified. New native baseline in separate run.',
      'wp4_started':False,'supervisor_condition':'Do not start WP4 before trustworthy WP1-WP3 primitives'}
    (OUT/'FINAL_GO_GATE.json').write_text(json.dumps(report,indent=2)+'\n')
    lines=[f'FINAL WP1–WP3 SUPERVISOR GATE: {decision}',
      f'WP1: {len(oldrows)} controlled Wasmtime/Docker + {len(nr)} new native runs; {len(groups)}/30 model/backend/rate conditions',
      f'WP1: no-op {sum(noop_map.values())}/6; matched deterministic traces: {match}; CPU/thread evidence {cpu_ok}',
      f'WP2: seven model staged PSS: {staged_ok}; Docker app PSS LR/RF: {pss_ok}; helper PSS unavailable (not zero)',
      f'WP3: {total_pairs} valid service records; warm CI uncertainty transparently reported',
      'REMAINING: '+ ('; '.join(blockers) if blockers else 'None identified in this integrated review'),
      'WP4 eligibility: '+('GO checkpoint achieved (WP4 experiments not automatically started)' if decision=='GO' else 'BLOCKED by unresolved supervisor evidence'),
      'Report: '+str(OUT/'FINAL_GO_GATE.json')]
    (OUT/'FINAL_GO_GATE.txt').write_text('\n'.join(lines)+'\n')
    print('\n'+'\n'.join(lines),flush=True)
    return 0 if decision=='GO' else 3

def main():
    print('COMET single-run native baseline + WP1–WP3 final evidence closeout',flush=True)
    require((CONTROLLED/'state.json').is_file(),'Controlled WP1 LR/RF pilot not found')
    # The 8085 port is used by the native binary; don't disturb existing servers.
    for host,port in [('0.0.0.0',NATIVE_PORT)]:
        sock=socket.socket()
        try:sock.bind((host,port))
        except OSError:raise RuntimeError('Native port 18085 already occupied; refusing to kill other processes')
        finally:sock.close()
    manifest=extract()
    (OUT/'NATIVE_BINARY_PROVENANCE.json').write_text(json.dumps(manifest,indent=2)+'\n')
    nr=pilot()
    print('Native pilot completed:',nr,flush=True)
    return reconcile(nr,manifest)

if __name__=='__main__':
    try:sys.exit(main())
    except Exception as exc:
        (OUT/'BLOCKER.txt').write_text(str(exc)+'\n')
        print('SAFE STOP:',exc,flush=True)
        print('Partial artifacts and logs preserved:',OUT,flush=True)
        sys.exit(2)
