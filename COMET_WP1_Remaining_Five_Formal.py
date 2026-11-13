#!/usr/bin/env python3
"""COMET-Wasm WP1 five-model formal extension (NB, DT, KMeans, SVM, MLP).

Reuses COMET_Auto_Workplan_v4_BUNDLED's actual 15-second open-loop trials,
no-op headroom, process accounting, and independent-run Student-t + bootstrap
95% CI adaptive 20..60 protocol. Uses the same isolated
Tokio max_blocking_threads(1) gateway as the LR/RF correction.

No preliminary smoke benchmarking; correctness is verified during actual trials.
Run only after the existing LR/RF campaign finishes. Does not overwrite it.
"""
import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import types

ROOT=Path(__file__).resolve().parent
BUNDLED=ROOT/'COMET_Auto_Workplan_v4_BUNDLED.py'
CORRECTED=ROOT/'COMET_WP1_One_Command_Parity_Corrected.py'
MODELS=('nb','dt','kmeans','svm','mlp')
RATES=(100,300,600,1200,2400)
OUTROOT=ROOT/'research_enhancement/automated_supervisor_workplan/wp1_five_model_formal'
REF_DIR=ROOT/'research_enhancement/v2_references'
WP1_GOLD=ROOT/'research_enhancement/v2_wp1_workloads/golden'


def fail(msg): raise RuntimeError(msg)
def sha(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda:f.read(1<<20),b''):h.update(b)
    return h.hexdigest()

def load(path,name):
    spec=importlib.util.spec_from_file_location(name,str(path))
    if not spec or not spec.loader: fail('Missing Python module: '+str(path))
    mod=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

def ports():
    sockets=[]
    try:
        for _ in range(2):
            sock=socket.socket();sock.bind(('127.0.0.1',0));sockets.append(sock)
        return [s.getsockname()[1] for s in sockets]
    finally:
        for s in sockets:s.close()

def unique_file(candidates,description):
    seen={str(p.resolve()):p for p in candidates if p.is_file()}
    if len(seen)!=1:
        fail(f'{description}: need exactly one matching file, found {list(map(str,seen.values()))}. '
             'Set up model-specific artifact before formal experiments; no synthetic substitute.')
    return next(iter(seen.values()))

