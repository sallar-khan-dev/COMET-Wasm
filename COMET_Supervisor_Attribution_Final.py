#!/usr/bin/env python3
"""COMET-Wasm supervisor WP2 §5: full repeated, container-owned helper PSS attribution.

Does not repeat density or change any existing experiments. Samples each RF Docker
application, its container-owned containerd shim, and other visible container-
specific helpers across 20 independent starts. Shared dockerd/containerd memory is
reported as NOT ATTRIBUTABLE. Produces trial CSV, raw JSONL, and an evidence report.
This resolves only what is measurable; it never substitutes an inventory for WP1-WP3 GO.
"""
import argparse, csv, datetime, json, os, pathlib, re, shutil, statistics, subprocess, sys, time, uuid, fcntl

ROOT=pathlib.Path(__file__).resolve().parent
DEST=ROOT/'research_enhancement/automated_supervisor_workplan/wp2_helper_attribution'

def cmd(a,timeout=40,check=True):
 p=subprocess.run(a,capture_output=True,text=True,timeout=timeout)
 if check and p.returncode:raise RuntimeError(f'{a}: {(p.stderr or p.stdout)[-600:]}')
 return p.stdout.strip()

def psnapshot(pid):
 p=pathlib.Path('/proc')/str(pid); d={'pid':pid,'pss_kib':None,'rss_kib':None,'threads':None,'comm':None}
 try:d['comm']=(p/'comm').read_text().strip()
 except OSError:pass
 try:
  for s in (p/'status').read_text().splitlines():
   if s.startswith('Threads:'):d['threads']=int(s.split()[1])
  for s in (p/'smaps_rollup').read_text().splitlines():
   if s.startswith('Pss:'):d['pss_kib']=int(s.split()[1])
   if s.startswith('Rss:'):d['rss_kib']=int(s.split()[1])
 except (OSError,ValueError):pass
 return d

def owned_helpers(cid):
 helpers=[]
 for p in pathlib.Path('/proc').iterdir():
  if not p.name.isdigit():continue
  try:
   raw=(p/'cmdline').read_bytes().replace(b'\0',b' ').decode(errors='replace')
   comm=(p/'comm').read_text().strip()
  except OSError:continue
  # Only count container-associated *runtime helper* processes whose command
  # line includes the exact long Docker container ID, not all system daemons.
  if cid in raw and (comm.startswith('containerd-shim') or comm in ('docker-proxy','rootlesskit')):
   item=psnapshot(int(p.name));item['cmdline']=raw[:512];helpers.append(item)
 return helpers

def app_pss(name,pid):
 # Host process PSS first; if inaccessible, read from inside container.
 h=psnapshot(pid)
 if h['pss_kib'] is not None:return {**h,'method':'host_smaps'}
 r=cmd(['docker','exec','-u','0',name,'cat','/proc/1/smaps_rollup'],check=False,timeout=12)
 for s in r.splitlines():
  if s.startswith('Pss:'):h['pss_kib']=int(s.split()[1])
  if s.startswith('Rss:'):h['rss_kib']=int(s.split()[1])
 h['method']='container_smaps' if h['pss_kib'] is not None else 'unavailable'
 return h

def mean(values):
 v=[x for x in values if x is not None]
 return statistics.mean(v) if v else None

def write_csv(path,records):
 if not records:return
 with path.open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=list(records[0]));w.writeheader();w.writerows(records)

