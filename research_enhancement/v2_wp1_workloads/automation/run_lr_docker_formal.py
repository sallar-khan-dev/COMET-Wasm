#!/usr/bin/env python3
"""COMET-Wasm LR Docker formal experiment, resumable with outer-run statistics."""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path('/home/sallar/wasiMultitenant')
BASE = ROOT / 'research_enhancement/v2_wp1_workloads'
OUT = BASE / 'experiments/lr_docker_formal_25rps'
LOADGEN = ROOT / 'research_enhancement/v2_loadgen/target/release/comet_v2_loadgen'
TRACE = ROOT / 'research_enhancement/v2_workloads/lr_iris_trace_135_seed42_t3.json'
GOLDEN = ROOT / 'research_enhancement/v2_references/lr_iris_golden_v1.json'
sys.path.insert(0, str(BASE / 'automation'))
from statistical_control import evaluate, MIN_RUNS, MAX_RUNS

METRICS = ('execution_time_ns', 'inference_time_ns', 'request_total_ns', 'latency_from_schedule_ns', 'latency_from_dispatch_ns')
EXPECTED_PER_REPLAY = 135
INNER = 50


def write_json(path, data):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(data, indent=2) + '\n')
    temp.replace(path)


def read_replay(prefix):
    path = Path(str(prefix) + '.requests.jsonl')
    summary_path = Path(str(prefix) + '.summary.json')
    if not path.is_file() or not summary_path.is_file():
        raise RuntimeError(f'Missing replay artifacts: {prefix}')
    summary = json.loads(summary_path.read_text())
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if len(rows) != EXPECTED_PER_REPLAY or summary.get('offered_requests') != EXPECTED_PER_REPLAY:
        raise RuntimeError(f'Unexpected request count: {prefix}')
    if summary.get('successful_requests') != EXPECTED_PER_REPLAY or any(summary.get(k) != 0 for k in ('failed_requests', 'timed_out_requests', 'dropped_requests')):
        raise RuntimeError(f'Unsuccessful replay: {prefix}: {summary}')
    if any(not r.get('success') or r.get('served_backend') != 'docker' or r.get('http_status') != 200 or r.get('actual_prediction') != r.get('expected_prediction') for r in rows):
        raise RuntimeError(f'Incorrect inference/backend in {prefix}')
    for r in rows:
        for metric in METRICS:
            v = r.get(metric)
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not (0 < v < float('inf')):
                raise RuntimeError(f'Missing/nonpositive {metric}: {prefix}')
    return rows


def run_replay(prefix):
    env = dict(os.environ, COMET_LOADGEN_WORKERS='2')
    cmd = [str(LOADGEN), str(TRACE), str(GOLDEN), 'http', 'http://127.0.0.1:8200/infer', 'docker', '25', '5000', '16', str(prefix)]
    log = Path(str(prefix) + '.log')
    with log.open('w') as f:
        proc = subprocess.run(cmd, cwd=ROOT, env=env, stdout=f, stderr=subprocess.STDOUT)
    if proc.returncode:
        raise RuntimeError(f'Loadgen failed for {prefix}; inspect {log}')


def outer_summary(outer, index):
    all_rows = []
    for j in range(1, INNER + 1):
        prefix = outer / f'inner_{j:02d}'
        request_path = Path(str(prefix) + '.requests.jsonl')
        summary_path = Path(str(prefix) + '.summary.json')
        if not request_path.exists() and not summary_path.exists():
            print(f'  Running outer {index:02d}, inner {j:02d}/{INNER}', flush=True)
            run_replay(prefix)
        elif not request_path.exists() or not summary_path.exists():
            raise RuntimeError(f'Incomplete replay: {prefix}; inspect manually before resuming')
        all_rows.extend(read_replay(prefix))
    result = {'backend': 'docker', 'outer_run': index, 'inner_replays': INNER, 'requests': len(all_rows), 'metrics': {}}
    for m in METRICS:
        values = sorted(r[m] / 1_000_000 for r in all_rows)
        n = len(values)
        result['metrics'][m] = {
            'mean_ms': sum(values) / n,
            'median_ms': (values[(n - 1) // 2] + values[n // 2]) / 2,
            'p95_ms': percentile(values, 0.95),
            'p99_ms': percentile(values, 0.99),
            'min_ms': values[0], 'max_ms': values[-1],
        }
    write_json(outer / 'outer_summary.json', result)
    return result


def percentile(a, p):
    pos = (len(a) - 1) * p
    low = int(pos)
    frac = pos - low
    return a[low] * (1 - frac) + a[min(low + 1, len(a) - 1)] * frac


def main():
    if not all(p.is_file() for p in (LOADGEN, TRACE, GOLDEN)):
        raise RuntimeError('Missing loadgen/trace/golden file')
    OUT.mkdir(parents=True, exist_ok=True)
    existing = sorted(p.name for p in OUT.iterdir())
    if existing and not all(name.startswith('outer_') or name == 'statistical_summary.json' for name in existing):
        raise RuntimeError(f'Unexpected files in output directory: {existing[:10]}')
    for index in range(1, MAX_RUNS + 1):
        outer = OUT / f'outer_{index:02d}'
        outer.mkdir(exist_ok=True)
        # Reconstruct each outer summary from validated request files, including resumed runs.
        outer_summary(outer, index)
        if index < MIN_RUNS:
            print(f'Completed outer {index}/{MIN_RUNS} minimum', flush=True)
            continue
        completed = [json.loads((OUT / f'outer_{i:02d}' / 'outer_summary.json').read_text()) for i in range(1, index + 1)]
        stats = {}
        for metric in METRICS:
            e = evaluate([o['metrics'][metric]['mean_ms'] for o in completed])
            stats[metric] = {
                'mean_ms': e.mean, 'ci95_lower_ms': e.ci_lower, 'ci95_upper_ms': e.ci_upper,
                'relative_half_width_percent': e.relative_half_width * 100,
                'precision_target_met': e.target_met,
            }
        passed = all(v['precision_target_met'] for v in stats.values())
        result = {'backend': 'docker', 'outer_runs': index, 'inner_replays_per_outer': INNER,
                  'total_requests': index * INNER * EXPECTED_PER_REPLAY,
                  'metrics': stats, 'all_metrics_precision_target_met': passed,
                  'stopping_reason': 'all_metrics_precision_target_met' if passed else ('maximum_repetitions_reached' if index == MAX_RUNS else 'continue_sampling')}
        write_json(OUT / 'statistical_summary.json', result)
        print(f'Outer {index}: ' + ', '.join(f'{m}={v["relative_half_width_percent"]:.3f}%' for m, v in stats.items()), flush=True)
        if passed or index == MAX_RUNS:
            print('STOP:', result['stopping_reason'], flush=True)
            return


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f'ERROR: {e}', file=sys.stderr, flush=True)
        sys.exit(1)
