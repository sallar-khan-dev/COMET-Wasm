#!/usr/bin/env python3
"""Resume supervisor WP1 controlled LR/RF pilot with corrected validated RF image.
Preserves original supervisor harness and all previous measurements. Refuses to
substitute an unverified image. Uses harness native reference/golden checks.
"""
from pathlib import Path
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys

root=Path(__file__).resolve().parent
original=root/'COMET_Auto_Workplan_v4.py'
image='comet-wp1-rf:validated-20261123'
expected='sha256:694b2945ddfb6758e9ebd3f24435cd5ba74a0953faf493e54a0def73d15bbd9f'
if not original.is_file():
    sys.exit('SAFE STOP: original COMET_Auto_Workplan_v4.py missing. Existing data unaffected.')
r=subprocess.run(['docker','image','inspect','--format','{{.Id}}',image],capture_output=True,text=True)
if r.returncode or r.stdout.strip()!=expected:
    sys.exit('SAFE STOP: corrected RF Docker image missing or SHA does not match the previously validated image. Existing data unaffected. Actual: '+r.stdout.strip()+' '+r.stderr.strip())
s=original.read_text()
needle="    image=pilot['rf_image'];image_id=run(['docker','image','inspect','-f','{{.Id}}',image],check=False)\n    must(image_id.returncode==0 and image_id.stdout.strip()==pilot['rf_docker_image_id'],'RF Docker image unavailable or changed')"
replacement=("    # Revised 2026-11-23 RF image: independently reference-validated (569/569).\n"
             "    # Image digest is pinned; all original RF golden, WASM and pilot checks remain.\n"
             "    image='comet-wp1-rf:validated-20261123'\n"
             "    image_id=run(['docker','image','inspect','-f','{{.Id}}',image],check=False)\n"
             "    must(image_id.returncode==0 and image_id.stdout.strip()=='sha256:694b2945ddfb6758e9ebd3f24435cd5ba74a0953faf493e54a0def73d15bbd9f', 'Validated 20261123 RF Docker image missing or changed')")
if s.count(needle)!=1:
    sys.exit('SAFE STOP: expected harness verification snippet not found exactly once. Original untouched.')
s=s.replace(needle,replacement)
patched=root/'COMET_Auto_Workplan_v4_RF_Validated_20261124.py'
if patched.exists() and patched.read_text()!=s:
    sys.exit('SAFE STOP: patched runner path occupied with different contents; refusing overwrite.')
patched.write_text(s)
report=root/'research_enhancement/reports/wp1_controlled_serving_pilot'/('resume_'+dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d_%H%M%S'))
report.mkdir(parents=True,exist_ok=False)
(report/'PROVENANCE.json').write_text(json.dumps({
    'original_harness':str(original),'original_harness_sha256':hashlib.sha256(original.read_bytes()).hexdigest(),
    'patched_harness':str(patched),'corrected_image':image,'image_digest':expected,
    'reason':'Historical RF image was superseded by the 2026-11-23 validated image; legacy image identity gate is stale.',
    'pilot_preservation':'new run directory; existing 1,027 WP1 repetitions untouched',
    'method':'same supervisor WP1 LR/RF open-loop rate grid, reference oracle, no-op, resource sampling',
    'scope':'WP1 controlled pilot only; no native-process substitution; no GO asserted'},indent=2)+'\n')
print('RF image digest verified; preserved golden/pilot validations.',flush=True)
print('Starting NEW bounded-thread WP1 pilot using corrected RF image.',flush=True)
cmd=[sys.executable,str(patched),'--mode','auto','--rates','100','300','600','1200','2400',
     '--repetitions','3','--seconds','15','--service-cpu','0','--client-cpu','1']
env=os.environ.copy();env['COMET_LR_DOCKER_IMAGE']='comet-wp1cap-lr:latest';env['PYTHONUNBUFFERED']='1'
with (report/'RUN.log').open('w') as log:
    p=subprocess.Popen(cmd,cwd=root,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,bufsize=1)
    for line in p.stdout:
        print(line,end='',flush=True);log.write(line);log.flush()
    rc=p.wait()
print('Exit code:',rc,'Log:',report/'RUN.log',flush=True)
sys.exit(rc)
