#!/usr/bin/env python3
"""WP2 six-model continuation of the existing controlled LR memory-density protocol.

Schedule in a separate tmux session. This waits for the LR run's advisory flock,
requires completion of all LR densities (with CI failures flagged), then runs NB, DT,
K-Means, RF, SVM, MLP sequentially using the same base helpers/statistics.
Never edits historical outputs, changes runtime sources, builds images or alters
unowned Docker containers. Each model has its own checkpointed result directory.
"""
import argparse
import csv
import fcntl
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path('/home/sallar/wasiMultitenant')
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import COMET_WP2_LR_Controlled_Density as lr

BASE = ROOT / 'research_enhancement/automated_supervisor_workplan'
LR_DIR = BASE / 'wp2_lr_controlled_density_20261121'
OUT = BASE / 'wp2_six_models_controlled_density_20261121'
LEVELS = [1, 5, 10, 20, 50, 100, 200]
MIN_REPS, MAX_REPS = 20, 40
MODELS = {
    'naive_bayes': ('nb', 'nb_breast_cancer', ('comet-nb-docker:v1', 'comet-wp1-nb:latest')),
    'decision_tree': ('dt', 'dt_breast_cancer', ('comet-dt-docker:v1', 'comet-wp1-dt:latest')),
    'kmeans': ('kmeans', 'kmeans_iris', ('comet-kmeans-docker:v1', 'comet-wp1-kmeans:latest')),
    'random_forest': ('rf', 'rf_breast_cancer', ('comet-rf-docker:v1', 'comet-wp1-rf:latest')),
    'svm': ('svm', 'svm_breast_cancer', ('comet-svm-docker:v1', 'comet-wp1-svm:latest')),
    'mlp': ('mlp', 'mlp_breast_cancer', ('comet-mlp-docker:v1', 'comet-wp1-mlp:latest')),
}
FIELDS = lr.FIELDS


def require(ok, message):
    if not ok:
        raise RuntimeError('SAFE STOP: ' + message)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_samples(gold_path):
    data = json.loads(gold_path.read_text())
    records = data['records']
    require(len(records) >= 20, f'Insufficient golden records in {gold_path}')
    samples = []
    for i, rec in enumerate(records):
        prediction = rec.get('expected_prediction', rec.get('prediction'))
        require(prediction is not None, f'Golden row {i} has no prediction: {gold_path}')
        vals = rec.get('features')
        require(isinstance(vals, list) and len(vals) in (4, 30),
                f'Golden feature vector invalid in {gold_path} at {i}')
        samples.append({'features': vals, 'expected_prediction': int(prediction)})
    return samples


def image_for(candidates):
    for name in candidates:
        result = lr.run(['docker', 'image', 'inspect', '-f', '{{.Id}}', name],
                        timeout=20, check=False)
        if result.startswith('sha256:'):
            return name, result
    return None, None


def preflight():
    require(lr.SERVER.is_file(), f'Missing compiled multitenant Wasmtime server: {lr.SERVER}')
    require((ROOT / 'COMET_WP2_LR_Controlled_Density.py').is_file(),
            'Original controlled LR experiment script missing')
    lr.run(['docker', 'info', '--format', '{{.ServerVersion}}'], timeout=20)
    available = sorted(os.sched_getaffinity(0))
    require(lr.CPU == min(available), 'Runner CPU selection differs from LR script')
    plan = {}
    for model, (tag, golden_stem, images) in MODELS.items():
        wasm = ROOT / (f'wasm/tenant_{tag}_real/target/'
                       f'wasm32-unknown-unknown/release/tenant_{tag}_real.wasm')
        golden = ROOT / f'research_enhancement/v2_references/{golden_stem}_golden_v1.json'
        require(wasm.is_file() and golden.is_file(), f'Missing Wasm/golden artifact for {model}')
        samples = load_samples(golden)
        image_name, image_id = image_for(images)
        require(image_id, f'No matching installed Docker image for {model}; tried {images}')
        plan[model] = {
            'wasm': str(wasm), 'golden': str(golden), 'samples': samples,
            'image_tag': image_name, 'image_id': image_id,
            'wasm_sha256': sha(wasm), 'golden_sha256': sha(golden),
        }
        print(f'PREFLIGHT {model}: WASM=OK GOLDEN={len(samples)} IMAGE={image_name} ID={image_id[:24]}', flush=True)
    return plan


