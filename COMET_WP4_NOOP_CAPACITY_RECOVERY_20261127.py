#!/usr/bin/env python3
"""WP4 §7 no-op calibration repair and checkpoint resume.

Raises only Rust load-generator no-op max_inflight 256 -> 512 (supported
by loadgen), keeping gateway/serving CPU, model sources, offered RPS,
all inference experiment settings, traces, and adaptive 20..60/CI unchanged.
Archives the previous failed no-op calibration instead of deleting it.
"""
from pathlib import Path
import datetime as dt
import importlib.util
import json
import shutil
import subprocess
import sys

ROOT = Path('/home/sallar/wasiMultitenant')
BASE = ROOT / 'COMET_WP4_MLP_SVM_RESUME_20261125.py'
MASTER = ROOT / 'COMET_WP4_SCALED_RF_SVM_GATEWAY_20261126.py'
TARGET = ROOT / 'research_enhancement/reports/wp4_scaled_gateway_adaptive'
MODEL = 'svm_c_0p03'
OLD = "'4800',str(14900/4800),'3000','256',noop]"
NEW = "'4800',str(14900/4800),'3000','512',noop]"


def die(msg):
    raise RuntimeError(msg)


def main():
    if not BASE.is_file() or not MASTER.is_file():
        die('Required current baseline/master source not found')
    source = BASE.read_text()
    if source.count(OLD) != 1 or source.count(NEW) != 0:
        if source.count(NEW) == 1 and source.count(OLD) == 0:
            print('No-op 512 in-flight calibration already in baseline; continuing', flush=True)
            patched = source
        else:
            die('No-op command changed unexpectedly: refusing source modification')
    else:
        patched = source.replace(OLD, NEW, 1)

    spec = importlib.util.spec_from_file_location('comet_wp4_scaled_master', MASTER)
    if spec is None or spec.loader is None:
        die('Cannot read WP4 master script')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # Identify all existing scaled drivers first. Do not modify any file until
    # all have been proven identical to the previously generated source.
    updates = [(BASE, source, patched)]
    for name in module.VARIANTS:
        driver = TARGET / f'runner_{name}.py'
        if not driver.exists():
            continue
        expected_old = module.render_variant(source, module.spec(name))
        expected_new = module.render_variant(patched, module.spec(name))
        current = driver.read_text()
        if current not in (expected_old, expected_new):
            die(f'Generated runner has independent changes, refusing to overwrite: {driver}')
        updates.append((driver, current, expected_new))
    # Do not resume while another WP4 scaled run is already active.
    check = subprocess.run(['pgrep', '-af', 'COMET_WP4_SCALED_RF_SVM_GATEWAY_20261126.py'],
                           capture_output=True, text=True)
    active = [line for line in check.stdout.splitlines()
              if 'python' in line and 'pgrep' not in line and 'sh -c' not in line]
    if active:
        die('WP4 scaled experiment appears active; refusing a concurrent run: ' + '; '.join(active[:2]))

    old_directories = sorted((TARGET / MODEL).glob('*/' + MODEL + '_docker'))
    if not old_directories:
        die('Prior failed SVM Docker calibration directory not found')
    section = old_directories[-1]
    summary = section / 'noop.summary.json'
    if not summary.is_file():
        die('Missing previous no-op summary; cannot confirm the failed calibration')
    no = json.loads(summary.read_text())
    if no.get('offered_requests') != 14900 or no.get('dropped_requests') != 20 or no.get('successful_requests') != 14880:
        die('Existing no-op outcome differs from documented failure; do not archive a new run by accident')
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d_%H%M%S')
    archive = section / ('failed_noop_256_inflight_' + stamp)
    archive.mkdir(parents=True, exist_ok=False)
    for name in ('noop.log', 'noop.summary.json', 'noop.requests.jsonl', 'noop.resources.json'):
        path = section / name
        if path.is_file():
            shutil.move(str(path), str(archive / name))
    (archive / 'WHY_RECALIBRATED.txt').write_text(
        'Observed 4800 RPS no-op: 14880/14900 successes, 20 dropped at max_inflight=256.\n'
        'Headroom FAIL, not accepted. Retry with only no-op client max_inflight=512.\n'
        'Inference max_inflight, serving, requests, precision 20..60 unchanged.\n')
    print('Archived failed no-op calibration:', archive, flush=True)

    # Write recoverable, separate backups before changing baseline or drivers.
    for path, before, after in updates:
        if before == after:
            continue
        backup = path.with_name(path.name + '.pre_noop_capacity_' + stamp + '.bak')
        backup.write_text(before)
        path.write_text(after)
        compile(after, str(path), 'exec')
        print('Changed only no-op max_inflight 256 -> 512:', path, flush=True)
    print('Restarting WP4 scaled master, preserving prior checkpoints and 20..60-repetition precision control', flush=True)
    result = subprocess.run([str(ROOT/'.venv/bin/python'), '-u', str(MASTER)], cwd=ROOT)
    if result.returncode:
        die(f'WP4 STOP: master exited {result.returncode}; original data and no-op archive preserved')
    print('WP4 scaled serving complete; density and crossover analysis still separate requirements', flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('SAFE STOP:', exc, file=sys.stderr, flush=True)
        sys.exit(2)
