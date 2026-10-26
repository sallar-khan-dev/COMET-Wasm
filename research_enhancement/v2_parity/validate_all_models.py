#!/usr/bin/env python3
"""COMET-Wasm V2 seven-model correctness gate. Run from repository root."""
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

import numpy as np

ROOT = Path.cwd()
BASE = ROOT / 'research_enhancement'
REF = BASE / 'v2_references'
PAR = BASE / 'v2_parity'
MODELS = ['lr', 'nb', 'dt', 'kmeans', 'rf', 'svm', 'mlp']
PATHS = {
    'lr': 'models/logistic_regression/iris_lr/model.json',
    'nb': 'models/naive_bayes/breast_cancer/model.json',
    'dt': 'models/decision_tree/breast_cancer/model.json',
    'kmeans': 'models/kmeans/iris/model.json',
    'rf': 'models/random_forest/breast_cancer/model_packed.json',
    'svm': 'models/svm/breast_cancer/model.json',
    'mlp': 'models/mlp/breast_cancer/model.json',
}
REFERENCES = {
    'lr': 'lr_iris_golden_v1.json',
    'kmeans': 'kmeans_iris_golden_v1.json',
    'rf': 'rf_breast_cancer_golden_v1.json',
    'svm': 'svm_breast_cancer_golden_v1.json',
}
F = np.float32


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reference_prediction(name, model, features):
    x = np.asarray(features, dtype=np.float32)
    mean = np.asarray(model['mean'], dtype=np.float32)
    scale = np.asarray(model['scale'], dtype=np.float32)
    assert len(x) == len(mean) == len(scale) == 30 and np.all(scale != 0)
    if name == 'dt':
        node = 0
        for _ in range(len(model['feature']) + 1):
            left = int(model['children_left'][node])
            right = int(model['children_right'][node])
            if left == -1 and right == -1:
                return int(model['leaf_class'][node])
            j = int(model['feature'][node])
            if j < 0:
                return int(model['leaf_class'][node])
            z = F(F(x[j] - mean[j]) / scale[j])
            node = left if z <= F(model['threshold'][node]) else right
            assert 0 <= node < len(model['feature'])
        raise ValueError('DT traversal cycle')
    if name == 'nb':
        priors = np.asarray(model['class_prior'], dtype=np.float32)
        theta = np.asarray(model['theta'], dtype=np.float32)
        var = np.asarray(model['var'], dtype=np.float32)
        assert theta.shape == var.shape == (2, 30) and np.all(var > 0)
        scores = []
        for c in range(2):
            score = F(np.log(priors[c]))
            for j in range(30):
                z = F(F(x[j] - mean[j]) / scale[j])
                diff = F(z - theta[c, j])
                term = F(F(2.0 * np.pi) * var[c, j])
                penalty = F(F(np.log(term)) + F(F(diff * diff) / var[c, j]))
                score = F(score + F(F(-0.5) * penalty))
            scores.append(float(score))
        return int(np.argmax(scores))
    if name == 'mlp':
        weights = model['weights']
        biases = model['biases']
        w1 = np.asarray(weights[0], dtype=np.float32)
        w2 = np.asarray(weights[1], dtype=np.float32)
        b1 = np.asarray(biases[0], dtype=np.float32)
        b2 = np.asarray(biases[1], dtype=np.float32)
        assert w1.shape == (30, 32), f'Unexpected W1 shape {w1.shape}'
        assert b1.shape == (32,), f'Unexpected B1 shape {b1.shape}'
        assert w2.size == 32 and b2.size == 1
        hidden = []
        for h in range(32):
            acc = F(b1[h])
            for j in range(30):
                z = F(F(x[j] - mean[j]) / scale[j])
                acc = F(acc + F(z * w1[j, h]))
            hidden.append(F(max(0.0, float(acc))))
        out = F(b2.ravel()[0])
        for h in range(32):
            out = F(out + F(hidden[h] * w2.ravel()[h]))
        return int(out >= 0)
    raise ValueError(name)


