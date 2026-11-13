#!/usr/bin/env python3
"""Non-destructive supervisor WP1-WP3 stop/go review using existing experiments.

Fixes erroneous WP2 model-label parsing. Reviews data coverage and known plan
acceptance gaps. Never reruns experiments, changes scheduler, or asserts a GO
based only on presence of files.
"""
import csv, json, os, pathlib, datetime, collections, statistics
ROOT=pathlib.Path(__file__).resolve().parent
BASE=ROOT/'research_enhancement/automated_supervisor_workplan'
N=(1,5,10,20,50,100,200)
MODEL_ALIASES={
 'lr':{'lr','logistic_regression','logisticregression','logistic regression'},
 'nb':{'nb','naive_bayes','naivebayes','naive bayes'},
 'dt':{'dt','decision_tree','decisiontree','decision tree'},
 'kmeans':{'kmeans','k_means','k-means','k means'},
 'rf':{'rf','random_forest','randomforest','random forest'},
 'svm':{'svm','support_vector_machine','supportvectormachine','support vector machine'},
 'mlp':{'mlp','multilayer_perceptron','multi_layer_perceptron','multilayer perceptron'},
}
BACKEND_ALIASES={'wasmtime':{'wasmtime','wasm','webassembly'},'docker':{'docker','container'}}

def canonical(v,aliases):
 s=str(v or '').strip().lower()
 for k,values in aliases.items():
  if s in values:return k
 return None

def newest(glob,needed):
 ps=[p for p in BASE.glob(glob) if p.is_dir() and all((p/n).is_file() for n in needed)]
 return max(ps,key=lambda p:p.stat().st_mtime) if ps else None

def jload(path):
 try:return json.loads(path.read_text())
 except (OSError,ValueError):return {}

def density():
 p=ROOT/'results/processed/density/density_seven_levels_statistical_summary.csv'
 if not p.is_file():return {'status':'BLOCKED','reason':'Statistical summary absent','file':str(p)}
 with p.open(newline='') as f:rows=list(csv.DictReader(f))
 counts=collections.Counter(); bad=[]; zero=[]; values={}
 for i,r in enumerate(rows,2):
  m=canonical(r.get('model'),MODEL_ALIASES)
  b=canonical(r.get('backend'),BACKEND_ALIASES)
  try:n=int(float(r.get('physical_tenants','')));pss=float(r.get('pss_mib_mean',''))
  except (ValueError,TypeError):bad.append({'row':i,'reason':'Missing/non-numeric tenant or PSS','raw_model':r.get('model'),'raw_backend':r.get('backend')});continue
  if m is None or b is None or n not in N or not (0<=pss<1e8):
   bad.append({'row':i,'reason':'Unrecognised model/backend/tenant/PSS','raw_model':r.get('model'),'raw_backend':r.get('backend'),'n':n});continue
  counts[m,b,n]+=1;values[(m,b,n)]=pss
  if pss==0:zero.append([m,b,n])
 expected={(m,b,n) for m in MODEL_ALIASES for b in BACKEND_ALIASES for n in N}
 missing=sorted(expected-set(counts));duplicate=sorted([list(k)+[v] for k,v in counts.items() if v>1]);extras=sorted(set(counts)-expected)
 available_columns=list(rows[0]) if rows else []
 required_decomp=['pss_mib_mean','rss_mib_mean','private_mib_mean']
 missing_cols=[c for c in required_decomp if c not in available_columns]
 result={'status':'EVIDENCE_PRESENT' if not missing and not duplicate and not bad and not missing_cols else 'BLOCKED',
  'rows':len(rows),'present_cells':len(expected&set(counts)),'required_cells':len(expected),
  'missing_cells':missing,'duplicate_cells':duplicate,'invalid_rows':bad[:20], 'zero_pss_cells':zero,
  'missing_columns':missing_cols,'columns':available_columns,'source':str(p.relative_to(ROOT)),
  'scope':'Coverage and basic memory columns only. Per-tenant base/model/incremental PSS, Docker helpers, actual thread parity and confidence precision remain separate acceptance conditions.'}
 return result

