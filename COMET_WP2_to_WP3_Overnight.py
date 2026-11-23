#!/usr/bin/env python3
"""Sequential COMET-Wasm overnight coordinator: wait WP2, audit, push, WP3, push.

No new research/scheduler modification before the WP1-3 STOP/GO checkpoint.
Never overlaps running WP2 with new CPU-intensive work. Records nonaccepted
2.5% CI cells without discarding their evidence. Uses explicit Git allowlist,
never commits other staged changes and never deletes raw evidence.
"""
import argparse
import csv
import datetime as dt
import fcntl
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import traceback

ROOT = Path(__file__).resolve().parent
BASE = ROOT / 'research_enhancement/automated_supervisor_workplan'
LR = BASE / 'wp2_lr_controlled_density_20261121'
SIX = BASE / 'wp2_six_models_controlled_density_20261121'
WP3 = BASE / 'wp3_cold_http_ready_seven_models_20261123'
REPORT = BASE / 'wp2_seven_model_controlled_audit_20261123'
SCRIPT_WP3 = ROOT / 'COMET_WP3_Cold_Readiness_Overnight.py'
MODELS = ('logistic_regression', 'naive_bayes', 'decision_tree', 'kmeans', 'random_forest', 'svm', 'mlp')
LEVELS = (1, 5, 10, 20, 50, 100, 200)
BACKENDS = ('wasmtime', 'docker')
COLUMNS = ('model', 'backend', 'tenants', 'repetitions', 'mean_pss_mib',
           'student_t_pct', 'bootstrap_pct', 'precision_met', 'mean_threads',
           'max_threads_observed', 'cpu_observed')


def stamp():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def show(*x):
    print(stamp(), *x, flush=True)


def require(ok, why):
    if not ok:
        raise RuntimeError('SAFE STOP: ' + why)


def read_json(path):
    return json.loads(path.read_text())


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, indent=2) + '\n')
    tmp.replace(path)


def read_csv(path):
    require(path.is_file(), f'Expected raw repetitions missing: {path}')
    with path.open(newline='') as f:
        return list(csv.DictReader(f))


def csv_output(path, columns, rows):
    with path.open('w', newline='') as f:
        w = csv.DictWriter(f, columns)
        w.writeheader()
        w.writerows(rows)