def validate_lr():
    """Do not start other loads until LR has truly completed all seven levels."""
    lock = LR_DIR / '.single_runner.lock'
    require(lock.is_file(), f'LR lock missing: {lock}')
    print('WAITING FOR CONTROLLED LR RUN TO RELEASE ITS LOCK...', flush=True)
    with lock.open('r') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)  # waits, no CPU-intensive polling
        print('LR LOCK RELEASED. VERIFYING FULL LR COMPLETION...', flush=True)
        report_path = LR_DIR / 'RESULT.json'
        require(report_path.is_file(), f'LR result missing: {report_path}')
        report = json.loads(report_path.read_text())
        precision = report.get('precision_by_density', {})
        failures = []
        for n in LEVELS:
            for b in ('wasmtime', 'docker'):
                val = precision.get(str(n), {}).get(b, {})
                if not (val.get('accepted') and val.get('n', 0) >= MIN_REPS
                        and val.get('student_t_pct', 1e9) <= 2.5
                        and val.get('bootstrap_pct', 1e9) <= 2.5):
                    failures.append(f'N={n}/{b}:{val}')
        require(all(precision.get(str(n), {}).get(b, {}).get('n', 0) >= MIN_REPS
                for n in LEVELS for b in ('wasmtime','docker')),
            f'LR incomplete. Do not start another campaign: {failures[:4]}')
    log_path = BASE / 'wp2_lr_density.log'
    require(log_path.is_file() and 'FINAL: WP2 LR CONTROLLED DENSITY CAMPAIGN COMPLETE' in log_path.read_text(),
            'LR run did not complete cleanly (no final log marker)')
    if failures:
        print('LR FINISHED WITH UNACCEPTED CI CELLS:', len(failures), failures[:4], flush=True)
    else:
        print('LR FULL 7-LEVEL DENSITY PRECISION VERIFIED.', flush=True)
    print('STARTING REMAINING SIX.', flush=True)


def wasm_measure(model, n, rep, samples, wasm):
    port = lr.freeport()
    env = dict(os.environ, TOKIO_WORKER_THREADS='1')
    process = __import__('subprocess').Popen([
        'taskset', '-c', str(lr.CPU), str(lr.SERVER), model, str(wasm), str(n), str(port)
    ], cwd=ROOT, env=env, stdout=__import__('subprocess').DEVNULL,
        stderr=__import__('subprocess').DEVNULL)
    try:
        url = f'http://127.0.0.1:{port}/infer'
        for tenant in range(n):
            first = samples[(rep + tenant) % len(samples)]
            result = lr.ready(url, {'tenant_id': tenant, 'features': first['features']},
                              first['expected_prediction'], 60)
            require(result['worker_id'] == tenant, f'{model} wrong Wasm instance assignment')
            second = samples[(rep + tenant + 7) % len(samples)]
            result = lr.http(url, {'tenant_id': tenant, 'features': second['features']})
            require(int(result['prediction']) == second['expected_prediction'],
                    f'{model} varied Wasm prediction mismatch')
        memory = []
        for _ in range(3):
            memory.append(lr.mem(Path(f'/proc/{process.pid}/smaps_rollup').read_text()))
            time.sleep(.15)
        vals = np.mean(memory, axis=0).tolist()
        threads = lr.threads(process.pid)
        return ['wasmtime', n, rep, *vals, threads, threads, lr.CPU, 'N/A']
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=8)
            except __import__('subprocess').TimeoutExpired:
                process.kill()
                process.wait()


