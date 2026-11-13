#!/usr/bin/env python3
"""Supervisor WP1 §4 / WP3 §6.1: real native-through-common-ingress LR
attribution and decomposition of existing native/Wasmtime/Docker trace records.

Runs ONLY the missing native-process baseline under the existing common gateway;
never overwrites or repeats prior Wasmtime/Docker/density/cold-start campaigns.
No fabricated stop/go pass. No scheduler or model changes.
"""
import csv, datetime, hashlib, json, math, os, pathlib, shutil, signal, socket, statistics, subprocess, sys, time, traceback, urllib.request

ROOT=pathlib.Path(__file__).resolve().parent
AUT=ROOT/'research_enhancement/automated_supervisor_workplan'
RATES=(100,300,600,1200,2400)
REPS=20
SECONDS=15
CPU_SERVICE=None
CPU_CLIENT=None
LOADGEN=ROOT/'research_enhancement/v2_loadgen/target/release/comet_v2_loadgen'
GATEWAY=ROOT/'serving/common_ingress/target/release/comet_common_ingress'
GOLDEN=ROOT/'research_enhancement/v2_references/lr_iris_golden_v1.json'
TRACEGEN=ROOT/'research_enhancement/v2_workloads/generate_trace.py'
NATIVE_MANIFEST=ROOT/'docker/lr_server/Cargo.toml'
NATIVE_BINARY=ROOT/'docker/lr_server/target/release/docker_lr_server'
GATEWAY_PORT=8200
NATIVE_PORT=8085

class Abort(Exception):pass

def call(args,*,log=None,timeout=900,env=None):
    argv=[str(x) for x in args]
    if log is None:
        r=subprocess.run(argv,cwd=ROOT,env=env,capture_output=True,text=True,timeout=timeout)
    else:
        with open(log,'w') as f:r=subprocess.run(argv,cwd=ROOT,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=timeout)
    if r.returncode:raise Abort(f'Exit {r.returncode}: {argv!r}, log={log}, {getattr(r,"stdout","")[-700:]}')
    return r

def jsonread(p):return json.loads(pathlib.Path(p).read_text())

def sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for part in iter(lambda:f.read(1024*1024),b''):h.update(part)
    return h.hexdigest()

def free_port(port):
    with socket.socket() as sock:
        try:sock.bind(('127.0.0.1',port));return True
        except OSError:return False

def percent(values,p):
    if not values:return None
    a=sorted(values);return a[math.ceil((len(a)-1)*p)]

def procstatus(pid):
    result={'pid':pid}
    try:
        for s in (pathlib.Path('/proc')/str(pid)/'status').read_text().splitlines():
            if s.startswith(('Threads:','Cpus_allowed_list:','voluntary_ctxt_switches:','nonvoluntary_ctxt_switches:')):
                k,v=s.split(':',1);result[k]=v.strip()
    except OSError:result['unreadable']=True
    return result

