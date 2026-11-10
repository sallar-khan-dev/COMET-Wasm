#!/usr/bin/env python3
"""COMET-Wasm WP1: guarded common-ingress resource parity and headroom checkpoint.

A bounded diagnostic, NOT a supervisor signoff or sustained capacity curve.
Reuses verified RF/SVM pilot traces; no source changes or reference regeneration.
Only starts/stops owned ingress processes and uniquely named Docker containers.
"""
import argparse
import csv
import datetime
import fcntl
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import threading
import time

from COMET_WP1_RF_SVM_Pilot_v2 import (
    ROOT, GEN, ING, PORT, DOCKER_PORT, MODEL_CONFIG,
    Blocked, require, command, request, wait_url, port_free,
    hashfile, procinfo, docker_procinfo, stop_process, validate_summary,
)

PILOT_ROOT = ROOT / 'research_enhancement/wp1_rf_svm_pilot_runs'
RESULT_ROOT = ROOT / 'research_enhancement/wp1_parity_headroom'

def json_write(p, value):
    p.write_text(json.dumps(value, indent=2, default=str) + '\n')

def percentile(values, fract):
    if not values: return None
    s = sorted(values)
    return s[min(len(s)-1, __import__('math').ceil((len(s)-1)*fract))]

def read_sample(pid):
    result=procinfo(pid)
    if not result:
        return {'pid':pid, 'missing':True}
    result['pid']=pid
    try: result['tasks']=len(list((Path('/proc')/str(pid)/'task').iterdir()))
    except OSError:result['tasks']=None
    return result

def docker_pid(name):
    r=command(['docker','inspect','-f','{{.State.Pid}}',name], check=False)
    require(r.returncode==0, f'Cannot inspect owned Docker container {name}')
    return int(r.stdout.strip())

def run_with_samples(argv, log, pids, client_cpu, timeout, env=None):
    results=[]
    stop=threading.Event()
    def sampler():
        while not stop.is_set():
            row={'t_epoch':time.time()}
            for label,pid in pids.items():
                row[label]=read_sample(pid)
            results.append(row)
            stop.wait(.15)
    t=threading.Thread(target=sampler,daemon=True)
    t.start()
    try:
        r=command(['taskset','-c',str(client_cpu)]+[str(x) for x in argv],
                  log=log, env=env, timeout=timeout, check=False)
    finally:
        stop.set();t.join(timeout=3)
    require(r.returncode==0, f'Experiment command exited {r.returncode}; inspect {log}')
    return results

def delays_from_jsonl(path):
    delays=[]
    with path.open() as f:
        for line in f:
            rec=json.loads(line)
            v=rec.get('scheduling_delay_ns')
            if isinstance(v,int): delays.append(v/1e6)
    return {'samples':len(delays),'p50_ms':percentile(delays,.50),
            'p95_ms':percentile(delays,.95),'p99_ms':percentile(delays,.99)}