def copy_report():
    """Strict coverage, not blanket scientific acceptance."""
    REPORT.mkdir(parents=True, exist_ok=True)
    records = []
    missing = []
    duplicates = []
    incomplete = []
    precision_misses = []
    per_model_reps = {}
    manifest_files = {}
    for model in MODELS:
        folder = LR if model == 'logistic_regression' else SIX / model
        result_path, raw_path = folder / 'RESULT.json', folder / 'trials.csv'
        require(result_path.is_file(), f'{model}: no RESULT.json')
        manifest = folder / 'manifest.json'
        require(manifest.is_file(), f'{model}: no frozen manifest')
        results = read_json(result_path)
        raw = read_csv(raw_path)
        manifest_files[model] = str(manifest.relative_to(ROOT))
        groups = {}
        for r in raw:
            key = (r['backend'], int(r['tenants']))
            groups.setdefault(key, []).append(r)
        per_model_reps[model] = len(raw)
        for n in LEVELS:
            for backend in BACKENDS:
                stats = results.get('precision_by_density', {}).get(str(n), {}).get(backend)
                entries = groups.get((backend, n), [])
                if stats is None:
                    missing.append([model, backend, n, 'no_result'])
                    continue
                count = len(entries)
                keys = [(r['backend'], r['tenants'], r['rep']) for r in entries]
                if len(set(keys)) != count:
                    duplicates.append([model, backend, n, 'duplicates'])
                if not 20 <= count <= 60 or int(stats.get('n', 0)) != count:
                    incomplete.append([model, backend, n, count, stats.get('n')])
                passed = bool(stats.get('accepted', False))
                if not passed:
                    precision_misses.append({
                        'model': model, 'backend': backend, 'tenants': n,
                        'student_t_pct': stats.get('student_t_pct'),
                        'bootstrap_pct': stats.get('bootstrap_pct'),
                        'repetitions': count})
                tcounts = [float(r['total_threads']) for r in entries]
                max_threads = [int(r['max_threads']) for r in entries]
                cpus = sorted({str(r['cpu']) for r in entries})
                psamples = [float(r['pss_mib']) for r in entries]
                finite = psamples and all(math.isfinite(x) and x > 0 for x in psamples)
                if not finite:
                    incomplete.append([model, backend, n, 'invalid_pss'])
                records.append({
                    'model': model, 'backend': backend, 'tenants': n,
                    'repetitions': count, 'mean_pss_mib': stats.get('mean_pss_mib'),
                    'student_t_pct': stats.get('student_t_pct'),
                    'bootstrap_pct': stats.get('bootstrap_pct'),
                    'precision_met': passed,
                    'mean_threads': round(sum(tcounts) / len(tcounts), 3) if tcounts else '',
                    'max_threads_observed': max(max_threads) if max_threads else '',
                    'cpu_observed': ';'.join(cpus)})
    require(not missing and not duplicates and not incomplete,
            f'WP2 coverage/integrity mismatch: missing={missing[:4]}, duplicate={duplicates[:4]}, incomplete={incomplete[:4]}')
    require(len(records) == 98, f'Expected 98 conditions; got {len(records)}')
    ci_miss_count = len(precision_misses)
    csv_output(REPORT / 'WP2_Seven_Model_98_Conditions.csv', COLUMNS, records)
    readings = {(r['model'], r['backend'], int(r['tenants'])): r for r in records}
    comparison_rows = []
    for m in MODELS:
        for n in LEVELS:
            w = readings[(m, 'wasmtime', n)]
            d = readings[(m, 'docker', n)]
            wmem, dmem = float(w['mean_pss_mib']), float(d['mean_pss_mib'])
            comparison_rows.append({'model': m, 'tenants': n,
                                    'wasmtime_application_pss_mib': wmem,
                                    'docker_application_pss_mib': dmem,
                                    'wasm_to_docker_application_pss_ratio': wmem/dmem,
                                    'wasmtime_precision_met': w['precision_met'],
                                    'docker_precision_met': d['precision_met']})
    csv_output(REPORT / 'WP2_App_PSS_Comparison.csv',
               ('model', 'tenants', 'wasmtime_application_pss_mib',
                'docker_application_pss_mib', 'wasm_to_docker_application_pss_ratio',
                'wasmtime_precision_met', 'docker_precision_met'), comparison_rows)
    event_file = SIX / 'readiness_retry_events.csv'
    event_rows = read_csv(event_file) if event_file.is_file() else []
    result = {
        'audit_utc': stamp(), 'status': 'COVERAGE_CHECKED_NOT_FULL_WP2_SCIENTIFIC_ACCEPTANCE',
        'density_levels': len(MODELS) * len(LEVELS),
        'backend_density_conditions': len(records),
        'conditions_precision_met': len(records) - ci_miss_count,
        'conditions_precision_not_met': ci_miss_count,
        'precision_misses': precision_misses,
        'readiness_retries_six_model_campaign': len(event_rows),
        'readiness_events': event_rows,
        'raw_repetitions_per_model': per_model_reps,
        'frozen_manifests': manifest_files,
        'known_limitations': [
            'The measured metric is total application PSS, not full Docker daemon/helper ownership.',
            'Base/process, model-resident and incremental tenant PSS require explicit decomposition.',
            'JIT/AOT configuration sensitivity must be integrated with separately run pilot evidence.',
            'WP1 common-gateway, native parity and high-headroom verification remain independent.',
            'WP3 full symmetric cold and warm readiness is not established by this density dataset.',
            'Precision misses are recorded and not converted into passes.',
        ],
    }
    save_json(REPORT / 'WP2_Controlled_Audit.json', result)
    lines = [
        '# COMET-Wasm WP2 seven-model controlled density audit',
        '',
        f'- Audit UTC: {result["audit_utc"]}',
        '- Seven models, seven densities each, two backends: 98 cells.',
        f'- Relative CI precision met: {result["conditions_precision_met"]}/98.',
        f'- CI precision not met (retained): {ci_miss_count}/98.',
        f'- Recorded six-model readiness retry events: {len(event_rows)}.',
        '- Raw measurement coverage validated for 20–60 repetitions per condition.',
        '',
        '## Interpretation limitation',
        'This is an **application PSS** curve, not a full container stack/PSS cost; all prior caveats about helper accounting, JIT/AOT sensitivity, CPU/thread verification, and common gateway remain.',
        'A 2.5% CI precision miss does not invalidate the observation; its achieved precision is explicitly shown in the CSV.',
        'Scientific WP1–WP3 STOP/GO acceptance must be reviewed separately.',
        ''
    ]
    (REPORT / 'README.md').write_text('\n'.join(lines))
    show('WP2 AUDIT: 98/98 backend-density cells, precision met=',
         result['conditions_precision_met'], 'misses=', ci_miss_count,
         'readiness retry attempts=', len(event_rows))
    return result


