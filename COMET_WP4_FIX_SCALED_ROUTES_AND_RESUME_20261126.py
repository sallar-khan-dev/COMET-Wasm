#!/usr/bin/env python3
"""WP4 §7 repair: allow six already validated scaled model IDs in the same gateway.
Preserve all measurements and adaptive 20-60 repetition methodology.
"""
from pathlib import Path
import subprocess, shutil, datetime, sys, os
ROOT=Path('/home/sallar/wasiMultitenant')
SRC=ROOT/'serving/common_ingress/src/routes.rs'
MAN=ROOT/'serving/common_ingress/Cargo.toml'
BIN=ROOT/'serving/common_ingress/target/release/comet_common_ingress'
DRIVER=ROOT/'COMET_WP4_SCALED_RF_SVM_GATEWAY_20261126.py'
ORIGINAL='            "lr" | "nb" | "dt" | "kmeans" | "rf" | "svm" | "mlp"'
EXTENDED=ORIGINAL+'\n            | "rf_trees_100" | "rf_trees_200" | "rf_trees_400"\n            | "svm_c_0p03" | "svm_c_0p1" | "svm_c_0p3"'
def go():
    for f in (SRC,MAN,BIN,DRIVER):
        if not f.is_file(): raise RuntimeError(f'Missing required file: {f}')
    if ':8200 ' in subprocess.run(['ss','-ltn'],capture_output=True,text=True,check=True).stdout:
        raise RuntimeError('Port 8200 is occupied; do not rebuild an active serving gateway')
    code=SRC.read_text()
    if EXTENDED in code:
        print('Model routing already fixed; proceeding without source modifications',flush=True)
    elif code.count(ORIGINAL)==1:
        timestamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M%S')
        backup=SRC.with_name('routes.rs.pre_wp4_'+timestamp)
        backup.write_text(code)
        SRC.write_text(code.replace(ORIGINAL,EXTENDED,1))
        print('Added only the six validated WP4 model IDs; backup:',backup,flush=True)
    else:
        raise RuntimeError('Unexpected routes.rs; refusing unverified modification')
    env=os.environ.copy()
    env['CARGO_TARGET_DIR']=str(BIN.parents[1])
    print('Running gateway tests',flush=True)
    subprocess.run(['cargo','test','--manifest-path',str(MAN)],cwd=ROOT,env=env,check=True)
    prior=BIN.with_name(BIN.name+'.pre_wp4_scaled')
    if not prior.exists():shutil.copy2(BIN,prior)
    print('Rebuilding exact common gateway (no model or resource configuration changes)',flush=True)
    subprocess.run(['cargo','build','--release','--manifest-path',str(MAN)],cwd=ROOT,env=env,check=True)
    print('Resuming original scaled RF/SVM driver, existing checkpoint and precision 20-60',flush=True)
    subprocess.run([str(ROOT/'.venv/bin/python'),'-u',str(DRIVER)],cwd=ROOT,check=True)
if __name__=='__main__':
    try:go()
    except Exception as e:
        print('SAFE STOP:',e,file=sys.stderr)
        sys.exit(2)
