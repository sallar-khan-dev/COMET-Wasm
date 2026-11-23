#!/usr/bin/env python3
"""COMET-Wasm WP3 *diagnostic* cold startup / functional HTTP readiness pilot.

Does NOT claim the supervisor's final common-ingress, symmetric /health experiment:
Docker model servers expose POST /infer, not GET /health. Both treatments use
first and all-tenant golden-verified /infer readiness, with direct endpoints.

Requires the exact pinned WP2 Wasmtime executable, Wasm artifacts and Docker
images. Cold = launch a new N-instance Wasmtime process vs N independent Docker
containers; record first valid inference and all N tenants responsive. Different
cold deployment topologies are intentionally labelled, not equated. No scheduler
changes or new heavy models. Runs all seven current reference models. Checkpoints every successful treatment, records
retries, preserves failures, never silently excludes correctness failures.
"""
import argparse
import csv
import datetime as dt
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import COMET_WP2_LR_Controlled_Density as lr
import COMET_WP2_Remaining_Six_Controlled_Density as six

BASE = ROOT / 'research_enhancement/automated_supervisor_workplan'
OUT = BASE / 'wp3_cold_http_ready_seven_models_20261123'
LEVELS = (1, 20, 50)
MODELS = ('logistic_regression', 'naive_bayes', 'decision_tree', 'kmeans', 'random_forest', 'svm', 'mlp')
BACKENDS = ('wasmtime', 'docker')
MIN_REPS = 20
MAX_REPS = 60
MAX_ATTEMPTS = 3
FIELDS = ('model', 'backend', 'tenants', 'rep', 'first_valid_ms',
          'all_ready_ms', 'total_threads', 'max_threads', 'cpu',
          'image_id', 'utc')
FAIL_FIELDS = ('utc', 'model', 'backend', 'tenants', 'rep', 'attempt', 'error')


def emit(*items):
    print(*items, flush=True)


def require(cond, msg):
    if not cond:
        raise RuntimeError('SAFE STOP: ' + msg)