def main():
 if not (ROOT/'serving/common_ingress').exists():raise SystemExit('Run from /home/sallar/wasiMultitenant, with script saved at repository root.')
 out=BASE/'wp1_wp3_stop_go'/('corrected_'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%d_%H%M%S')+'_'+str(os.getpid()))
 out.mkdir(parents=True,exist_ok=False)
 previous=newest('wp1_wp3_stop_go/*/',('STOP_GO.json',))
 previous_data=jload(previous/'STOP_GO.json') if previous and previous!=out else {}
 original_checks=previous_data.get('checks',{})
 # Source the other check statuses from the latest saved dossier; they are not independently revalidated here.
 for k in ('WP1','WP2_Docker_PSS','WP2_JIT_AOT','WP3_batched_execution','WP3_cold_admission'):
  if k not in original_checks: original_checks[k]={'status':'NOT_REVALIDATED','reason':'Prior dossier unavailable'}
 original_checks['WP2_density']=density()
 blockers=[]
 for k,v in original_checks.items():
  if isinstance(v,dict) and v.get('status')!='EVIDENCE_PRESENT':blockers.append(f'{k}: {v.get("status")}')
 required=[
  'WP1 §4.1–4.3: common ingress including native attribution, matched thread/CPU configuration and demonstrated no-op load generator headroom',
  'WP2 §5: base/model/incremental PSS decomposition and separately attributable Docker helper memory where measurable',
  'WP3 §6.1: separated kernel, guest call, host input-copy and complete backend service costs',
  'WP3 §6.2: consistent readiness strategy for cold paths, and accurately labelled warm admission scopes',
 ]
 blockers.extend(required)
 decision='NO_GO_PENDING_ACCEPTANCE'
 result={'decision':decision,'density':original_checks['WP2_density'],'checks':original_checks,
         'unresolved_supervisor_acceptance_criteria':required,'blockers':blockers,
         'note':'Correction resolves name-label parsing only. An evidence inventory is not scientific acceptance; no false GO issued.',
         'prior_dossier':str(previous) if previous else None}
 (out/'STOP_GO_CORRECTED.json').write_text(json.dumps(result,indent=2,default=str)+'\n')
 lines=['# COMET-Wasm WP1–WP3 corrected supervisor stop/go','',
        '## WP2 density coverage',
        f"- **{result['density']['status']}**: {result['density'].get('present_cells',0)}/{result['density'].get('required_cells',98)} cells",
        f"- Missing: {result['density'].get('missing_cells',[])}",
        f"- Invalid rows: {result['density'].get('invalid_rows',[])}",
        f"- Duplicate cells: {result['density'].get('duplicate_cells',[])}",
        '', '## Other experiment inventories']
 for k,v in original_checks.items():
  if k!='WP2_density' and isinstance(v,dict):lines.append(f'- {k}: {v.get("status","UNAVAILABLE")}')
 lines+=['','## Outstanding scientific acceptance tasks']+[f'- {s}' for s in required]+['','## Stop/go decision',f'**{decision}**',
         'This decision is conservative: the supervisor requires experimental comparability, not just file existence.','']
 (out/'STOP_GO_CORRECTED.md').write_text('\n'.join(lines))
 print('CORRECTED WP2 DENSITY COVERAGE:',result['density'].get('present_cells',0),'/',result['density'].get('required_cells',98))
 print('WP2 DENSITY STATUS:',result['density']['status'])
 print('MISSING:',result['density'].get('missing_cells'))
 print('INVALID_ROWS:',result['density'].get('invalid_rows'))
 print('FINAL:',decision)
 print('REPORT:',out/'STOP_GO_CORRECTED.md')
 print('DATA:',out/'STOP_GO_CORRECTED.json')
if __name__=='__main__':main()
