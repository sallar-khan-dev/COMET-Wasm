"""Read-only process/thread and environment snapshot for research team WP1/WP2."""
import argparse,json,os,platform,subprocess
from pathlib import Path

def cmd(*args):
    try:return subprocess.run(args,capture_output=True,text=True,timeout=8).stdout.strip()
    except Exception:return 'unavailable'

def snapshot(pids):
    out={'platform':platform.platform(),'cpu_count':os.cpu_count(),'docker_version':cmd('docker','--version'),'rust_version':cmd('rustc','--version'),'wasmtime_version':cmd('wasmtime','--version'),'processes':{}}
    for pid in pids:
        path=Path(f'/proc/{pid}/status')
        if not path.exists():out['processes'][str(pid)]={'error':'not_found'};continue
        fields={}
        for line in path.read_text().splitlines():
            if line.startswith(('Name:','Threads:','VmRSS:','Cpus_allowed_list:','voluntary_ctxt_switches:','nonvoluntary_ctxt_switches:')):
                k,v=line.split(':',1);fields[k]=v.strip()
        out['processes'][str(pid)]=fields
    return out
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--pid',type=int,action='append',default=[]);a=ap.parse_args();print(json.dumps(snapshot(a.pid),indent=2))