def docker_measure(model, n, rep, samples, image_id):
    names = []
    try:
        for tenant in range(n):
            name = f'cometwp2six_{os.getpid()}_{model}_{rep}_{n}_{tenant}'
            lr.run(['docker','run','-d','--name',name,'--network','bridge',
                    '--cpuset-cpus',str(lr.CPU),'--pids-limit','16',
                    '--memory','128m','-e','TOKIO_WORKER_THREADS=1',
                    '-p','127.0.0.1::8085',image_id], timeout=75)
            names.append(name)
        pids = []
        for tenant, name in enumerate(names):
            port = lr.run(['docker','port',name,'8085/tcp']).rsplit(':', 1)[-1]
            url = f'http://127.0.0.1:{port}/infer'
            first = samples[(rep + tenant) % len(samples)]
            lr.ready(url, {'features': first['features']}, first['expected_prediction'], 60)
            second = samples[(rep + tenant + 7) % len(samples)]
            result = lr.http(url, {'features': second['features']})
            require(int(result['prediction']) == second['expected_prediction'],
                    f'{model} varied Docker prediction mismatch')
            pids.append(int(lr.run(['docker','inspect','-f','{{.State.Pid}}',name])))
        totals = []
        for _ in range(3):
            mm = [lr.mem(lr.run(['docker','exec','-u','0',name,
                                 'cat','/proc/1/smaps_rollup'],timeout=20)) for name in names]
            totals.append(np.sum(mm, axis=0).tolist())
            time.sleep(.15)
        vals = np.mean(totals, axis=0).tolist()
        threads = [lr.threads(pid) for pid in pids]
        return ['docker', n, rep, *vals, sum(threads), max(threads), lr.CPU, image_id]
    finally:
        for name in reversed(names):
            lr.run(['docker', 'rm', '-f', name], timeout=30, check=False)


def save_json(path, obj):
    path.write_text(json.dumps(obj, indent=2) + '\n')


def precision(rows, n, backend):
    xs = [float(row['pss_mib']) for row in rows
          if int(row['tenants']) == n and row['backend'] == backend]
    return lr.precision(xs)