def cli(args, *, timeout=180):
    env = dict(os.environ, GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='never')
    p = subprocess.run(args, cwd=ROOT, env=env, capture_output=True, text=True,
                       timeout=timeout)
    return p


def stage_files(stage):
    paths = [
        'COMET_WP2_LR_Controlled_Density.py',
        'COMET_WP2_Remaining_Six_Controlled_Density.py',
        'COMET_WP2_Six_Resume_Readiness.py',
        'COMET_WP3_Cold_Readiness_Overnight.py',
        'COMET_WP2_to_WP3_Overnight.py',
    ]
    for file in (LR / 'manifest.json', LR / 'RESULT.json', LR / 'trials.csv'):
        paths.append(str(file.relative_to(ROOT)))
    for model in MODELS[1:]:
        p = SIX / model
        for name in ('manifest.json', 'RESULT.json', 'trials.csv'):
            paths.append(str((p / name).relative_to(ROOT)))
    for name in ('COMPLETE.txt', 'SUITE_SUMMARY.json', 'readiness_retry_events.csv'):
        paths.append(str((SIX / name).relative_to(ROOT)))
    for name in ('WP2_Seven_Model_98_Conditions.csv', 'WP2_App_PSS_Comparison.csv',
                 'WP2_Controlled_Audit.json', 'README.md'):
        paths.append(str((REPORT / name).relative_to(ROOT)))
    if stage == 'wp3':
        for name in ('manifest.json', 'trials.csv', 'RESULT.json',
                     'readiness_failures.csv', 'COMPLETE.txt'):
            paths.append(str((WP3 / name).relative_to(ROOT)))
    output = []
    for path in paths:
        full = ROOT / path
        if full.is_file():
            size = full.stat().st_size
            require(size <= 5_000_000, f'Git staging file exceeds 5 MB safety limit: {path} ({size})')
            output.append(path)
    return output


def git_checkpoint(stage):
    """Never touch other staged work, branch, remote config or unrelated files."""
    status = {'timestamp': stamp(), 'stage': stage, 'status': 'NOT_ATTEMPTED'}
    try:
        check = cli(['git', 'rev-parse', '--is-inside-work-tree'])
        require(check.returncode == 0 and check.stdout.strip() == 'true', 'Not a Git repo')
        branch_response = cli(['git', 'branch', '--show-current'])
        branch = branch_response.stdout.strip()
        require(branch.startswith('research/') or branch.startswith('comet-v2-research-'),
                f'Unsafe branch for automatic Git commit: {branch!r}. No branch switching performed.')
        index = cli(['git', 'diff', '--cached', '--name-only'])
        require(index.returncode == 0 and not index.stdout.strip(),
                'Pre-existing staged changes. Refusing to create a mixed commit.')
        paths = stage_files(stage)
        require(paths, 'Nothing available to stage')
        add = cli(['git', 'add', '--', *paths])
        require(add.returncode == 0, 'git add failed: ' + add.stderr[-700:])
        checkstaged = cli(['git', 'diff', '--cached', '--name-only'])
        require(checkstaged.returncode == 0, 'Cannot inspect staged files')
        staged = [x.strip() for x in checkstaged.stdout.splitlines() if x.strip()]
        require(set(staged).issubset(set(paths)),
                'Staged change outside allowlist; refusing automatic commit')
        if staged:
            msg = ('checkpoint: controlled WP2 seven-model memory evidence and audit'
                   if stage == 'wp2' else
                   'checkpoint: WP3 cold-readiness diagnostic and precision report')
            committed = cli(['git', 'commit', '-m', msg], timeout=120)
            require(committed.returncode == 0, 'git commit failed: ' + committed.stderr[-700:])
        push = cli(['git', 'push', 'origin', branch], timeout=240)
        require(push.returncode == 0, 'git push failed (credentials/network/remote): ' + (push.stderr or push.stdout)[-950:])
        status.update(status='PUSHED', branch=branch,
                      commit=cli(['git', 'rev-parse', '--short', 'HEAD']).stdout.strip(),
                      staged_files=staged)
        show('GIT PUSHED:', stage, branch, status['commit'])
    except Exception as exc:
        status.update(status='GIT_BLOCKED_NONFATAL', reason=str(exc))
        show('GIT PUSH NOT CONFIRMED:', stage, str(exc))
    save_json(REPORT / f'GIT_{stage.upper()}_STATUS.json', status)
    return status