def terminate(process):
    if process is not None and process.poll() is None:
        try:os.killpg(process.pid,signal.SIGTERM)
        except ProcessLookupError:pass
        try:process.wait(timeout=7)
        except subprocess.TimeoutExpired:
            try:os.killpg(process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
            process.wait(timeout=5)

def poll_probe(golden,expected='native',timeout=35):
    item=golden['records'][0]
    payload=json.dumps({'request_id':'native-probe','tenant_id':0,'model':'lr','features':item['features']}).encode()
    deadline=time.monotonic()+timeout
    last=''
    while time.monotonic()<deadline:
        try:
            req=urllib.request.Request(f'http://127.0.0.1:{GATEWAY_PORT}/infer',data=payload,headers={'Content-Type':'application/json'},method='POST')
            with urllib.request.urlopen(req,timeout=1) as resp:data=json.load(resp)
            if data.get('prediction')==item['expected_prediction'] and data.get('backend')==expected:return data
            raise Abort(f'Inference mismatch: {data}')
        except Abort:raise
        except Exception as e:last=str(e);time.sleep(.2)
    raise Abort('Native common gateway probe failed: '+last)

def latest_past():
    candidates=[]
    for p in AUT.glob('20*/wp1_capacity_summary.csv'):
        if (p.parent/'state.json').is_file():candidates.append(p)
    if not candidates:raise Abort('Cannot find completed WP1 capacity data; source comparison is not possible')
    return max(candidates,key=lambda p:p.stat().st_mtime)

def trace_path(existing,rate,out):
    candidate=existing.parent/f'lr_trace_{rate*SECONDS}.json'
    if candidate.is_file():
        d=jsonread(candidate)
        if d.get('request_count')==rate*SECONDS and d.get('model')=='lr' and d.get('golden_artifact_sha256')==sha(GOLDEN):return candidate
    dest=out/f'lr_trace_{rate*SECONDS}.json'
    call([sys.executable,TRACEGEN,'--golden',GOLDEN,'--output',dest,'--count',str(rate*SECONDS),'--seed','42','--tenants','3'],log=out/f'trace_{rate}.log')
    return dest

def start_cmd(cmd,log,env=None):
    stream=open(log,'w')
    try:p=subprocess.Popen([str(x) for x in cmd],cwd=ROOT,env=env,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
    finally:stream.close()
    return p

def analyze_records(path):
    cols=('latency_from_dispatch_ns','request_total_ns','adapter_roundtrip_ns','inference_time_ns','execution_time_ns','scheduling_delay_ns')
    values={c:[] for c in cols};offered=0;success=0;bad=0
    with open(path) as f:
        for line in f:
            if not line.strip():continue
            r=json.loads(line);offered+=1
            if not r.get('success'):bad+=1;continue
            success+=1
            for k in cols:
                if isinstance(r.get(k),(int,float)) and r[k]>=0:values[k].append(r[k]/1e6)
    return {'offered_records':offered,'successful_records':success,'unsuccessful_records':bad,
        'measurements':{k:{'n':len(x),'mean_ms':statistics.mean(x) if x else None,'p50_ms':percent(x,.5),'p95_ms':percent(x,.95),'p99_ms':percent(x,.99)} for k,x in values.items()},
        'metric_note':'Gateway/server clock metrics are nested; do not subtract unrelated machine clocks or call execution_time pure native/guest kernel without validation.'}

def main():
    assert ROOT.is_dir()
    if not (ROOT/'serving/common_ingress/src/main.rs').is_file():raise Abort('Not in actual COMET-Wasm repository root')
    if not all(p.is_file() for p in (LOADGEN,GATEWAY,GOLDEN,TRACEGEN,NATIVE_MANIFEST)):
        raise Abort('Existing common gateway/load generator/golden/native Rust sources are missing')
    existing=latest_past()
    cpus=sorted(os.sched_getaffinity(0))
    if len(cpus)<2:raise Abort('Two accessible CPUs required (service and client)')
    srv,cli=cpus[:2]
    if not free_port(GATEWAY_PORT) or not free_port(NATIVE_PORT):raise Abort('Ports 8200/8085 already occupied. Refusing to stop other jobs.')
    stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M%S')+f'_{os.getpid()}'
    out=AUT/'wp1_wp3_native_attribution'/stamp;out.mkdir(parents=True)
    report={'supervisor':'WP1 §4.1–4.5 and WP3 §6.1','baseline':'native process through common gateway (not scheduler backend)',
       'existing_wp1':str(existing.relative_to(ROOT)),'service_cpu':srv,'loadgen_cpu':cli,'rates':list(RATES),'repetitions':REPS,'seconds':SECONDS,
       'source_sha256':{'gateway':sha(GATEWAY),'loadgen':sha(LOADGEN),'golden':sha(GOLDEN)},'results':[],'status':'RUNNING','blockers':[]}
    def save(): (out/'RESULT.json').write_text(json.dumps(report,indent=2)+'\n')
    save();print('SUPERVISOR WP1 §4 / WP3 §6 NATIVE COMMON-INGRESS FULL CAMPAIGN',flush=True)
    print('RESULTS:',out,flush=True)
    print('Existing matched Wasmtime/Docker records will be analyzed without rerunning',flush=True)
    native=None;gateway=None
    try:
        # This is the same Rust LR inference service source used by existing Docker image.
        if not NATIVE_BINARY.is_file():
            print('BUILD native executable from existing docker/lr_server source',flush=True)
            call(['cargo','build','--release','--manifest-path',NATIVE_MANIFEST],log=out/'native_build.log',timeout=1800)
        report['source_sha256']['native_binary']=sha(NATIVE_BINARY)
        routes={str(i):{'backend':'native','model':'lr','url':f'http://127.0.0.1:{NATIVE_PORT}/infer'} for i in range(3)}
        routefile=out/'native_routes.json';routefile.write_text(json.dumps(routes,indent=2)+'\n')
        env=os.environ.copy();env.update({'COMET_INGRESS_WORKERS':'2','COMET_WASM_WORKERS':'2'})
        native=start_cmd(['taskset','-c',str(srv),NATIVE_BINARY],out/'native_server.log',env)
        gateway=start_cmd(['taskset','-c',str(srv),GATEWAY,routefile],out/'common_ingress.log',env)
        poll_probe(jsonread(GOLDEN))
        report['processes']={'native':procstatus(native.pid),'gateway':procstatus(gateway.pid)}
        save()
        base=out/'native';base.mkdir()
        for rate in RATES:
            trace=trace_path(existing,rate,out)
            report.setdefault('trace_sha256',{})[str(rate)]=sha(trace)
            for rep in range(1,REPS+1):
                if native.poll() is not None or gateway.poll() is not None:raise Abort('Gateway or native process exited mid-campaign')
                prefix=base/f'rps{rate}_rep{rep}'
                cmd=['taskset','-c',str(cli),LOADGEN,trace,GOLDEN,'http',f'http://127.0.0.1:{GATEWAY_PORT}/infer','native',str(rate),'3000','512',prefix]
                clientenv=os.environ.copy();clientenv['COMET_LOADGEN_WORKERS']='2'
                call(cmd,log=base/f'rps{rate}_rep{rep}.log',timeout=SECONDS*4+90,env=clientenv)
                summ=jsonread(prefix.with_suffix('.summary.json'))
                raw=analyze_records(prefix.with_suffix('.requests.jsonl'))
                row={'backend':'native','model':'lr','rps':rate,'repeat':rep,'summary':summ,'raw_analysis':raw,
                  'gateway_threads':procstatus(gateway.pid).get('Threads'),'native_threads':procstatus(native.pid).get('Threads')}
                report['results'].append(row);save()
                ok=int(summ.get('successful_requests',0))==rate*SECONDS and all(int(summ.get(k,0))==0 for k in ('failed_requests','timed_out_requests','dropped_requests'))
                print(f'NATIVE common gateway {rate} RPS rep {rep:02}/{REPS}: '+('PASS' if ok else 'LOAD LOSS')+f' success={summ.get("successful_requests")}/{rate*SECONDS}',flush=True)
        report['status']='NATIVE_CAMPAIGN_COMPLETE'
    except Exception as e:
        report['status']='BLOCKED';report['blockers'].append(f'{type(e).__name__}: {e}')
        print('BLOCKED:',e,flush=True)
    finally:
        terminate(gateway);terminate(native)
        # Scientific decomposition, including previously collected backend records.
        cross=[]
        for backend in ('wasmtime','docker'):
            folder=existing.parent/f'lr_{backend}'
            for rate in RATES:
                for rep in range(1,4):
                    prefix=folder/f'rps{rate}_rep{rep}'
                    src=prefix.with_suffix('.requests.jsonl')
                    if src.exists():cross.append({'backend':backend,'rps':rate,'repeat':rep,'source':str(src.relative_to(ROOT)),**analyze_records(src)})
        for r in report['results']:
            cross.append({'backend':'native','rps':r['rps'],'repeat':r['repeat'],'source':'new native campaign',**r['raw_analysis']})
        (out/'TIMING_DECOMPOSITION.json').write_text(json.dumps(cross,indent=2)+'\n')
        rows=[]
        for x in cross:
            row={k:x[k] for k in ('backend','rps','repeat','source')}
            row['successful_records']=x['successful_records'];row['unsuccessful_records']=x['unsuccessful_records']
            for k,v in x['measurements'].items():row[k+'_mean_ms']=v['mean_ms'];row[k+'_p95_ms']=v['p95_ms']
            rows.append(row)
        if rows:
            with (out/'TIMING_DECOMPOSITION.csv').open('w',newline='') as f:
                w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
        report['historical_backend_raw_comparisons']=len(cross)-len(report['results'])
        report['scope_limits']=['Native route uses gateway/loopback backend and identical Rust LR service source, not a third scheduler backend.',
            'Only native path runs now; Wasmtime/Docker historical campaigns have three repetitions and possibly different max-inflight settings, so pooled cross-backend statistical equivalence is NOT asserted.',
            'Existing Docker gateway route uses a published loopback port; verified Docker bridge internals still require a separate deployment review.',
            'Execution, inference, adapter and gateway timings have nested boundaries; guest-call/input-copy isolation cannot be inferred by subtraction alone.',
            'No-go remains until WP1 generator headroom, matched threads and WP2 helper visibility are scientifically resolved.']
        report['stop_go']='NO_GO_PENDING_ACCEPTANCE'
        save()
        lines=['# WP1/WP3 Native common-ingress attribution campaign','',f"**Status:** {report['status']}",f"**Native trials:** {len(report['results'])}/{len(RATES)*REPS}",f"**Historical backend request-series read:** {report['historical_backend_raw_comparisons']}",
           '', '## Scope limits and supervisor acceptance']+['- '+x for x in report['scope_limits']]+['', '**WP1–WP3 Stop/Go remains NO-GO pending acceptance.**','', 'See `TIMING_DECOMPOSITION.csv` and `RESULT.json` for evidence.']
        (out/'REPORT.md').write_text('\n'.join(lines)+'\n')
        print('FINAL:',report['status'],'\nREPORT:',out/'REPORT.md','\nCOMPARISON:',out/'TIMING_DECOMPOSITION.csv',flush=True)
    return 0 if report['status']=='NATIVE_CAMPAIGN_COMPLETE' else 2

if __name__=='__main__':
    try:sys.exit(main())
    except Exception:traceback.print_exc();sys.exit(2)
