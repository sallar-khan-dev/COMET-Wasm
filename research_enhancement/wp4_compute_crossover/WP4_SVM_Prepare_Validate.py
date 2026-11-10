#!/usr/bin/env python3
"""Prepare, compile and parity-gate three genuine scaled RBF SVM variants.
Run with .venv/bin/python from the COMET-Wasm repository root.
Does not launch performance experiments or modify baseline artifacts.
"""
import hashlib
import json
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import numpy as np
from sklearn.datasets import load_breast_cancer
from sklearn.metrics import accuracy_score, precision_recall_fscore_support
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVC

ROOT = Path('/home/sallar/wasiMultitenant')
BASE = ROOT / 'research_enhancement/wp4_compute_crossover'
MODEL_BASE = ROOT / 'models/wp4_scaled/svm'
VARIANTS = [('svm_c_0p03', 0.03), ('svm_c_0p1', 0.1), ('svm_c_0p3', 0.3)]
RUNNER = ROOT / 'research_enhancement/v2_parity/all_models_wasmtime_runner/target/release/comet-all-parity'


def run(args, **kwargs):
    print('RUN:', ' '.join(map(str, args)), flush=True)
    return subprocess.run(list(map(str, args)), check=True, cwd=ROOT, **kwargs)


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def write_checked(path, contents):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        require(path.read_text() == contents, f'Existing file differs, refusing overwrite: {path}')
    else:
        path.write_text(contents)


def golden_prediction(model, features):
    # Independent float32 traversal: same evaluation order as existing SVM reference.
    f = np.float32
    x = np.asarray(features, dtype=np.float32)
    mean = np.asarray(model['mean'], dtype=np.float32)
    scale = np.asarray(model['scale'], dtype=np.float32)
    svs = np.asarray(model['support_vectors'], dtype=np.float32)
    coefs = np.asarray(model['dual_coef'], dtype=np.float32)
    gamma = f(model['gamma'])
    decision = f(model['intercept'])
    for i in range(len(svs)):
        distance = f(0.0)
        for j in range(30):
            standardized = f(f(x[j] - mean[j]) / scale[j])
            diff = f(standardized - svs[i, j])
            distance = f(distance + f(diff * diff))
        kernel = f(np.exp(f(-f(gamma * distance))))
        decision = f(decision + f(coefs[i] * kernel))
    return 1 if decision > 0 else 0