def run():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--pilot',default='20261110_170246_710579',help='Successful RF/SVM pilot folder')
    ap.add_argument('--service-cpu',type=int,default=None)
    ap.add_argument('--client-cpu',type=int,default=None)
    ap.add_argument('--infer-rps',type=int,default=300)
    ap.add_argument('--noop-rps',type=int,default=1200)
    ap.add_argument('--requests',type=int,default=1500)
    ap.add_argument('--noop-seconds',type=int,default=5)
    args=ap.parse_args()
    require(1 <= args.infer_rps <= 1200,'infer-rps out of guarded range 1..1200')
    require(1 <= args.noop_rps <= 2400,'noop-rps out of guarded range 1..2400')
    require(1000 <= args.requests <= 15000,'requests out of guarded range 1000..15000')
    require(2 <= args.noop_seconds <= 10,'noop-seconds must be 2..10')
    require(args.noop_rps*args.noop_seconds<=15000,'No-op requests exceed guarded cap')
    allowed=sorted(os.sched_getaffinity(0))
    require(len(allowed)>=2,'Need two available logical CPUs to isolate load generator from serving; no safe comparison on one CPU')
    service_cpu=allowed[0] if args.service_cpu is None else args.service_cpu
    client_cpu=allowed[1] if args.client_cpu is None else args.client_cpu
    require(service_cpu in allowed and client_cpu in allowed and service_cpu!=client_cpu,
            f'Choose different available service/client CPUs from {allowed}')
    for tool in ('docker','taskset','git'):
        require(shutil.which(tool),f'Missing {tool}')
    require(GEN.is_file() and os.access(GEN,os.X_OK),'Missing release load generator')
    require(ING.is_file() and os.access(ING,os.X_OK),'Missing release common ingress')
    pilot=PILOT_ROOT/args.pilot
    require(pilot.is_dir(),f'Missing prior pilot folder {pilot}')
    final=json.loads((pilot/'FINAL_GATE.json').read_text())
    require(final.get('status','').startswith('PILOT PASS'),'Source pilot did not pass')
    require(port_free(PORT) and port_free(DOCKER_PORT),
            f'Port {PORT} or {DOCKER_PORT} occupied; will not terminate existing services')
    require(command(['docker','info'],check=False).returncode==0,'Docker daemon unavailable')
    for m in ('rf','svm'):
        require((pilot/f'{m}.trace.json').is_file(),f'Missing validated pilot trace for {m}')
        require((pilot/f'{m}_golden_v2_adapted.json').is_file(),f'Missing adapted golden for {m}')
        require(MODEL_CONFIG[m]['wasm'].is_file(),f'Missing Wasm module for {m}')
        require(hashfile(MODEL_CONFIG[m]['wasm']) == final[f'{m}_wasm_sha256'],
                f'{m} Wasm changed since successful pilot')
        require(command(['docker','image','inspect',final[f'{m}_image']],check=False).returncode==0,
                f'Missing Docker image {final[f"{m}_image"]}')
        image_id=command(['docker','image','inspect','-f','{{.Id}}',final[f'{m}_image']]).stdout.strip()
        require(image_id==final[f'{m}_docker_image_id'],f'{m} Docker image changed since successful pilot')
        golden_path=ROOT/'research_enhancement/v2_references'/MODEL_CONFIG[m]['gold']
        require(hashfile(golden_path)==final[f'{m}_golden_sha256'],f'{m} source golden changed')
        # Validate identity using same official load generator, with no inference dispatch.
        valid=command([GEN,pilot/f'{m}.trace.json',pilot/f'{m}_golden_v2_adapted.json'],check=False,timeout=120)
        require(valid.returncode==0,f'{m} trace/golden provenance failed')
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M%S')+'_'+str(os.getpid())
    out=RESULT_ROOT/stamp
    out.mkdir(parents=True,exist_ok=False)
    manifest={'scope':'WP1 isolated-client resource parity and bounded headroom checkpoint; NOT sustained capacity / WP1 final signoff',
              'source_pilot':str(pilot),'git_head':command(['git','rev-parse','HEAD']).stdout.strip(),
              'service_cpu':service_cpu,'client_cpu':client_cpu,'infer_rps':args.infer_rps,
              'noop_rps':args.noop_rps,'requests':args.requests,'noop_seconds':args.noop_seconds,
              'loadgen_sha256':hashfile(GEN),'ingress_sha256':hashfile(ING),
              'runs':[],'blockers':[],'status':'INCOMPLETE'}
    json_write(out/'manifest.json',manifest)
    print('WP1 PARITY + HEADROOM | OUTPUT:',out,flush=True)
    lockpath=ROOT/'research_enhancement/.comet_wp1_parity_headroom.lock'
    with lockpath.open('w') as lock:
        try: fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise Blocked('Another parity/headroom checkpoint is active')
        ingress=None; loghandle=None; container=None
        try:
            for model in ('rf','svm'):
                conf=MODEL_CONFIG[model]
                for backend in ('wasmtime','docker'):
                    require(port_free(PORT) and port_free(DOCKER_PORT),'Listener occupied; refusing to interrupt')
                    label=f'{model}_{backend}'
                    print('\n===',label,'===',flush=True)
                    if backend=='docker':
                        container=f'comet_wp1_parity_{model}_{stamp}'
                        command(['docker','run','--rm','-d','--name',container,'--network','bridge',
                                 '-p',f'127.0.0.1:{DOCKER_PORT}:8085','--cpuset-cpus',str(service_cpu),
                                 '-e','TOKIO_WORKER_THREADS=1',final[f'{model}_image']],
                                log=out/f'{label}_docker_start.log',timeout=90)
                        code,_=request(f'http://127.0.0.1:{DOCKER_PORT}/infer',{'features':[0.0]*30})
                        require(code==200,'Owned Docker backend failed readiness')
                        bridge=command(['docker','inspect','-f','{{.HostConfig.NetworkMode}}',container]).stdout.strip()
                        require(bridge=='bridge','Docker network is not bridge')
                    route={'backend':backend,'model':model}
                    if backend=='docker':route['url']=f'http://127.0.0.1:{DOCKER_PORT}/infer'
                    routes=out/f'{label}_routes.json'
                    json_write(routes,{str(t):route for t in range(3)})
                    env=os.environ.copy()
                    env.update({'COMET_INGRESS_WORKERS':'1','COMET_WASM_WORKERS':'1',
                                'TOKIO_WORKER_THREADS':'1',
                                f'COMET_{model.upper()}_WASM_PATH':str(conf['wasm'])})
                    loghandle=(out/f'{label}_ingress.log').open('w')
                    ingress=subprocess.Popen(['taskset','-c',str(service_cpu),str(ING),str(routes)],
                                             cwd=ROOT,env=env,stdout=loghandle,stderr=subprocess.STDOUT,
                                             start_new_session=True)
                    require(wait_url(f'http://127.0.0.1:{PORT}/health',ingress,25),
                            f'Ingress not ready for {label}')
                    pids={'ingress':ingress.pid}
                    if container:pids['docker']=docker_pid(container)
                    baseline={k:read_sample(pid) for k,pid in pids.items()}
                    require(all(x.get('Cpus_allowed_list')==str(service_cpu) for x in baseline.values()),
                            f'{label} service affinity differs from CPU {service_cpu}')
                    run={'model':model,'backend':backend,'bridge':backend=='docker',
                         'baseline_resources':baseline,'pids':pids,'measurements':{}}
                    for mode in ('noop','infer'):
                        name=f'{label}_{mode}'
                        prefix=out/name
                        loadenv=os.environ.copy();loadenv['COMET_LOADGEN_WORKERS']='1'
                        if mode=='noop':
                            argv=[GEN,'noop',f'http://127.0.0.1:{PORT}/noop',
                                  str(args.noop_rps),str(args.noop_seconds),'3000','128',str(prefix)]
                            timelimit=60
                        else:
                            argv=[GEN,pilot/f'{model}.trace.json',pilot/f'{model}_golden_v2_adapted.json',
                                  'http',f'http://127.0.0.1:{PORT}/infer',backend,
                                  str(args.infer_rps),'3000','64',str(prefix)]
                            timelimit=max(90,round(args.requests/args.infer_rps)*4+30)
                        print('RUN',name,flush=True)
                        samples=run_with_samples(argv,out/f'{name}.log',pids,client_cpu,timelimit,loadenv)
                        expected=round(args.noop_rps*args.noop_seconds) if mode=='noop' else args.requests
                        result=validate_summary(out/f'{name}.summary.json',expected)
                        json_write(out/f'{name}_resources.json',samples)
                        delay=delays_from_jsonl(out/f'{name}.requests.jsonl')
                        maxima={k:max((int(x[k]['Threads']) for x in samples if k in x and x[k].get('Threads','').isdigit()),default=None) for k in pids}
                        run['measurements'][mode]={'offered':expected,'p50_ms':result.get('p50_latency_ms'),
                          'p95_ms':result.get('p95_latency_ms'),'p99_ms':result.get('p99_latency_ms'),
                          'successful':result.get('successful_requests'),'failed':result.get('failed_requests'),
                          'dropped':result.get('dropped_requests'),'timed_out':result.get('timed_out_requests'),
                          'p99_scheduling_delay_ms':delay['p99_ms'],'observed_max_threads':maxima,
                          'sample_count':len(samples)}
                        print('  PASS p95_ms=',result.get('p95_latency_ms'),'p99_sched_ms=',delay['p99_ms'],
                              'max_threads=',maxima,flush=True)
                    manifest['runs'].append(run)
                    json_write(out/'checkpoint.json',manifest)
                    stop_process(ingress,loghandle);ingress=None;loghandle=None
                    if container:
                        command(['docker','stop','-t','3',container],log=out/f'{label}_stop.log',timeout=20,check=False)
                        container=None
                    time.sleep(.3)
            manifest['status']='DIAGNOSTIC PASS: functional/headroom sampling; WP1 acceptance remains REVIEW'
        except Exception as e:
            manifest['status']='BLOCKED'
            manifest['blockers'].append(f'{type(e).__name__}: {e}')
            print('BLOCKED:',e,flush=True)
        finally:
            stop_process(ingress,loghandle)
            if container:
                command(['docker','stop','-t','3',container],log=out/'cleanup_container.log',timeout=20,check=False)
            json_write(out/'FINAL_GATE.json',manifest)
            with (out/'summary.csv').open('w',newline='') as f:
                writer=csv.writer(f)
                writer.writerow(['model','backend','mode','success','offered','p95_ms','p99_ms','p99_schedule_delay_ms','ingress_threads_max','docker_threads_max'])
                for r in manifest['runs']:
                    for mode,met in r['measurements'].items():
                        writer.writerow([r['model'],r['backend'],mode,met['successful'],met['offered'],met['p95_ms'],met['p99_ms'],met['p99_scheduling_delay_ms'],met['observed_max_threads'].get('ingress'),met['observed_max_threads'].get('docker')])
            print('\nFINAL:',manifest['status'],'\nRESULTS:',out,flush=True)
            if manifest['blockers']:print('BLOCKERS:',manifest['blockers'],flush=True)
    return 0 if manifest['status'].startswith('DIAGNOSTIC PASS') else 2

if __name__=='__main__':
    try:sys.exit(run())
    except Exception as e:
        print('PREFLIGHT BLOCKED:',type(e).__name__,str(e),file=sys.stderr)
        sys.exit(2)
