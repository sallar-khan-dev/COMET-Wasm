#!/usr/bin/env python3
"""COMET supervisor WP4 §7, stage 1: estimate the measured CPU crossover.

Uses accepted WP1-WP3 experimental evidence only. Does not manufacture large-model
variants or launch heavy-model experiments before the crossover is estimated.
Does not modify any previous results or scheduler. Follow-up heavy experiments
must use the established adaptive 20..60 repetition precision protocol.
"""
import csv
import datetime as dt
import json
import math
import os
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPORTS = ROOT / 'research_enhancement/reports'
WP3 = REPORTS / 'wp3_service_decomposition/20261124_035240/DECOMPOSITION.json'
GATE = REPORTS / 'wp1_wp3_final_reconciled/20261125_223313/EVIDENCE_AND_GATE.json'
OUT = REPORTS / 'wp4_crossover' / (dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d_%H%M%S') + '_' + str(os.getpid()))
OUT.mkdir(parents=True, exist_ok=False)

def load(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError) as e:
        raise RuntimeError(f'Missing or unreadable required evidence: {path}: {e}') from e

def mean_of(model, field):
    p = ((source.get('models') or {}).get(model) or {}).get('components') or {}
    v = (p.get(field) or {}).get('mean_ns')
    if not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0:
        raise RuntimeError(f'No positive valid measured mean for {model}/{field}')
    return float(v)

gate = load(GATE)
checks = gate.get('checks', {})
fail = [k for k, v in checks.items() if not (isinstance(v, dict) and v.get('status') == 'PASS')]
if fail or len(checks) != 14:
    raise RuntimeError('WP1–WP3 evidence gate is not 14/14 PASS: ' + ', '.join(fail))
if gate.get('decision') != 'GO_CANDIDATE_FOR_SUPERVISOR_REVIEW':
    raise RuntimeError('WP1-WP3 gate is not a GO candidate; refusing WP4')

source = load(WP3)
rows = []
for model in ('lr', 'rf'):
    w, d = f'{model}_wasmtime', f'{model}_docker'
    kw = mean_of(w, 'execution_time_ns')
    kd = mean_of(d, 'execution_time_ns')
    lw = mean_of(w, 'request_total_ns')
    ld = mean_of(d, 'request_total_ns')
    dw, dd = lw - kw, ld - kd
    if min(dw, dd) < 0:
        raise RuntimeError(f'Negative non-kernel overhead for {model}; invalid decomposition')
    s = kw / kd
    overhead_difference = dd - dw
    # A positive crossover requires a positive K*_Docker, and actual relative
    # kernel slowdown must point to a region in which Docker compute wins.
    if abs(s-1) < 1e-12:
        star = None
        why = 'Kernel ratio approximately 1: no finite crossover under the linear approximation'
    else:
        candidate = overhead_difference / (s - 1)
        star = candidate if candidate > 0 and math.isfinite(candidate) else None
        why = 'Positive design estimate, not a measured backend crossover' if star is not None else 'No positive predicted crossover with measured decomposition'
    share_w = kw / lw
    share_d = kd / ld
    rows.append({
        'model': model,
        'wasm_kernel_ns': kw, 'docker_kernel_ns': kd,
        'wasm_service_ns': lw, 'docker_service_ns': ld,
        'wasm_non_kernel_ns': dw, 'docker_non_kernel_ns': dd,
        'kernel_ratio_wasm_over_docker': s,
        'predicted_docker_kernel_crossover_ns': star,
        'predicted_docker_kernel_crossover_ms': star/1e6 if star is not None else None,
        'wasm_execution_share_pct': share_w*100,
        'docker_execution_share_pct': share_d*100,
        'interpretation': why
    })

planned = {
    'light_baseline': ['logistic_regression', 'naive_bayes', 'decision_tree', 'kmeans', 'random_forest', 'svm', 'mlp'],
    'medium_candidates_from_existing_implementations': ['larger_mlp', 'larger_random_forest', 'larger_svm'],
    'heavy_new_model_limit': 1,
    'design_rule': 'Choose actual sizes below/near/above positive crossover estimate before measuring final backend winner. Do not invent sizes absent measured execution-cost scaling.',
    'control': {'minimum_repetitions': 20, 'maximum_repetitions': 60,
                'target_relative_95_percent_CI_halfwidth_percent': 2.5,
                'scope': 'every NEW experimental cell, including performance and seven-level density for every heavier model'},
    'density_counts': [1,5,10,20,50,100,200],
    'backend_equivalence': 'Same model logic and inference engine for native/Docker and Wasmtime. No simultaneous ML engine and substrate change.',
    'one_model_per_wasmtime_host': True,
    'execution_share': 'T_kernel/T_request, seek broad natural range without forcing result',
    'success': 'Explain observed crossover; if Docker never wins, report that and narrow claim.',
}
report = {
    'work_package': 'WP4, supervisor §7',
    'phase': 'Measured crossover estimation and workload-sizing prerequisites',
    'input_gate': str(GATE), 'input_service_decomposition': str(WP3),
    'reused_accepted_evidence_only': True,
    'rows': rows, 'next_experiment_specification': planned,
    'status': 'WP4_CROSSOVER_ESTIMATED__HEAVY_MODEL_SCALING_NOT_YET_RUN',
    'warning': 'The preceding gate is GO_CANDIDATE_FOR_SUPERVISOR_REVIEW, not recorded supervisor approval. Respect any supervisor approval requirement before executing new WP4 experiments.'
}
(OUT/'WP4_CROSSOVER_ESTIMATE.json').write_text(json.dumps(report, indent=2)+'\n')
with (OUT/'WP4_CROSSOVER_ESTIMATE.csv').open('w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=[k for k in rows[0] if k != 'interpretation'] + ['interpretation'])
    writer.writeheader();writer.writerows(rows)
print('WP4 §7: measured crossover estimate from accepted WP1–WP3')
for r in rows:
    v=r['predicted_docker_kernel_crossover_ms']
    print(f"{r['model'].upper()}: Wasm kernel share {r['wasm_execution_share_pct']:.3f}%, "
          f"Docker kernel share {r['docker_execution_share_pct']:.3f}%, "
          f"kernel ratio {r['kernel_ratio_wasm_over_docker']:.4f}, "
          f"predicted Docker kernel crossover: {v:.6f} ms" if v is not None else
          f"{r['model'].upper()}: No positive predicted crossover; "
          f"Wasm share {r['wasm_execution_share_pct']:.3f}%, "
          f"Docker share {r['docker_execution_share_pct']:.3f}%")
print('NEXT WP4: Scale existing MLP/RF/SVM below, near and above crossover, then execute')
print('matched performance + 7-density experiments; adaptive 20..60 repetitions per cell.')
print('SAVED:', OUT/'WP4_CROSSOVER_ESTIMATE.json')