def docker_parity(image, records):
    name = 'comet_wp4_svm_parity_' + uuid.uuid4().hex[:12]
    started = False
    try:
        run(['docker', 'run', '-d', '--name', name, '-p', '127.0.0.1::8085', image], stdout=subprocess.DEVNULL)
        started = True
        port_out = subprocess.check_output(['docker', 'port', name, '8085/tcp'], text=True).strip()
        port = int(port_out.rsplit(':', 1)[-1])
        url = f'http://127.0.0.1:{port}/infer'
        matched, errors, examples = 0, 0, []
        for index, record in enumerate(records):
            payload = json.dumps({'features': record['features']}).encode()
            response = None
            for attempt in range(40 if index == 0 else 1):
                try:
                    req = urllib.request.Request(url, data=payload, headers={'Content-Type': 'application/json'}, method='POST')
                    with urllib.request.urlopen(req, timeout=10) as result:
                        response = json.loads(result.read())
                    break
                except Exception as exc:
                    if index == 0 and attempt < 39:
                        time.sleep(.25)
                    else:
                        errors += 1
                        if len(examples) < 25:
                            examples.append({'id': record['id'], 'error': str(exc)})
            if response is None:
                continue
            got = int(response['prediction'])
            if got == record['prediction']:
                matched += 1
            elif len(examples) < 25:
                examples.append({'id': record['id'], 'expected': record['prediction'], 'actual': got})
        return {'status': 'PASS' if matched == len(records) and not errors else 'FAIL',
                'records': len(records), 'matched': matched,
                'mismatches': len(records) - matched - errors, 'errors': errors,
                'examples': examples, 'image': image}
    finally:
        if started:
            subprocess.run(['docker', 'rm', '-f', name], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    require(Path.cwd().resolve() == ROOT, f'Run from {ROOT}')
    require(RUNNER.is_file(), 'Existing Wasmtime parity binary missing')
    require((BASE / 'run_mlp_64_wasmtime.py').is_file(), 'WP4 reference measurement runner missing')
    require(shutil.which('docker') is not None, 'Docker unavailable')
    require(shutil.which('cargo') is not None, 'Cargo unavailable')
    for side, generator in [('wasm', ROOT / 'wasm/tenant_svm_real/generate_svm_lib.py'),
                            ('docker', ROOT / 'docker/svm_server/generate_main.py')]:
        require(generator.is_file(), f'Existing SVM generator missing: {generator}')

    data = load_breast_cancer()
    X = data.data.astype(float)
    y = data.target.astype(int)
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=.30, random_state=42, stratify=y)
    scaler = StandardScaler().fit(Xtr)
    feature_names = [str(n).replace(' ', '_').replace('(', '').replace(')', '') for n in data.feature_names]

    for name, c in VARIANTS:
        print(f'\n==== {name} (C={c}) ====', flush=True)
        clf = SVC(kernel='rbf', gamma='scale', C=c, probability=False, random_state=42)
        clf.fit(scaler.transform(Xtr), ytr)
        pred = clf.predict(scaler.transform(Xte))
        precision, recall, f1, _ = precision_recall_fscore_support(yte, pred, average='binary', zero_division=0)
        count = int(len(clf.support_vectors_))
        require(count > 91, f'{name}: support vectors did not exceed original 91')
        model = {
            'model': 'SVM_RBF', 'dataset': 'breast_cancer', 'task': 'binary_classification',
            'feature_names': feature_names, 'classes': clf.classes_.astype(int).tolist(),
            'mean': scaler.mean_.astype(float).tolist(), 'scale': scaler.scale_.astype(float).tolist(),
            'support_vectors': clf.support_vectors_.astype(float).tolist(),
            'dual_coef': clf.dual_coef_[0].astype(float).tolist(),
            'intercept': float(clf.intercept_[0]), 'gamma': float(clf._gamma),
            'n_support': clf.n_support_.astype(int).tolist(), 'n_support_total': count,
            'metrics': {'accuracy': float(accuracy_score(yte, pred)), 'precision': float(precision),
                        'recall': float(recall), 'f1': float(f1)},
            'profile_hint': {'compute_class': 'kernel_compute_heavy', 'memory_class': 'medium_high',
                             'complexity': 'O(support_vectors*d)', 'features': 30,
                             'support_vectors': count, 'train_samples': len(Xtr),
                             'test_samples': len(Xte), 'regularization_C': c,
                             'training_split_seed': 42},
        }
        model_path = MODEL_BASE / name / 'model.json'
        write_checked(model_path, json.dumps(model, indent=2) + '\n')
        print(f'Trained: {count} support vectors; held-out accuracy={model["metrics"]["accuracy"]:.4f}', flush=True)
        variant_dir = BASE / 'generated' / name
        for side, orig in [('wasm', ROOT / 'wasm/tenant_svm_real'),
                           ('docker', ROOT / 'docker/svm_server')]:
            target = variant_dir / side
            (target / "src").mkdir(parents=True, exist_ok=True)
            gen_file = 'generate_svm_lib.py' if side == 'wasm' else 'generate_main.py'
            source = (orig / gen_file).read_text()
            original_path = 'models/svm/breast_cancer/model.json'
            require(source.count(original_path) == 1, f'Generator model path unexpectedly changed: {orig}')
            require(source.count('Path(__file__).resolve().parents[2]') == 1,
                    f'Generator project root assumption changed: {orig}')
            source = source.replace(original_path, f'models/wp4_scaled/svm/{name}/model.json')
            source = source.replace('Path(__file__).resolve().parents[2]', 'Path("/home/sallar/wasiMultitenant")')
            write_checked(target / gen_file, source)
            for item in ('Cargo.toml', 'Cargo.lock', 'Dockerfile'):
                if (orig / item).is_file():
                    write_checked(target / item, (orig / item).read_text())
            run([sys.executable, target / gen_file])

        wasm_dir = variant_dir / 'wasm'
        run(['cargo', 'build', '--release', '--target', 'wasm32-unknown-unknown', '--manifest-path', wasm_dir / 'Cargo.toml'])
        wasm_artifact = wasm_dir / 'target/wasm32-unknown-unknown/release/tenant_svm_real.wasm'
        require(wasm_artifact.is_file(), f'Wasm build missing: {wasm_artifact}')
        image = f'comet-wp4-{name.replace("_", "-")}:latest'
        run(['docker', 'build', '-t', image, variant_dir / 'docker'])

        records = [{'id': i, 'features': [float(f) for f in np.asarray(features, dtype=np.float32)],
                    'prediction': golden_prediction(model, features)}
                   for i, features in enumerate(X)]
        assert len(records) == 569
        reports = BASE / 'validation'
        reports.mkdir(parents=True, exist_ok=True)
        golden = reports / f'{name}_golden.json'
        write_checked(golden, json.dumps({
            'model': name, 'reference_method': 'independent_numpy_float32_rbf',
            'model_sha256': hashlib.sha256(model_path.read_bytes()).hexdigest(),
            'n_support_vectors': count, 'n_records': 569, 'records': records
        }, indent=2) + '\n')
        wasm_report = reports / f'{name}_wasmtime.json'
        require(not wasm_report.exists(), f'Existing Wasmtime report: {wasm_report}')
        run([RUNNER, wasm_artifact, golden, wasm_report])
        wasmtime = json.loads(wasm_report.read_text())
        docker = docker_parity(image, records)
        docker_report = reports / f'{name}_docker.json'
        require(not docker_report.exists(), f'Existing Docker report: {docker_report}')
        docker_report.write_text(json.dumps(docker, indent=2) + '\n')
        print(f'{name} Wasmtime: {wasmtime["matched"]}/569; Docker: {docker["matched"]}/569', flush=True)
        require(wasmtime['status'] == 'PASS' and docker['status'] == 'PASS',
                f'Parity failed for {name}. Do NOT start performance runs.')

    print('\nWP4 SVM PREPARATION AND ALL SIX PARITY CHECKS PASSED', flush=True)


if __name__ == '__main__':
    main()