def preflight():
    require(SCRIPT_WP3.is_file(), f'WP3 runner missing {SCRIPT_WP3.name}')
    require((ROOT / 'COMET_WP2_LR_Controlled_Density.py').is_file(), 'WP2 LR base script missing')
    require((ROOT / 'COMET_WP2_Remaining_Six_Controlled_Density.py').is_file(), 'WP2 six-model script missing')
    require(SIX.is_dir(), 'Six-model density output directory missing')
    require((SIX / '.single_runner.lock').is_file(), 'Six-model lock missing')
    p = subprocess.run([sys.executable, str(SCRIPT_WP3), '--preflight'],
                       cwd=ROOT, capture_output=True, text=True, timeout=90)
    require(p.returncode == 0, 'WP3 diagnostic preflight failed: ' + (p.stderr or p.stdout)[-600:])
    show('OVERNIGHT PREFLIGHT PASS:', p.stdout.strip())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--preflight', action='store_true')
    args = ap.parse_args()
    preflight()
    if args.preflight:
        return
    REPORT.mkdir(parents=True, exist_ok=True)
    checkpoint = {'started_at': stamp(), 'state': 'WAITING_FOR_WP2'}
    save_json(REPORT / 'OVERNIGHT_STATE.json', checkpoint)
    # Actual WP2 runner holds this lock for its full duration. Wait without polling.
    with (SIX / '.single_runner.lock').open('a+') as lock:
        show('WAITING FOR SIX-MODEL WP2 LOCK TO BE RELEASED...')
        fcntl.flock(lock, fcntl.LOCK_EX)  # Blocks without benchmark activity.
        require((SIX / 'COMPLETE.txt').is_file(),
                'WP2 released lock without suite COMPLETE.txt; do not start next experiment')
        require((LR / 'RESULT.json').is_file(), 'LR results missing')
        checkpoint['state'] = 'WP2_FINISHED_AUDITING'
        save_json(REPORT / 'OVERNIGHT_STATE.json', checkpoint)
        audit = copy_report()
        checkpoint['wp2_audit'] = audit['status']
        checkpoint['git_wp2'] = git_checkpoint('wp2')['status']
        checkpoint['state'] = 'WP3_DIAGNOSTIC_RUNNING'
        save_json(REPORT / 'OVERNIGHT_STATE.json', checkpoint)
        # Keep WP2 lock across the successor to prevent an accidental second
        # WP2 runner from overlapping with this CPU-sensitive experiment.
        show('STARTING WP3 DIAGNOSTIC: controlled cold functional-HTTP readiness',
             'models=', MODELS, 'densities=', LEVELS)
        p = subprocess.run([sys.executable, '-u', str(SCRIPT_WP3)], cwd=ROOT)
        require(p.returncode == 0 and (WP3 / 'COMPLETE.txt').is_file(),
                'WP3 diagnostic not complete; preserve raw trials and do not mark success')
        checkpoint['state'] = 'WP3_FINISHED_PUSHING'
        save_json(REPORT / 'OVERNIGHT_STATE.json', checkpoint)
        checkpoint['git_wp3'] = git_checkpoint('wp3')['status']
        checkpoint['state'] = 'DONE'
        checkpoint['finished_at'] = stamp()
        save_json(REPORT / 'OVERNIGHT_STATE.json', checkpoint)
        show('OVERNIGHT SEQUENCE FINISHED; WP1-WP3 scientific STOP/GO still pending review')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        REPORT.mkdir(parents=True, exist_ok=True)
        save_json(REPORT / 'OVERNIGHT_FAILURE.json',
                  {'timestamp': stamp(), 'failure': repr(exc), 'traceback': traceback.format_exc()[-5000:]})
        show('SAFE STOP:', repr(exc))
        raise SystemExit(2)