def run_model(model, info):
    folder = OUT / model
    folder.mkdir(parents=True, exist_ok=True)
    artifact = Path(info['wasm'])
    samples = info['samples']
    manifest = {
        'model': model, 'levels': LEVELS, 'cpu': lr.CPU,
        'minimum_reps': MIN_REPS, 'maximum_reps': MAX_REPS,
        'thread_policy': 'TOKIO_WORKER_THREADS=1; Wasmtime and Docker pinned to same CPU',
        'wasm_sha256': info['wasm_sha256'], 'golden_sha256': info['golden_sha256'],
        'docker_image_id': info['image_id'], 'docker_network': 'bridge',
        'scope': 'Total application PSS only; excludes Docker helper ownership and base/model separation',
        'measurement': 'Three /proc/smaps_rollup samples per independent launched serving configuration',
        'resource_limits': {'per_docker_container_memory': '128m', 'per_docker_container_pids': 16},
        'repetition_independence': 'New Wasm serving process, new N Docker containers per rep',
        'historical_experiments_not_pooled': True,
    }
    mf = folder / 'manifest.json'
    if mf.exists():
        require(json.loads(mf.read_text()) == manifest,
                f'Manifest/source/image changed since earlier {model} measurements')
    else:
        save_json(mf, manifest)
    raw = folder / 'trials.csv'
    with raw.open(newline='') if raw.exists() else open(os.devnull) as handle:
        rows = list(csv.DictReader(handle)) if raw.exists() else []
    seen = {(r['backend'], int(r['tenants']), int(r['rep'])) for r in rows}
    require(len(seen) == len(rows), f'Duplicate {model} raw repetitions')
    print(f'MODEL START {model}; existing rows={len(rows)}', flush=True)
    for n in LEVELS:
        for rep in range(1, MAX_REPS+1):
            status = {b:precision(rows,n,b) for b in ('wasmtime','docker')}
            if rep > MIN_REPS and all(s['accepted'] for s in status.values()):
                break
            for backend in (('wasmtime','docker') if rep % 2 else ('docker','wasmtime')):
                if (backend,n,rep) in seen:
                    continue
                if rep > MIN_REPS and status[backend]['accepted']:
                    continue
                mem_available = next(int(x.split()[1]) for x in Path('/proc/meminfo').read_text().splitlines()
                                     if x.startswith('MemAvailable:'))
                require(mem_available > 2_000_000,
                        f'{model} N={n} memory available <2 GiB; preserving previous evidence')
                measured = (wasm_measure(model,n,rep,samples,artifact) if backend == 'wasmtime'
                            else docker_measure(model,n,rep,samples,info['image_id']))
                item = dict(zip(FIELDS, measured))
                with raw.open('a', newline='') as handle:
                    writer = csv.DictWriter(handle,fieldnames=FIELDS)
                    if handle.tell() == 0: writer.writeheader()
                    writer.writerow(item)
                    handle.flush()
                    os.fsync(handle.fileno())
                rows.append(item)
                seen.add((backend,n,rep))
            if rep >= MIN_REPS and (rep == MIN_REPS or rep % 5 == 0):
                status = {b:precision(rows,n,b) for b in ('wasmtime','docker')}
                save_json(folder / 'progress.json', {'model':model,'tenants':n,'repetition':rep,'precision':status})
                print('PROGRESS',model,'N=',n,'REP=',rep,' | '.join(
                    f"{b}: n={s.get('n',0)} t={s.get('student_t_pct',float('inf')):.2f}% "
                    f"boot={s.get('bootstrap_pct',float('inf')):.2f}% pass={s['accepted']}"
                    for b,s in status.items()),flush=True)
        results = {str(level):{b:precision(rows,level,b) for b in ('wasmtime','docker')}
                   for level in LEVELS}
        save_json(folder/'RESULT.json', {'model':model,'precision_by_density':results,
                                        'all_accepted':all(s['accepted'] for v in results.values() for s in v.values())})
        print('LEVEL COMPLETE',model,'N=',n,flush=True)
    final = json.loads((folder/'RESULT.json').read_text())
    accepted = sum(s['accepted'] for v in final['precision_by_density'].values() for s in v.values())
    print('MODEL DATA COLLECTED:', model, f'{accepted}/14 backend-density PSS precision conditions accepted',flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preflight', action='store_true', help='Check available artifacts/images only; do not run')
    args = parser.parse_args()
    print('WP2 six-model controlled density: starting preflight',flush=True)
    info = preflight()
    if args.preflight:
        print('PREFLIGHT PASS: all six models have Wasm, golden oracle and Docker images',flush=True)
        return
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT/'.single_runner.lock').open('w') as file:
        try:
            fcntl.flock(file, fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another six-model density campaign is already active')
        validate_lr()
        summary = {}
        for model, artifact in info.items():
            run_model(model, artifact)
            result = json.loads((OUT/model/'RESULT.json').read_text())
            summary[model] = {
                'accepted_cells': sum(s['accepted'] for v in result['precision_by_density'].values() for s in v.values()),
                'total_cells': 14, 'all_accepted': result['all_accepted']
            }
            save_json(OUT/'SUITE_SUMMARY.json', summary)
        (OUT/'COMPLETE.txt').write_text('Six controlled model campaigns finished; inspect CI acceptance in SUITE_SUMMARY.json.\n')
        print('FINAL: SIX-MODEL WP2 CAMPAIGN FINISHED; CI results in SUITE_SUMMARY.json', flush=True)

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('SAFE STOP:',repr(exc),flush=True)
        raise SystemExit(2)
