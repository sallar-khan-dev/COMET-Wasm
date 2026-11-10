#!/usr/bin/env python3
"""COMET-Wasm WP2 §5: controlled Docker memory attribution experiment.

Runs fresh Docker RF processes and samples application PSS from inside each
container, host-visible runtime/helper PSS where accessible, and a baseline.
No alteration of existing COMET files. Does NOT certify helper attribution
when dockerd/containerd are shared with unrelated workloads.
"""
import argparse, csv, datetime, fcntl, hashlib, json, os, pathlib, re, shutil, signal, statistics, subprocess, sys, time, uuid
ROOT=pathlib.Path(__file__).resolve().parent
OUTROOT=ROOT/'research_enhancement/automated_supervisor_workplan/wp2_memory_attribution'

def command(args, timeout=20, check=True):
    p=subprocess.run([str(x) for x in args], capture_output=True,text=True,timeout=timeout)
    if check and p.returncode:
        raise RuntimeError(f"{args[0]} exited {p.returncode}: {p.stderr[-900:] or p.stdout[-900:]}")
    return p

def bytes_sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1<<20),b''): h.update(block)
    return h.hexdigest()

def proc_stat(pid):
    p=pathlib.Path('/proc')/str(pid)
    d={'pid':pid,'pss_kib':None,'rss_kib':None,'threads':None,'cpu_allowed':None}
    try:
        for line in (p/'status').read_text().splitlines():
            if line.startswith('Threads:'):d['threads']=int(line.split()[1])
            if line.startswith('Cpus_allowed_list:'):d['cpu_allowed']=line.split(':',1)[1].strip()
        for line in (p/'smaps_rollup').read_text().splitlines():
            if line.startswith('Pss:'):d['pss_kib']=int(line.split()[1])
            if line.startswith('Rss:'):d['rss_kib']=int(line.split()[1])
    except (PermissionError,OSError,ValueError):pass
    return d

def helper_pids():
    result=[]
    for path in pathlib.Path('/proc').iterdir():
        if not path.name.isdigit():continue
        try:
            comm=(path/'comm').read_text().strip()
        except OSError:continue
        if comm in ('dockerd','containerd','containerd-shim-runc-v2','docker-proxy'):
            result.append({'comm':comm,**proc_stat(int(path.name))})
    return result

def app_mem(name):
    # Use container namespace to access its process' smaps; no host privileges required.
    p=command(['docker','exec','-u','0',name,'cat','/proc/1/smaps_rollup'],timeout=10,check=False)
    if p.returncode:return {'pss_kib':None,'rss_kib':None,'error':(p.stderr or p.stdout).strip()[:250]}
    d={'pss_kib':None,'rss_kib':None}
    for ln in p.stdout.splitlines():
        if ln.startswith('Pss:'):d['pss_kib']=int(ln.split()[1])
        if ln.startswith('Rss:'):d['rss_kib']=int(ln.split()[1])
    return d

def numeric_sum(items):
    values=[p['pss_kib'] for p in items if p['pss_kib'] is not None]
    return sum(values) if len(values)==len(items) else None

def record_csv(p, rows):
    if not rows:return
    with p.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