def load_reference(name):
    model_path = ROOT / PATHS[name]
    assert model_path.is_file(), f'Missing model {model_path}'
    if name in REFERENCES:
        path = REF / REFERENCES[name]
        assert path.is_file(), f'Missing golden reference {path}'
        data = json.loads(path.read_text())
        if 'model_sha256' in data:
            assert data['model_sha256'] == sha(model_path), f'Stale model hash for {name}'
        records = []
        for r in data['records']:
            prediction = r.get('expected_prediction', r.get('prediction'))
            assert prediction is not None, f'No prediction in {name} record'
            records.append({'id': r.get('id', r.get('row_index')), 'features': r['features'], 'prediction': int(prediction)})
        return records, {'reference': str(path.relative_to(ROOT)), 'sha256': sha(path), 'method': data.get('reference_method', 'existing golden')}
    model = json.loads(model_path.read_text())
    source = json.loads((REF / 'rf_breast_cancer_golden_v1.json').read_text())
    records = []
    for r in source['records']:
        x = np.asarray(r['features'], dtype=np.float32).astype(float).tolist()
        records.append({'id': r['id'], 'features': x, 'prediction': reference_prediction(name, model, x)})
    assert len(records) == 569
    path = REF / f'{name}_breast_cancer_golden_v1.json'
    data = {'model': model.get('model'), 'dataset': 'breast_cancer', 'reference_method': 'independent_numpy_float32_model_parameters', 'reference_status': 'GENERATED_NOT_BACKEND_VALIDATED', 'model_sha256': sha(model_path), 'n_records': len(records), 'records': records}
    path.write_text(json.dumps(data, indent=2) + '\n')
    return records, {'reference': str(path.relative_to(ROOT)), 'sha256': sha(path), 'method': data['reference_method']}


RUST_SOURCE = r'''
use anyhow::{anyhow, Context, Result};
use serde_json::{json, Value};
use std::{env, fs};
use wasmtime::{Engine, Instance, Module, Store};
fn main() -> Result<()> {
    let args: Vec<String> = env::args().collect();
    if args.len() != 4 { return Err(anyhow!("usage: runner wasm reference output")); }
    let data: Value = serde_json::from_slice(&fs::read(&args[2])?)?;
    let records = data["records"].as_array().context("missing records")?;
    let engine = Engine::default();
    let module = Module::from_file(&engine, &args[1])?;
    let mut store = Store::new(&engine, ());
    let instance = Instance::new(&mut store, &module, &[])?;
    let ptr_fn = instance.get_typed_func::<(), i32>(&mut store, "input_ptr")?;
    let count_fn = instance.get_typed_func::<(), i32>(&mut store, "feature_count")?;
    let predict_fn = instance.get_typed_func::<(), i32>(&mut store, "predict")?;
    let memory = instance.get_memory(&mut store, "memory").context("missing memory export")?;
    let n = count_fn.call(&mut store, ())? as usize;
    let ptr = ptr_fn.call(&mut store, ())? as usize;
    let mut matched = 0usize;
    let mut mismatches = Vec::new();
    for (index, record) in records.iter().enumerate() {
        let features = record["features"].as_array().context("missing features")?;
        if features.len() != n { return Err(anyhow!("record {} has {} features, expected {}", index, features.len(), n)); }
        let mut bytes = Vec::with_capacity(4*n);
        for v in features { bytes.extend_from_slice(&(v.as_f64().context("invalid feature")? as f32).to_le_bytes()); }
        memory.write(&mut store, ptr, &bytes)?;
        let got = predict_fn.call(&mut store, ())?;
        let expected = record["prediction"].as_i64().context("missing prediction")? as i32;
        if got == expected { matched += 1; }
        else if mismatches.len() < 25 { mismatches.push(json!({"id": record["id"], "expected": expected, "actual": got})); }
    }
    let report = json!({"status": if matched == records.len() {"PASS"} else {"FAIL"}, "records": records.len(), "matched": matched, "mismatches": records.len()-matched, "examples": mismatches});
    fs::write(&args[3], serde_json::to_vec_pretty(&report)?)?;
    println!("{}", report);
    Ok(())
}
'''


def prepare_wasmtime_runner():
    project = PAR / 'all_models_wasmtime_runner'
    src = project / 'src'
    src.mkdir(parents=True, exist_ok=True)
    manifest = project / 'Cargo.toml'
    if not manifest.exists():
        manifest.write_text('[package]\nname = "comet-all-parity"\nversion = "0.1.0"\nedition = "2021"\n\n[dependencies]\nanyhow = "1"\nserde_json = "1"\nwasmtime = "=25.0.3"\n')
    (src / 'main.rs').write_text(RUST_SOURCE)
    subprocess.run(['cargo', 'build', '--release', '--manifest-path', str(manifest)], check=True)
    binary = project / 'target/release/comet-all-parity'
    assert binary.is_file()
    return binary


def wasmtime_test(name, reference, binary):
    wasm = ROOT / f'wasm/tenant_{name}_real/target/wasm32-unknown-unknown/release/tenant_{name}_real.wasm'
    assert wasm.is_file(), f'Missing Wasm binary {wasm}'
    tmp = PAR / f'.{name}_normalized_reference.json'
    tmp.write_text(json.dumps({'records': reference}))
    report = PAR / f'{name.upper()}_WASMTIME_PARITY_REPORT.json'
    try:
        subprocess.run([str(binary), str(wasm), str(tmp), str(report)], check=True, timeout=180)
        return json.loads(report.read_text())
    finally:
        tmp.unlink(missing_ok=True)