def main():
 ap=argparse.ArgumentParser(description=__doc__)
 ap.add_argument('--image',default='comet-wp1-rf:latest')
 ap.add_argument('--repetitions',type=int,default=20)
 ap.add_argument('--samples',type=int,default=5)
 ap.add_argument('--interval',type=float,default=0.2)
 a=ap.parse_args()
 if a.repetitions<20 or a.samples<2 or a.interval<=0:ap.error('Supervisor campaign: use at least 20 trials, two samples, positive interval')
 if not shutil.which('docker'):sys.exit('BLOCKED: docker CLI not available')
 cmd(['docker','image','inspect',a.image,'--format','{{.Id}}'])
 cpu=min(os.sched_getaffinity(0))
 DEST.mkdir(parents=True,exist_ok=True)
 lock=(DEST/'.exclusive.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
 out=DEST/(datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M%S')+'_'+str(os.getpid()));out.mkdir()
 (out/'manifest.json').write_text(json.dumps({'workplan':'WP2 §5 Docker application and helper attribution','image':a.image,'n':a.repetitions,'samples':a.samples,'cpu':cpu,'git_head':cmd(['git','rev-parse','HEAD'],check=False),'note':'Shared Docker daemon PSS cannot be allocated to one container without independent proof'},indent=2)+'\n')
 trials=[];name=None
 try:
  for i in range(1,a.repetitions+1):
   name='comet_wp2_attr_'+uuid.uuid4().hex[:12]
   before=owned_helpers('not-a-real-container-id-'+uuid.uuid4().hex)
   cid=cmd(['docker','run','-d','--name',name,'--network','bridge','--cpuset-cpus',str(cpu),'--pids-limit','64',a.image],timeout=80)
   cid=cmd(['docker','inspect','--format','{{.Id}}',name])
   pid=int(cmd(['docker','inspect','--format','{{.State.Pid}}',name]))
   if pid<=0:raise RuntimeError('container exited early')
   app=[];hs=[];helper_seen=[]
   with (out/'samples.jsonl').open('a') as f:
    for j in range(a.samples):
     if j:time.sleep(a.interval)
     aa=app_pss(name,pid); hh=owned_helpers(cid)
     # A missing or unreadable helper is an unknown, never zero.
     known=(len(hh)>0 and all(h['pss_kib'] is not None for h in hh))
     helper=sum(h['pss_kib'] for h in hh) if known else None
     app.append(aa['pss_kib']);hs.append(helper);helper_seen.append(len(hh))
     f.write(json.dumps({'rep':i,'sample':j,'container_id':cid,'application':aa,'owned_helpers':hh,'owned_helper_pss_kib':helper})+'\n')
   trials.append({'rep':i,'app_pss_kib_mean':mean(app),'helper_pss_kib_mean':mean(hs),'owned_helper_process_count_max':max(helper_seen),'application_samples_valid':sum(x is not None for x in app),'helper_samples_valid':sum(x is not None for x in hs),'samples':a.samples})
   write_csv(out/'trials.csv',trials)
   print(f'TRIAL {i:02d}/{a.repetitions} RF app PSS={trials[-1]["app_pss_kib_mean"]} KiB; owned helper PSS={trials[-1]["helper_pss_kib_mean"]} KiB; helper process count={trials[-1]["owned_helper_process_count_max"]}',flush=True)
   cmd(['docker','rm','-f',name],check=False);name=None
 finally:
  if name:cmd(['docker','rm','-f',name],check=False)
 n=len(trials);valid=sum(t['helper_samples_valid']==a.samples for t in trials)
 result={'experiment':'Supervisor WP2 §5 Docker application PSS and container-owned runtime helper PSS','trials':n,'expected_trials':a.repetitions,'valid_helper_trials':valid,'app_pss_kib_mean':mean([r['app_pss_kib_mean'] for r in trials]),'container_owned_helper_pss_kib_mean':mean([r['helper_pss_kib_mean'] for r in trials]),'shared_daemon_pss_attributable':False,'status':'CONTAINER_OWNED_HELPER_OBSERVED' if valid==n else 'PARTIAL_HELPER_VISIBILITY','wp1_wp3_stop_go':'NOT_CERTIFIED','scope':'Container-owned helpers only; cannot equate this with total Docker deployment memory.'}
 (out/'RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
 lines=['# WP2 §5, Docker application and attributable runtime-helper memory','',f'- Repeated independent container starts: **{n}/{a.repetitions}**',f'- Application PSS mean: **{result["app_pss_kib_mean"]} KiB**',f'- Container-owned helper PSS mean: **{result["container_owned_helper_pss_kib_mean"]} KiB**',f'- Fully visible helper trials: **{valid}/{n}**','','Global Docker daemon/containerd PSS remains shared and is **not** attributed per tenant. A missing shim observation is **unknown**, not zero.','',f'**Status:** {result["status"]}. This alone does not establish WP1–WP3 GO.','', 'Preserved: `samples.jsonl`, `trials.csv`, `manifest.json`, `RESULT.json`.']
 (out/'REPORT.md').write_text('\n'.join(lines)+'\n')
 print('\nFINAL:',result['status'],'\nREPORT:',out/'REPORT.md','\nRESULT:',out/'RESULT.json',flush=True)

if __name__=='__main__':
 try:main()
 except Exception as e:print('BLOCKED:',repr(e),file=sys.stderr);sys.exit(2)