def run(args):
    assert ROOT.exists()
    if not shutil.which('docker'):raise RuntimeError('Docker CLI unavailable')
    image_info=command(['docker','image','inspect',args.image,'--format','{{.Id}}'],timeout=20).stdout.strip()
    if not image_info:raise RuntimeError('Requested image does not exist; not building or changing existing artifacts')
    allowed=sorted(os.sched_getaffinity(0))
    if args.cpu not in allowed:raise RuntimeError(f'Selected CPU {args.cpu} not in allowed set {allowed}')
    OUTROOT.mkdir(parents=True,exist_ok=True)
    lock=(OUTROOT/'.single_runner.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    out=OUTROOT/(datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M%S')+'_'+str(os.getpid()))
    out.mkdir()
    meta={'scope':'WP2 Docker RF PSS and runtime/helper attribution','image':args.image,'image_id':image_info,'repetitions':args.repetitions,'cpu':args.cpu,'sampling_interval_s':args.interval,'sampling_count':args.samples,'git_head':None,'warning':'Shared dockerd/containerd PSS is not causal per-container attribution unless daemon isolation is demonstrated.'}
    g=command(['git','rev-parse','HEAD'],check=False);meta['git_head']=g.stdout.strip()
    (out/'manifest.json').write_text(json.dumps(meta,indent=2)+'\n')
    name=None;rows=[];per_samples=[]
    try:
        print('WP2 ACTUAL MEMORY EXPERIMENT | Docker RF app + visible runtime helpers',flush=True)
        print('OUTPUT:',out,flush=True)
        print('REPETITIONS:',args.repetitions,'IMAGE:',args.image,flush=True)
        for rep in range(1,args.repetitions+1):
            before=helper_pids()
            name='comet_wp2_mem_'+uuid.uuid4().hex[:12]
            command(['docker','run','-d','--name',name,'--network','bridge','--cpuset-cpus',str(args.cpu),'--memory','2g','--pids-limit','64',args.image],timeout=40)
            try:
                info=command(['docker','inspect',name,'--format','{{.State.Pid}} {{.State.Running}}'],timeout=10).stdout.split()
                if len(info)!=2 or info[1]!='true':raise RuntimeError(f'Container {name} did not remain running')
                pid=int(info[0]);sample_set=[]
                for index in range(args.samples):
                    if index:time.sleep(args.interval)
                    app=app_mem(name)
                    host=proc_stat(pid)
                    helpers=helper_pids()
                    row={'rep':rep,'sample':index,'container':name,'pid':pid,'app_pss_kib':app['pss_kib'],'app_rss_kib':app['rss_kib'],'host_app_pss_kib':host['pss_kib'],'host_app_threads':host['threads'],'host_app_cpu_allowed':host['cpu_allowed'],'helper_pss_kib':numeric_sum(helpers),'baseline_helper_pss_kib':numeric_sum(before),'helper_process_count':len(helpers),'baseline_helper_process_count':len(before),'measurement_error':app.get('error','')}
                    per_samples.append(row);sample_set.append(row)
                avg=lambda field:statistics.mean(float(r[field]) for r in sample_set if r[field] is not None) if any(r[field] is not None for r in sample_set) else None
                rows.append({'rep':rep,'app_pss_kib_mean':avg('app_pss_kib'),'helper_pss_kib_mean':avg('helper_pss_kib'),'baseline_helper_pss_kib':numeric_sum(before),'helper_delta_kib':None if numeric_sum(before) is None or avg('helper_pss_kib') is None else avg('helper_pss_kib')-numeric_sum(before),'app_threads':max((r['host_app_threads'] or 0) for r in sample_set),'valid_app_pss':all(r['app_pss_kib'] is not None for r in sample_set),'valid_helper_pss':all(r['helper_pss_kib'] is not None for r in sample_set)})
            finally:
                command(['docker','rm','-f',name],check=False,timeout=30)
                name=None
            record_csv(out/'samples.csv',per_samples)
            record_csv(out/'trial_summary.csv',rows)
            print(f"TRIAL {rep:02d}/{args.repetitions} app_PSS={rows[-1]['app_pss_kib_mean']} KiB helper_delta={rows[-1]['helper_delta_kib']} KiB",flush=True)
    finally:
        if name:command(['docker','rm','-f',name],check=False,timeout=30)
        record_csv(out/'samples.csv',per_samples);record_csv(out/'trial_summary.csv',rows)
    valid_app=sum(r['valid_app_pss'] for r in rows)
    valid_help=sum(r['valid_helper_pss'] for r in rows)
    result={'experiment':'WP2 Docker RF application + helper/runtime memory','completed_trials':len(rows),'expected_trials':args.repetitions,'application_pss_trials_valid':valid_app,'helper_pss_trials_visible':valid_help,'helper_attribution_accepted':False,'method_note':'Global daemon and containerd PSS changes are observational and may be affected by other containers. Do not assign to COMET without isolated daemon or per-container helper ownership.','next':'WP2 Wasmtime JIT/AOT controlled pilot and base/model-resident attribution remain; do not claim WP2 complete.'}
    (out/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
    (out/'REPORT.md').write_text('# WP2 Docker memory experiment\n\n'+f"- Completed actual Docker starts: **{len(rows)}/{args.repetitions}**\n- Application PSS available: **{valid_app}/{len(rows)}**\n- Docker helper process PSS visible: **{valid_help}/{len(rows)}**\n- Helper memory attribution: **unverified if daemon shared**\n- Raw samples: `samples.csv`; trial summaries: `trial_summary.csv`\n\n**Next according to supervisor:** paired Wasmtime JIT/AOT memory pilot, baseline/model PSS, then WP3.\n")
    print('\nFINAL: EXPERIMENT COMPLETED; memory attribution acceptance remains conditional')
    print('REPORT:',out/'REPORT.md')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--image',default='comet-wp1-rf:latest')
    p.add_argument('--repetitions',type=int,default=20)
    p.add_argument('--samples',type=int,default=5)
    p.add_argument('--interval',type=float,default=.2)
    p.add_argument('--cpu',type=int,default=None)
    a=p.parse_args()
    if a.repetitions<2 or a.samples<2 or a.interval<=0: p.error('repetitions and samples >=2, interval >0')
    if a.cpu is None:a.cpu=min(os.sched_getaffinity(0))
    try:run(a)
    except Exception as e:print('BLOCKED:',e,file=sys.stderr,flush=True);sys.exit(2)
if __name__=='__main__':main()
