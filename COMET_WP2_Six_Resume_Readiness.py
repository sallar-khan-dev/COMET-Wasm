#!/usr/bin/env python3
"""Checkpoint-preserving recovery wrapper; logs and retries readiness failures only."""
import csv
import time
from datetime import datetime, timezone
from pathlib import Path
import COMET_WP2_Remaining_Six_Controlled_Density as campaign

BASE = Path('/home/sallar/wasiMultitenant/research_enhancement/automated_supervisor_workplan')
EVENTS = BASE / 'wp2_six_models_controlled_density_20261121' / 'readiness_retry_events.csv'

def bounded_retry(operation, backend):
    def measured(model, n, rep, *args):
        for attempt in (1, 2, 3):
            try:
                return operation(model, n, rep, *args)
            except RuntimeError as exc:
                if not str(exc).startswith('Readiness failed:'):
                    raise
                EVENTS.parent.mkdir(parents=True, exist_ok=True)
                with EVENTS.open('a', newline='') as f:
                    fields = ['utc', 'model', 'backend', 'tenants', 'repetition',
                              'attempt', 'error']
                    writer = csv.DictWriter(f, fieldnames=fields)
                    if f.tell() == 0:
                        writer.writeheader()
                    writer.writerow(dict(
                        utc=datetime.now(timezone.utc).isoformat(),
                        model=model, backend=backend, tenants=n, repetition=rep,
                        attempt=attempt, error=str(exc)[:500]
                    ))
                    f.flush()
                print(f'READINESS FAILURE {model} {backend} N={n} '
                      f'REP={rep} ATTEMPT={attempt}/3: {exc}', flush=True)
                if attempt == 3:
                    print('SAFE STOP: repeated readiness failure; no partial '
                          'repetition added to trials.csv', flush=True)
                    raise
                time.sleep(attempt * 10)
    return measured

campaign.wasm_measure = bounded_retry(campaign.wasm_measure, 'wasmtime')
campaign.docker_measure = bounded_retry(campaign.docker_measure, 'docker')

if __name__ == '__main__':
    campaign.main()