def sha(path):
    h = hashlib.sha256()
    with open(path, 'rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def append_row(path, fields, row):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        if handle.tell() == 0:
            writer.writeheader()
        writer.writerow(row)
        handle.flush()
        os.fsync(handle.fileno())


def read_rows(path):
    if not path.exists():
        return []
    with path.open(newline='') as handle:
        return list(csv.DictReader(handle))


def write_json(path, value):
    part = path.with_suffix(path.suffix + '.tmp')
    part.write_text(json.dumps(value, indent=2) + '\n')
    part.replace(path)


def source_and_gold(model):
    if model == 'logistic_regression':
        wasm = lr.WASM
        gold = lr.GOLD
        image = lr.IMAGE
        iid = lr.run(['docker', 'image', 'inspect', '-f', '{{.Id}}', image], timeout=20)
        records = json.loads(gold.read_text())['records']
        samples = [{'features': record['features'],
                    'expected_prediction': int(record['expected_prediction'])}
                   for record in records]
    else:
        tag, stem, images = six.MODELS[model]
        wasm = ROOT / f'wasm/tenant_{tag}_real/target/wasm32-unknown-unknown/release/tenant_{tag}_real.wasm'
        gold = ROOT / f'research_enhancement/v2_references/{stem}_golden_v1.json'
        image, iid = six.image_for(images)
        samples = six.load_samples(gold)
    require(wasm.is_file() and gold.is_file(), f'{model} Wasm or golden file missing')
    require(iid and str(iid).startswith('sha256:'), f'{model} Docker image missing')
    require(len(samples) >= 20, f'{model} insufficient input trace')
    # Freeze the exact artifacts previously used for the corrected WP2 density
    # treatment; refuse to silently replace a benchmarked Docker image or Wasm.
    density_manifest = ((BASE / 'wp2_lr_controlled_density_20261121') if
                        model == 'logistic_regression' else
                        (BASE / 'wp2_six_models_controlled_density_20261121' / model)) / 'manifest.json'
    require(density_manifest.is_file(), f'Cannot freeze source without WP2 manifest: {density_manifest}')
    frozen = json.loads(density_manifest.read_text())
    require(frozen.get('docker_image_id') == iid,
            f'{model} Docker image changed since WP2: {iid} vs {frozen.get("docker_image_id")}')
    require(frozen.get('wasm_sha256') == sha(wasm),
            f'{model} Wasm module changed since WP2')
    require(frozen.get('golden_sha256') == sha(gold),
            f'{model} reference trace changed since WP2')
    require(frozen.get('cpu') == lr.CPU,
            f'{model} pinned CPU changed since WP2')
    return {'model': model, 'wasm': str(wasm), 'golden': str(gold),
            'samples': samples, 'image': str(iid), 'image_tag': str(image),
            'wasm_sha256': sha(wasm), 'golden_sha256': sha(gold)}


def setup():
    require(lr.SERVER.is_file(), f'Missing Wasmtime server {lr.SERVER}')
    require(lr.CPU in os.sched_getaffinity(0), 'Pinned CPU unavailable')
    lr.run(['docker', 'info', '--format', '{{.ServerVersion}}'], timeout=25)
    catalog = {m: source_and_gold(m) for m in MODELS}
    manifest = {
        'study': 'WP3 exploratory cold-deployment/direct-functional-HTTP-readiness',
        'scope_warning': 'NOT final common-gateway equivalence. Docker lacks /health; POST /infer used for both. Wasmtime launches one process/N instances; Docker launches N containers.',
        'models': list(MODELS), 'tenant_densities': list(LEVELS),
        'minimum_reps': MIN_REPS, 'maximum_reps': MAX_REPS,
        'maximum_readiness_retries': MAX_ATTEMPTS,
        'cpu': lr.CPU, 'server_sha256': sha(lr.SERVER),
        'docker_network': 'bridge', 'worker_threads_env': 'TOKIO_WORKER_THREADS=1',
        'docker_memory_limit_per_tenant': '128m', 'docker_pids_limit': 16,
        'measurement': 'perf_counter_ns from just before process/docker-run launch to valid /infer for first tenant, and until all N tenants return reference-equivalent responses',
        'models_frozen': {k: {field: v for field, v in spec.items()
                              if field not in ('samples', 'wasm', 'golden')}
                          for k, spec in catalog.items()},
        'golden_records': {k: len(spec['samples']) for k, spec in catalog.items()},
        'not_poolable_with_other_startup_campaigns': True,
        'precision_policy': 'Minimum 20 and maximum 60 per backend-condition; require 95% Student-t and bootstrap relative CI <=2.5% for both first-valid and all-ready timings before early stopping; report misses at 60 and proceed'
    }
    return catalog, manifest


def python_ready(url, features, expected, seconds=60):
    return lr.ready(url, features, expected, seconds)


def proc_cpu_affinity(pid):
    status = Path(f'/proc/{pid}/status').read_text()
    for line in status.splitlines():
        if line.startswith('Cpus_allowed_list:'):
            return line.split(':', 1)[1].strip()
    return 'unknown'


def wasmtime_cold(spec, n, rep, attempt):
    port = lr.freeport()
    env = dict(os.environ, TOKIO_WORKER_THREADS='1')
    start = time.perf_counter_ns()
    proc = subprocess.Popen(['taskset', '-c', str(lr.CPU), str(lr.SERVER),
                            spec['model'], spec['wasm'], str(n), str(port)],
                            cwd=ROOT, env=env, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
    try:
        url = f'http://127.0.0.1:{port}/infer'
        inputs = spec['samples']
        for tenant in range(n):
            sample = inputs[(rep + tenant) % len(inputs)]
            r = python_ready(url, {'tenant_id': tenant, 'features': sample['features']},
                             sample['expected_prediction'])
            require(int(r['worker_id']) == tenant, f'Wasm wrong tenant {tenant}')
            if tenant == 0:
                first = time.perf_counter_ns()
        finish = time.perf_counter_ns()
        for tenant in range(n):
            sample = inputs[(rep + tenant + 7) % len(inputs)]
            response = lr.http(url, {'tenant_id': tenant, 'features': sample['features']})
            require(int(response['prediction']) == sample['expected_prediction'],
                    f'Wasm second varied input mismatch, tenant {tenant}')
        require(proc_cpu_affinity(proc.pid) == str(lr.CPU), 'Wasm CPU affinity mismatch')
        threads = lr.threads(proc.pid)
        return ((first - start) / 1e6, (finish - start) / 1e6,
                threads, threads, 'N/A')
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


def docker_cold(spec, n, rep, attempt):
    names = []
    try:
        start = time.perf_counter_ns()
        for tenant in range(n):
            name = f'cometwp3cold_{os.getpid()}_{spec["model"]}_{n}_{rep}_{attempt}_{tenant}'
            lr.run(['docker', 'run', '-d', '--name', name,
                    '--network', 'bridge', '--cpuset-cpus', str(lr.CPU),
                    '--pids-limit', '16', '--memory', '128m',
                    '-e', 'TOKIO_WORKER_THREADS=1',
                    '-p', '127.0.0.1::8085', spec['image']], timeout=90)
            names.append(name)
        inputs = spec['samples']
        pids = []
        for tenant, name in enumerate(names):
            port = lr.run(['docker', 'port', name, '8085/tcp'], timeout=25).rsplit(':', 1)[-1]
            sample = inputs[(rep + tenant) % len(inputs)]
            url = f'http://127.0.0.1:{port}/infer'
            python_ready(url, {'features': sample['features']}, sample['expected_prediction'])
            if tenant == 0:
                first = time.perf_counter_ns()
            pid = int(lr.run(['docker', 'inspect', '-f', '{{.State.Pid}}', name], timeout=25))
            require(pid > 0 and proc_cpu_affinity(pid) == str(lr.CPU),
                    f'Docker {tenant} CPU affinity mismatch')
            pids.append(pid)
        finish = time.perf_counter_ns()
        for tenant, name in enumerate(names):
            port = lr.run(['docker', 'port', name, '8085/tcp'], timeout=25).rsplit(':', 1)[-1]
            sample = inputs[(rep + tenant + 7) % len(inputs)]
            r = lr.http(f'http://127.0.0.1:{port}/infer', {'features': sample['features']})
            require(int(r['prediction']) == sample['expected_prediction'],
                    f'Docker second varied input mismatch, tenant {tenant}')
        tcounts = [lr.threads(pid) for pid in pids]
        return ((first - start) / 1e6, (finish - start) / 1e6,
                sum(tcounts), max(tcounts), spec['image'])
    finally:
        for name in reversed(names):
            lr.run(['docker', 'rm', '-f', name], timeout=35, check=False)


def ci(rows, model, backend, n, field):
    vals = [float(r[field]) for r in rows if r['model'] == model and
            r['backend'] == backend and int(r['tenants']) == n]
    if len(vals) < 2:
        return {'n': len(vals), 'accepted': False}
    result = lr.precision(vals)
    result['mean_ms'] = result.pop('mean_pss_mib')
    return result


def run_all(catalog):
    OUT.mkdir(parents=True, exist_ok=True)
    raw = OUT / 'trials.csv'
    rows = read_rows(raw)
    seen = {(r['model'], r['backend'], int(r['tenants']), int(r['rep'])) for r in rows}
    require(len(seen) == len(rows), 'Duplicate existing WP3 trial keys')
    for m in MODELS:
        for n in LEVELS:
            for rep in range(1, MAX_REPS + 1):
                # Require both timing endpoints to meet both 95% CI checks
                # before early stopping. At 60, retain all misses and advance.
                statuses = {
                    backend: {
                        metric: ci(rows, m, backend, n, metric)
                        for metric in ('first_valid_ms', 'all_ready_ms')
                    }
                    for backend in BACKENDS
                }
                backend_precise = {
                    backend: all(s.get('accepted', False) for s in metrics.values())
                    for backend, metrics in statuses.items()
                }
                if rep > MIN_REPS and all(backend_precise.values()):
                    break
                order = BACKENDS if rep % 2 else BACKENDS[::-1]
                for backend in order:
                    key = (m, backend, n, rep)
                    if key in seen or (rep > MIN_REPS and backend_precise[backend]):
                        continue
                    available = int(next(line.split()[1] for line in Path('/proc/meminfo').read_text().splitlines()
                                         if line.startswith('MemAvailable:')))
                    require(available > 4_000_000, 'Available memory below 4 GiB; stop before new trial')
                    for attempt in range(1, MAX_ATTEMPTS + 1):
                        try:
                            fn = wasmtime_cold if backend == 'wasmtime' else docker_cold
                            measured = fn(catalog[m], n, rep, attempt)
                            break
                        except RuntimeError as exc:
                            if 'Readiness failed:' not in str(exc):
                                raise
                            append_row(OUT / 'readiness_failures.csv', FAIL_FIELDS, {
                                'utc': dt.datetime.now(dt.timezone.utc).isoformat(),
                                'model': m, 'backend': backend, 'tenants': n,
                                'rep': rep, 'attempt': attempt, 'error': str(exc)[:500]})
                            emit('READINESS FAILURE', m, backend, 'N=', n,
                                 'REP=', rep, 'ATTEMPT=', f'{attempt}/{MAX_ATTEMPTS}', exc)
                            if attempt == MAX_ATTEMPTS:
                                raise
                            time.sleep(attempt * 10)
                    first, all_ready, total_threads, max_threads, image = measured
                    require(math.isfinite(all_ready) and 0 < first <= all_ready,
                            'Invalid cold-readiness clock')
                    item = dict(zip(FIELDS, (m, backend, n, rep, first, all_ready,
                                             total_threads, max_threads, lr.CPU, image,
                                             dt.datetime.now(dt.timezone.utc).isoformat())))
                    append_row(raw, FIELDS, item)
                    rows.append(item)
                    seen.add(key)
                if rep >= MIN_REPS and (rep == MIN_REPS or rep % 5 == 0):
                    status = {b: {metric: ci(rows, m, b, n, metric)
                                  for metric in ('first_valid_ms', 'all_ready_ms')}
                              for b in BACKENDS}
                    emit('WP3 PROGRESS', m, 'N=', n, 'REP=', rep,
                         ' | '.join(f'{b} ' + ' '.join(
                            f'{metric}: n={v.get("n", 0)} t={v.get("student_t_pct", float("nan")):.2f}% '
                            f'boot={v.get("bootstrap_pct", float("nan")):.2f}% pass={v.get("accepted", False)}'
                            for metric, v in status[b].items()) for b in BACKENDS))
            # Never refuse to advance merely because the statistical target failed.
            results = {'scope': 'DIRECT_ENDPOINT_DIAGNOSTIC_NOT_COMMON_GATEWAY',
                       'precision_threshold_pct': 2.5,
                       'results': {model: {str(level): {
                           b: {field: ci(rows, model, b, level, field)
                               for field in ('first_valid_ms', 'all_ready_ms')}
                           for b in BACKENDS}
                           for level in LEVELS} for model in MODELS}}
            write_json(OUT / 'RESULT.json', results)
            emit('WP3 LEVEL COMPLETE', m, n, '(CI misses retained and explicitly flagged)')
    allrows = read_rows(raw)
    require(len(allrows) >= len(MODELS) * len(LEVELS) * len(BACKENDS) * MIN_REPS,
            'Missing required minimum trial count')
    (OUT / 'COMPLETE.txt').write_text('WP3 exploratory cold/readiness measurements collected; see precision status and scope warning in RESULT.json.\n')
    emit('WP3 DIAGNOSTIC COMPLETE; precision misses and retries are in the reports')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--preflight', action='store_true')
    args = parser.parse_args()
    catalog, manifest = setup()
    emit('PREFLIGHT: frozen artifacts, Docker images, and CPU available',
         'models=', list(catalog), 'CPU=', lr.CPU)
    if args.preflight:
        return
    OUT.mkdir(parents=True, exist_ok=True)
    manifest_path = OUT / 'manifest.json'
    if manifest_path.exists():
        require(json.loads(manifest_path.read_text()) == manifest,
                'Manifest differs from existing pilot: do not pool unrelated trials')
    else:
        write_json(manifest_path, manifest)
    with (OUT / '.single_runner.lock').open('a+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another WP3 pilot is already active')
        run_all(catalog)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('SAFE STOP:', repr(exc), flush=True)
        raise SystemExit(2)
