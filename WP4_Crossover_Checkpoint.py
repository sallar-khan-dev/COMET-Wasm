#!/usr/bin/env python3
"""Read-only WP4 checkpoint, based on COMET-Wasm supervisor plan §§6–7.

Reports observed kernel means, statistical uncertainty, and inventories existing
WP1/WP3 inputs. Does not infer request-path dispatch costs from cold-start times.
"""
import csv
import json
from pathlib import Path

ROOT = Path('/home/sallar/wasiMultitenant')
if not ROOT.exists():
    ROOT = Path.cwd()
BASE = ROOT / 'results/processed/wp4_crossover'
FAMILIES = {
    'MLP': [(64,'mlp_width_64'), (128,'mlp_width_128'), (256,'mlp_width_256')],
    'RF': [(100,'rf_trees_100'), (200,'rf_trees_200'), (400,'rf_trees_400')],
    'SVM (support vectors)': [(127,'svm_c_0p3'), (183,'svm_c_0p1'), (280,'svm_c_0p03')],
}

def summary(variant, backend):
    paths = sorted(BASE.glob(f'{backend}_{variant}_execution_time_full_summary.json'))
    if not paths:
        paths = sorted(BASE.glob(f'{backend}_{variant}_*_execution_time_full_summary.json'))
    if len(paths) != 1:
        raise ValueError(f'{variant}/{backend}: expected exactly one summary; found {len(paths)}: {paths}')
    data = json.loads(paths[0].read_text())
    for key in ('execution_mean_ns','execution_relative_95ci','repetitions'):
        if key not in data:
            raise ValueError(f'{paths[0]}: missing {key}')
    return data

print('COMET-Wasm WP4 supervisor checkpoint: observations, NOT crossover proof')
print('Existing result files are read only. No workloads are executed.')
print('')
print(f'{"Family":<23}{"Complexity":>10}{"W (us)":>12}{"D (us)":>12}{"W/D":>9}{"W CI %":>10}{"D CI %":>10}{"W reps":>9}{"D reps":>9}')
print('-'*104)
for fam, variants in FAMILIES.items():
    last = None
    for complexity, variant in variants:
        try:
            w, d = summary(variant,'wasmtime'), summary(variant,'docker')
        except (ValueError, OSError, json.JSONDecodeError) as e:
            print('MISSING/INVALID:',e)
            continue
        kw, kd = w['execution_mean_ns']/1000, d['execution_mean_ns']/1000
        relw, reld = 100*w['execution_relative_95ci'], 100*d['execution_relative_95ci']
        print(f'{fam:<23}{complexity:>10}{kw:>12.3f}{kd:>12.3f}{kw/kd:>9.3f}{relw:>10.3f}{reld:>10.3f}{w["repetitions"]:>9}{d["repetitions"]:>9}')
        if last is not None and (kw-kd)*(last[1]-last[2]) < 0:
            print(f'  OBSERVED KERNEL MEAN REVERSAL between complexity {last[0]} and {complexity}; NOT a validated service crossover')
        last = (complexity, kw, kd)
    print('')

print('SUPERVISOR WP4 INPUTS / EVIDENCE INVENTORY')
print('Requirement: L_W = D_W + K_W and L_D = D_D + K_D, with matched request paths.')
print('The table above supplies execution means (candidate K); their exact WP3 batched-kernel equivalence must be audited.')
print('D_W and D_D must come from corrected comparable warm service/request-path decompositions.')
print('Do NOT substitute deployment cold start, first inference, or tenant admission for D.')

processed = ROOT/'results/processed'
for label, search_parts in [
 ('WP1 corrected performance/gateway evidence', ('performance','comet')),
 ('WP3 dispatch/overhead evidence', ('overhead','execution_time')),
 ('WP3 admission/startup evidence', ('cold_start',)),
 ('WP2 density and memory evidence', ('density',)),
]:
    print('\n'+label+':')
    count = 0
    for part in search_parts:
        directory = processed/part
        if directory.is_dir():
            files = sorted(p for p in directory.rglob('*') if p.is_file() and p.suffix in ('.csv','.json'))
            print(f'  {directory.relative_to(ROOT)}: {len(files)} CSV/JSON files')
            for p in files[:12]:
                print('   ',p.relative_to(ROOT))
            if len(files)>12: print(f'    ... {len(files)-12} additional files')
            count += len(files)
    if not count: print('  No matching files found in expected processed-result locations.')

cold = processed/'cold_start/cold_start_final_comparison.csv'
if cold.is_file():
    with cold.open(newline='') as f:
        rows=list(csv.DictReader(f))
    print(f'\nBaseline cold-start comparison found ({len(rows)} workloads); EXCLUDED from warm D estimates.')

print('\nCHECKPOINT DECISION:')
print('1. Existing MLP/RF/SVM kernel campaign is available for the observational WP4 chart.')
print('2. Predicting K* requires validated backend-specific warm D and comparable batched K/native data.')
print('3. Until these inputs are confirmed, NO predicted crossover, below/near/above selection, or WP5 transition is justified.')
print('4. Next evidence-only action is to identify and validate the matching WP1/WP3 measurements from the inventory above.')