def model_artifacts(model,out):
    # Model paths are discovered from existing project artifacts, not substituted
    # with another model's binary, reference, or container.
    wasm_dir=ROOT/'wasm'/f'tenant_{model}_real'
    wasm=unique_file(wasm_dir.glob('target/wasm32-unknown-unknown/release/*.wasm'),model+' Wasm binary')
    source_candidates=list(REF_DIR.glob(f'{model}_*_golden*.json'))+list(WP1_GOLD.glob(f'{model}_*_golden.json'))
    gold_candidates=[]
    for p in source_candidates:
        try:
            data=json.loads(p.read_text())
            if data.get('model') not in (None,model):continue
            rows=data.get('records',[])
            if isinstance(rows,list) and rows and isinstance(rows[0].get('features'),list):gold_candidates.append((p,data))
        except (ValueError,TypeError,AttributeError):pass
    if not gold_candidates:fail(f'{model}: existing oracle reference missing in {REF_DIR} or {WP1_GOLD}')
    # Prefer native v2 golden over legacy source, and prefer the project's WP1 source.
    gold_candidates.sort(key=lambda x:(x[1].get('schema_version')=='comet-v2-golden-v1', 'v2_references' in str(x[0])),reverse=True)
    orig,data=gold_candidates[0]
    if data.get('schema_version')=='comet-v2-golden-v1' and all('expected_prediction' in r for r in data['records']):
        gold=orig
    else:
        rows=[]
        for i,r in enumerate(data['records']):
            pred=r.get('expected_prediction',r.get('prediction'))
            if pred is None:fail(f'{model}: reference record {i} lacks oracle prediction')
            row={'row_index':r.get('row_index',r.get('id',i)),
                 'features':r['features'],'expected_prediction':pred}
            label=r.get('ground_truth_label',r.get('dataset_label'))
            if label is not None:row['ground_truth_label']=label
            rows.append(row)
        # This fingerprint identifies the REFERENCE RECORDS, not an original
        # training dataset. No labels or predictions are invented.
        fingerprint=hashlib.sha256(json.dumps(
            [{'row_index':r['row_index'],'features':r['features'],
              'ground_truth_label':r.get('ground_truth_label')} for r in rows],
            sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        modelhash=data.get('model_sha256')
        if not isinstance(modelhash,str) or len(modelhash)!=64:
            fail(f'{model}: source reference missing a validated model_sha256')
        adapted={'schema_version':'comet-v2-golden-v1','model':model,
                 'dataset':data.get('dataset','existing-reference'),
                 'model_sha256':modelhash,
                 'dataset_sha256':data.get('dataset_sha256') or fingerprint,
                 'sample_count':len(rows),'records':rows,
                 'reference_provenance':str(orig.relative_to(ROOT)),
                 'source_sha256':sha(orig),
                 'fingerprint_scope':'reference records (not original dataset file)',
                 'expected_predictions':'Copied unchanged from existing reference'}
        gold=out/f'{model}_golden_v2_adapted.json'
        gold.write_text(json.dumps(adapted,indent=2,allow_nan=False)+'\n')
    docker_dir=ROOT/'docker'/f'{model}_server'
    image=os.environ.get(f'COMET_{model.upper()}_DOCKER_IMAGE',f'comet-wp1-{model}:latest')
    inspect=subprocess.run(['docker','image','inspect','-f','{{.Id}}',image],capture_output=True,text=True)
    if inspect.returncode:
        if not (docker_dir/'Dockerfile').is_file():fail(f'{model}: Docker image {image} absent and Dockerfile missing in {docker_dir}')
        print(f'BUILD {model} existing Docker server image {image}',flush=True)
        with (out/f'{model}_docker_build.log').open('w') as log:
            p=subprocess.run(['docker','build','-t',image,str(docker_dir)],cwd=ROOT,
                             stdout=log,stderr=subprocess.STDOUT,timeout=3600)
        if p.returncode:fail(f'{model}: Docker build failed; inspect {out}/{model}_docker_build.log')
        inspect=subprocess.run(['docker','image','inspect','-f','{{.Id}}',image],capture_output=True,text=True)
        if inspect.returncode:fail(f'{model}: built image cannot be inspected')
    return {'wasm':wasm,'gold':gold,'gold_source':orig,'image':image,'image_id':inspect.stdout.strip()}


def load_formal_module():
    source=BUNDLED.read_text()
    # The historical runner hardcodes RF's Wasm path for every non-LR model.
    # Correct precisely that routing without changing trial/statistics methods.
    old="str(LR_WASM if model=='lr' else RF_WASM)"
    if source.count(old)!=1:fail('Existing formal runner Wasm routing changed; cannot safely extend')
    source=source.replace(old,"str(WASM_PATH_MAP[model])")
    module=types.ModuleType('comet_formal_five_existing')
    module.__file__=str(BUNDLED)
    exec(compile(source,str(BUNDLED),'exec'),module.__dict__)
    return module


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--models',nargs='+',choices=MODELS,default=list(MODELS))
    args=ap.parse_args()
    if len(set(args.models))!=len(args.models):fail('Duplicate model selected')
    for p in (BUNDLED,CORRECTED):
        if not p.is_file():fail('Required original formal module not found: '+str(p))
    out=OUTROOT/(dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d_%H%M%S')+'_'+str(os.getpid()))
    out.mkdir(parents=True,exist_ok=False)
    print('WP1 FIVE-MODEL FORMAL EXTENSION:',', '.join(args.models),flush=True)
    print('Reusing original 15s workload and 20..60 Student-t + bootstrap CI methodology',flush=True)
    print('OUTPUT DIRECTORY:',out,flush=True)
    models={name:model_artifacts(name,out) for name in args.models}
    mod=load_formal_module()
    mod.WP1_MODELS=tuple(args.models)
    mod.WASM_PATH_MAP={name:row['wasm'] for name,row in models.items()}
    mod.OUTROOT=OUTROOT
    gateway_port,docker_port=ports()
    mod.GATEWAY_PORT=gateway_port
    mod.DOCKER_HOST_PORT=docker_port
    # Use identical isolated gateway correction as current LR/RF campaign.
    corrected=load(CORRECTED,'comet_existing_isolated_correction')
    gateway=corrected.corrected_build(None,mod,out,gateway_port)
    mod.ING=gateway
    def existing():
        required=(mod.GEN,mod.TRACEGEN,mod.ING)
        if any(not p.is_file() for p in required):fail('Missing existing load generator or trace generator')
        return {'images':{m:d['image'] for m,d in models.items()},
                'image_ids':{m:d['image_id'] for m,d in models.items()}}
    mod.verify_existing=existing
    def prep(output,model,count):
        gold=models[model]['gold'];trace=output/f'{model}_trace_{count}.json'
        if not trace.exists():
            mod.run([sys.executable,mod.TRACEGEN,'--golden',gold,'--output',trace,
                     '--count',str(count),'--seed','42','--tenants','3'],
                    log=output/f'{model}_trace_generation.log',timeout=180)
        obj=json.loads(trace.read_text());ref=json.loads(gold.read_text())
        mod.must(obj.get('model')==model and obj.get('request_count')==count and
                 len(obj.get('requests',[]))==count and
                 obj.get('golden_artifact_sha256')==sha(gold) and
                 obj.get('golden_model_sha256')==ref.get('model_sha256'),
                 f'{model}: generated trace and reference fingerprint do not agree')
        return trace,gold
    mod.prepare_trace=prep
    def oracle(model,backend,timeout=30):
        import time,urllib.request
        ref=json.loads(models[model]['gold'].read_text())['records'][0]
        req={'request_id':'wp1-oracle','tenant_id':0,'model':model,'features':ref['features']}
        payload=json.dumps(req).encode();last='unreachable';stop=time.monotonic()+timeout
        while time.monotonic()<stop:
            try:
                request=urllib.request.Request(f'http://127.0.0.1:{gateway_port}/infer',data=payload,
                           headers={'Content-Type':'application/json'},method='POST')
                with urllib.request.urlopen(request,timeout=2) as res:body=json.loads(res.read())
                if body.get('backend')==backend and body.get('prediction')==ref['expected_prediction']:return True
                last=f'Oracle mismatch: {body}';break
            except Exception as e:last=str(e);time.sleep(.25)
        fail(f'{model}/{backend} oracle mismatch before formal measurements: {last}')
    mod.inference_ready=oracle
    def conf(a,srv,cli,existing):
        return {'models':list(args.models),'rates':a.rates,'seconds':a.seconds,
                'repetitions':a.repetitions,'min_repetitions':mod.FORMAL_MIN_REPS,
                'max_repetitions':mod.FORMAL_MAX_REPS,'confidence':mod.FORMAL_CONFIDENCE,
                'target_relative_halfwidth':mod.FORMAL_TARGET,'service_cpu':srv,
                'client_cpu':cli,'max_inflight':a.max_inflight,'noop_multiplier':a.noop_multiplier,
                'images':existing['image_ids'],'loadgen_sha256':sha(mod.GEN),
                'ingress_sha256':sha(mod.ING),
                'model_artifacts':{m:{'wasm_sha256':sha(d['wasm']),
                                      'gold_sha256':sha(d['gold']),
                                      'image_id':d['image_id']} for m,d in models.items()}}
    mod.config=conf
    manifest={'models':list(args.models),'backends':['wasmtime','docker'],
              'rates_rps':list(RATES),'duration_seconds':15,
              'min_runs_per_cell':20,'max_runs_per_cell':60,
              'confidence':0.95,'target_relative_ci_halfwidth':0.025,
              'metrics':list(mod.FORMAL_METRICS),
              'statistical_method':'Independent run-level Student-t and bootstrap 95% CI',
              'stopping_rule':'Stop if every metric passes both intervals and correctness passes; otherwise stop at 60 and record unmet',
              'gateway_blocking_threads':1,'gateway_binary_sha256':sha(gateway),
              'original_formal_runner_sha256':sha(BUNDLED),
              'models_detail':{m:{k:str(v) for k,v in d.items()} for m,d in models.items()},
              'methodology':'Matches LR/RF corrected campaign; no automatic supervisor GO'}
    (out/'FIVE_MODEL_MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
    # Existing runner keeps raw summaries and request records in its own
    # timestamped folder. Do not interfere with the preceding LR/RF run.
    values=argparse.Namespace(mode='auto',rates=list(RATES),seconds=15,repetitions=60,
             noop_multiplier=2,max_inflight=512,service_cpu=None,client_cpu=None,
             resume=None,resume_latest=False)
    print('START FORMAL 5 models x 2 backends x 5 offered rates = 50 independent cells',flush=True)
    rc=mod.run_auto(values)
    state_files=sorted(OUTROOT.glob('*/state.json'),key=lambda p:p.stat().st_mtime)
    if state_files:
        result=state_files[-1];state=json.loads(result.read_text());cells=state.get('WP1',{}).get('formal_precision',{})
        summary={'status':state.get('WP1',{}).get('status'),'actual_results':str(result.parent),
                 'completed_cells':len(cells),'expected_cells':len(args.models)*2*len(RATES),
                 'precision_and_correctness_passed':sum(bool(x.get('formal_acceptance')) for x in cells.values()),
                 'unmet_cells':[k for k,v in cells.items() if not v.get('formal_acceptance')],
                 'completed_independent_runs':len(state.get('WP1',{}).get('runs',[])),
                 'supervisor_stop_go':'PENDING_MANUAL_ACCEPTANCE'}
        (out/'FIVE_MODEL_FINAL_REVIEW.json').write_text(json.dumps(summary,indent=2)+'\n')
        print('FINAL SUMMARY:',out/'FIVE_MODEL_FINAL_REVIEW.json',flush=True)
        print(json.dumps(summary,indent=2),flush=True)
    return rc

if __name__=='__main__':
    try:sys.exit(main())
    except Exception as exc:
        print('CAMPAIGN STOPPED:',str(exc),file=sys.stderr,flush=True)
        sys.exit(2)