def docker_test(name, reference):
    image = f'comet-{name}-docker:v1'
    container = 'comet_validation_' + name + '_' + uuid.uuid4().hex[:12]
    report_path = PAR / f'{name.upper()}_DOCKER_PARITY_REPORT.json'
    # Docker allocates an unused host port; bind only to loopback.
    started = False
    try:
        result = subprocess.run(['docker', 'run', '-d', '--name', container, '-p', '127.0.0.1::8085', image], capture_output=True, text=True, check=True)
        started = True
        port_out = subprocess.check_output(['docker', 'port', container, '8085/tcp'], text=True).strip()
        port = int(port_out.rsplit(':', 1)[-1])
        url = f'http://127.0.0.1:{port}/infer'
        # POST readiness check (GET /infer may correctly return 405).
        ready = False
        for _ in range(40):
            try:
                request = urllib.request.Request(url, data=json.dumps({'features': reference[0]['features']}).encode(), headers={'Content-Type': 'application/json'}, method='POST')
                with urllib.request.urlopen(request, timeout=2) as response:
                    json.loads(response.read())
                ready = True
                break
            except (urllib.error.URLError, TimeoutError, OSError):
                time.sleep(0.25)
        if not ready:
            raise RuntimeError(f'{name} Docker server did not become ready')
        matched = 0
        errors = 0
        examples = []
        for r in reference:
            try:
                request = urllib.request.Request(url, data=json.dumps({'features': r['features']}).encode(), headers={'Content-Type': 'application/json'}, method='POST')
                with urllib.request.urlopen(request, timeout=10) as response:
                    got = int(json.loads(response.read())['prediction'])
                if got == r['prediction']:
                    matched += 1
                elif len(examples) < 25:
                    examples.append({'id': r['id'], 'expected': r['prediction'], 'actual': got})
            except Exception as exc:
                errors += 1
                if len(examples) < 25:
                    examples.append({'id': r['id'], 'error': str(exc)})
        report = {'status': 'PASS' if matched == len(reference) and errors == 0 else 'FAIL', 'records': len(reference), 'matched': matched, 'mismatches': len(reference) - matched - errors, 'errors': errors, 'examples': examples, 'image': image}
        report_path.write_text(json.dumps(report, indent=2) + '\n')
        return report
    finally:
        if started:
            subprocess.run(['docker', 'rm', '-f', container], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    assert (ROOT / 'models').is_dir() and (ROOT / 'wasm').is_dir(), 'Run from /home/sallar/wasiMultitenant'
    PAR.mkdir(parents=True, exist_ok=True)
    print('COMET-Wasm V2: seven-model prediction parity', flush=True)
    results = {}
    runner = None
    for name in MODELS:
        print(f'\n=== {name.upper()} ===', flush=True)
        result = {'wasmtime': {'status': 'NOT_TESTED'}, 'docker': {'status': 'NOT_TESTED'}}
        results[name] = result
        try:
            records, provenance = load_reference(name)
            result['reference'] = provenance
            result['reference_records'] = len(records)
            if runner is None:
                runner = prepare_wasmtime_runner()
            for backend in ['wasmtime', 'docker']:
                try:
                    report = wasmtime_test(name, records, runner) if backend == 'wasmtime' else docker_test(name, records)
                    result[backend] = report
                    print(f'{backend}: {report["status"]} ({report["matched"]}/{report["records"]}, errors={report.get("errors", 0)})', flush=True)
                except Exception as exc:
                    result[backend] = {'status': 'ERROR', 'error': str(exc)}
                    print(f'{backend}: ERROR: {exc}', flush=True)
        except Exception as exc:
            result['reference_error'] = str(exc)
            print(f'REFERENCE ERROR: {exc}', flush=True)
    all_pass = all(results[m][b]['status'] == 'PASS' for m in MODELS for b in ['wasmtime', 'docker'])
    summary = {'status': 'PASS' if all_pass else 'INCOMPLETE_OR_FAILED', 'model_count': len(MODELS), 'results': results}
    path = PAR / 'ALL_MODELS_PARITY_SUMMARY.json'
    path.write_text(json.dumps(summary, indent=2) + '\n')
    print('\n=== FINAL SUMMARY ===', flush=True)
    for name in MODELS:
        print(f'{name.upper():8} Wasmtime={results[name]["wasmtime"]["status"]:10} Docker={results[name]["docker"]["status"]:10}')
    print(f'OVERALL: {summary["status"]}\nREPORT: {path}', flush=True)
    return 0 if all_pass else 1


if __name__ == '__main__':
    sys.exit(main())
