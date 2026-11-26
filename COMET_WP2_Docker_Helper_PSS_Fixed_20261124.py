#!/usr/bin/env python3
"""WP2 Docker attributable app PSS versus per-container helper PSS.
Read-only to existing experiments; launches only uniquely named containers,
removes only containers it launched, never claims shared daemon PSS is owned.
"""
import argparse, datetime, json, os, pathlib, shutil, subprocess, time, uuid, statistics
ROOT=pathlib.Path(__file__).resolve().parent
REPORTS=ROOT/'research_enhancement/reports/wp2_docker_helper_pss'

def cmd(*args, check=True):
    p=subprocess.run(args,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=90)
    if check and p.returncode: raise RuntimeError(f'{args}: {p.stderr.strip()}')
    return p.stdout.strip() if p.returncode==0 else None

def proc_pss(pid):
    try:
        rows=(pathlib.Path('/proc')/str(pid)/'smaps_rollup').read_text().splitlines()
        for s in rows:
            if s.startswith('Pss:'): return int(s.split()[1])/1024
    except (OSError,ValueError,PermissionError): pass
    return None

def container_app_pss(cid):
    """Read application PID 1 PSS inside its own PID namespace, without host root.

    Container images are built on a Rust/Linux userspace with a shell. If the
    required binary is absent, fail explicitly rather than substitute RSS.
    """
    command = "grep '^Pss:' /proc/1/smaps_rollup"
    r = subprocess.run(['docker','exec',cid,'sh','-c',command],
                       capture_output=True,text=True,timeout=20)
    if r.returncode:
        return None, r.stderr.strip() or 'docker exec could not access /proc/1/smaps_rollup'
    try: return float(r.stdout.split()[1]) / 1024.0, None
    except ValueError: return None, 'No readable Pss value from inside container'

def cmdline(pid):
    try: return (pathlib.Path('/proc')/str(pid)/'cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace')
    except OSError:return ''

def all_pids():
    for f in pathlib.Path('/proc').iterdir():
        if f.name.isdigit(): yield int(f.name)

def container_pids(container_id, main_pid):
    # cgroup v2/v1: same container token in /proc/PID/cgroup. Fall back to main PID.
    ps=set()
    for pid in all_pids():
        try:
            cg=(pathlib.Path('/proc')/str(pid)/'cgroup').read_text()
            if container_id in cg: ps.add(pid)
        except OSError:pass
    if main_pid>0:ps.add(main_pid)
    return sorted(ps)

def helpers(container_id):
    # A containerd shim can be uniquely associated with a container ID.
    matching=[]
    for pid in all_pids():
        line=cmdline(pid)
        if 'containerd-shim' in line and container_id in line:
            matching.append(pid)
    return matching

def shared_snapshot():
    ans={}
    for pid in all_pids():
        line=cmdline(pid)
        if line and any(x in line for x in ('dockerd','containerd')) and not ('containerd-shim' in line):
            if pid==os.getpid():continue
            v=proc_pss(pid)
            if v is not None:ans[pid]={'pss_mib':v,'cmd':line[:180]}
    return ans

def sample(image, reps, settle):
    results=[]
    for i in range(reps):
        name='comet_wp2_helper_'+uuid.uuid4().hex[:10]
        before=shared_snapshot()
        cid=None
        try:
            cid=cmd('docker','run','-d','--rm','--network','bridge','--name',name,image)
            time.sleep(settle)
            pid=int(cmd('docker','inspect','-f','{{.State.Pid}}',cid))
            if pid<=0:raise RuntimeError('Container exited before PSS sampling')
            ps=container_pids(cid,pid); hs=helpers(cid)
            app={str(p):proc_pss(p) for p in ps}; h={str(p):proc_pss(p) for p in hs}
            app_source='host_proc'
            if not any(v is not None for v in app.values()):
                measured, why=container_app_pss(cid)
                if measured is None:
                    raise RuntimeError('Cannot read application PSS from host or inside container: '+str(why))
                # In this project's Docker LR/RF images the sole app is PID 1.
                # Do not pretend a host PID read succeeded.
                app={str(pid):measured}
                app_source='docker_exec_pid1_smaps_rollup'
            now=shared_snapshot()
            shared_delta={str(p):round(now[p]['pss_mib']-before[p]['pss_mib'],6) for p in (set(before)&set(now))}
            results.append({'repetition':i+1,'container_id':cid,'app_process_pss_mib':app,'app_pss_measurement_source':app_source,
                            'app_total_pss_mib':sum(v for v in app.values() if v is not None),
                            'per_container_shim_pss_mib':h,
                            'shim_pss_measurable':any(v is not None for v in h.values()),'shim_pss_permission_limited':bool(h) and not any(v is not None for v in h.values()),
                            'shim_total_pss_mib':sum(v for v in h.values() if v is not None) if any(v is not None for v in h.values()) else None,
                            'shared_docker_daemon_pss_change_mib_NONATTRIBUTABLE':shared_delta})
            print(f'{image} repetition {i+1}/{reps} app PSS {results[-1]["app_total_pss_mib"]:.3f} MiB, shim {results[-1]["shim_total_pss_mib"]}',flush=True)
        finally:
            if cid:
                cmd('docker','rm','-f',cid,check=False)
            else:
                cmd('docker','rm','-f',name,check=False)
    return results

def main():
    a=argparse.ArgumentParser()
    a.add_argument('--images',nargs='+',default=['comet-wp1cap-lr:latest','comet-wp1-rf:validated-20261123'])
    a.add_argument('--repetitions',type=int,default=20)
    a.add_argument('--settle-seconds',type=float,default=0.35)
    args=a.parse_args()
    if not 1<=args.repetitions<=100 or not .05<=args.settle_seconds<=10:raise SystemExit('Invalid repetition/settle settings')
    if shutil.which('docker') is None:raise SystemExit('Docker not found')
    cmd('docker','info')
    result={'scope':'WP2 §5 Docker application PSS and measurable per-container runtime helpers',
            'warning':'Shared dockerd/containerd PSS change is shown separately but is NOT safely attributable to a single tenant. No substitution for seven-model density matrix.',
            'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'images':{},'unavailable_images':[]}
    out=REPORTS/(datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M%S')+'_'+str(os.getpid()))
    out.mkdir(parents=True,exist_ok=False)
    try:
        for image in args.images:
            if cmd('docker','image','inspect',image,check=False) is None:
                print('IMAGE UNAVAILABLE:',image,flush=True);result['unavailable_images'].append(image);continue
            obs=sample(image,args.repetitions,args.settle_seconds)
            result['images'][image]={'repetitions':obs,
              'application_mean_pss_mib':statistics.mean(x['app_total_pss_mib'] for x in obs),
              'measured_shim_mean_pss_mib':statistics.mean(x['shim_total_pss_mib'] for x in obs if x['shim_total_pss_mib'] is not None) if any(x['shim_total_pss_mib'] is not None for x in obs) else None}
            (out/'results.json').write_text(json.dumps(result,indent=2)+'\n')
    except Exception as exc:
        result['failure']=str(exc)
        (out/'results.json').write_text(json.dumps(result,indent=2)+'\n')
        raise
    (out/'results.json').write_text(json.dumps(result,indent=2)+'\n')
    print('RESULT',out/'results.json',flush=True)
    print(json.dumps({k:{'app_pss_mean_mib':v['application_mean_pss_mib'],'shim_pss_mean_mib':v['measured_shim_mean_pss_mib']} for k,v in result['images'].items()},indent=2))
    if result['unavailable_images']:print('UNAVAILABLE_IMAGES',result['unavailable_images'])
if __name__=='__main__':main()
