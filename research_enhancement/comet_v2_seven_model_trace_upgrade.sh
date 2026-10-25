#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="${COMET_ROOT:-$HOME/wasiMultitenant}"
cd "$ROOT"
MAIN=research_enhancement/v2_loadgen/src/main.rs
GEN=research_enhancement/v2_workloads/generate_trace.py
[[ -f "$MAIN" && -f "$GEN" ]] || { echo 'ERROR: missing expected V2 sources'; exit 2; }
RUN="$ROOT/research_enhancement/v2_seven_model_upgrade/$(date +%Y%m%d_%H%M%S)_$$"
mkdir -p "$RUN/backup"
cp -p "$MAIN" "$RUN/backup/loadgen_main.rs"
cp -p "$GEN" "$RUN/backup/generate_trace.py"
echo "BACKUP=$RUN/backup"
python3 - "$MAIN" "$GEN" <<'PY'
from pathlib import Path
import sys
main,gen=map(Path,sys.argv[1:])
s=main.read_text()
old='''    if trace.model != "lr" {
        bail!("Only LR traces are currently supported");
    }

    if trace.dataset != "iris_binary" {
        bail!("Unexpected dataset");
    }'''
new='''    if !matches!(trace.model.as_str(), "lr" | "nb" | "dt" | "kmeans" | "rf" | "svm" | "mlp") {
        bail!("Unsupported model: {}", trace.model);
    }
    if trace.dataset.trim().is_empty() {
        bail!("Dataset name must not be empty");
    }'''
assert old in s or new in s, 'Unexpected loadgen model validation; refusing unsafe patch'
s=s.replace(old,new)
old='''        if request.features.len() != 4 || !request.features.iter().all(|x| x.is_finite()) {
            bail!("Invalid LR feature vector");
        }'''
new='''        let expected_features = match trace.model.as_str() {
            "lr" => 4,
            "rf" | "svm" => 30,
            _ => trace.requests[0].features.len(),
        };
        if expected_features == 0 || request.features.len() != expected_features
            || !request.features.iter().all(|x| x.is_finite()) {
            bail!("Invalid feature vector for model {}", trace.model);
        }'''
assert old in s or new in s, 'Unexpected loadgen feature validation; refusing unsafe patch'
s=s.replace(old,new)
old='''        if !matches!(request.expected_prediction, 0 | 1) {
            bail!("Invalid expected prediction");
        }

        if !matches!(request.ground_truth_label, 0 | 1) {
            bail!("Invalid ground-truth label");
        }

        if request.source_row_index >= 45 {
            bail!("Source row index out of range");
        }'''
new='''        if i32::try_from(request.expected_prediction).is_err() {
            bail!("Expected prediction outside i32 range");
        }
        // Ground-truth labels are retained for provenance, but golden predictions
        // (not dataset labels) are the inference correctness oracle.
        if trace.model == "lr" && request.source_row_index >= 45 {
            bail!("LR source row index out of range");
        }'''
assert old in s or new in s, 'Unexpected loadgen label validation; refusing unsafe patch'
s=s.replace(old,new)
main.write_text(s)
s=gen.read_text()
old='''        if record["expected_prediction"] not in (0, 1):
            raise ValueError("Invalid LR expected prediction")'''
new='''        prediction = record["expected_prediction"]
        if isinstance(prediction, bool) or not isinstance(prediction, int) or not (-2**31 <= prediction < 2**31):
            raise ValueError("Golden prediction must be an i32 integer")'''
assert old in s or new in s, 'Unexpected trace generator validation; refusing unsafe patch'
s=s.replace(old,new)
gen.write_text(s)
PY
python3 -m py_compile "$GEN"
(
 cd research_enhancement/v2_loadgen
 cargo test --locked 2>&1 | tee "$RUN/loadgen_tests.log"
 cargo build --release --locked 2>&1 | tee "$RUN/loadgen_build.log"
)
python3 - "$ROOT" "$RUN" <<'PY'
import json,sys,pathlib
root=pathlib.Path(sys.argv[1]); out=pathlib.Path(sys.argv[2]); models=['lr','nb','dt','kmeans','rf','svm','mlp']
results={}
for model in models:
  gold=list((root/'research_enhancement/v2_references').glob(f'{model}_*.json')) if (root/'research_enhancement/v2_references').exists() else []
  traces=list((root/'research_enhancement/v2_workloads').glob(f'{model}_*.json'))
  results[model]={'golden_references':[str(p.relative_to(root)) for p in gold], 'traces':[str(p.relative_to(root)) for p in traces]}
(out/'reference_inventory.json').write_text(json.dumps(results,indent=2))
print(json.dumps(results,indent=2))
PY
printf '\nPASS: seven-model trace parser and generator upgraded; Rust tests/build passed.\n'
printf 'No model predictions or reference labels were invented. Missing goldens still need independent generation and validation.\n'
printf 'RESULTS=%s\n' "$RUN"
echo "PACKAGE: tar -czf ~/comet_v2_seven_model_upgrade.tar.gz -C '$RUN' ."
