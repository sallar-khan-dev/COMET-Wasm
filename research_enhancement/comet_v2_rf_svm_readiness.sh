#!/usr/bin/env bash
set -euo pipefail
ROOT="${COMET_ROOT:-$HOME/wasiMultitenant}"
cd "$ROOT"
OUT="$ROOT/research_enhancement/v2_rf_svm_readiness/$(date +%Y%m%d_%H%M%S)_$$"
mkdir -p "$OUT"
echo "RUN_DIR=$OUT"
{
 echo '=== git ==='; git status --short; git rev-parse HEAD
 echo '=== tools ==='; for x in cargo rustc docker podman curl jq python3; do command -v "$x" || true; done
 echo '=== targets ==='; rustup target list --installed 2>/dev/null || true
 echo '=== RF/SVM source files ==='; find wasm docker serving research_enhancement -maxdepth 5 -type f \( -iname '*rf*' -o -iname '*svm*' -o -iname '*golden*' -o -iname '*trace*' \) 2>/dev/null | head -160
 echo '=== wasm binaries ==='; find . -type f \( -name '*.wasm' -o -name '*.cwasm' \) -not -path './.git/*' -printf '%p %s bytes\n' 2>/dev/null | head -120
 echo '=== docker images ==='; docker images --format '{{.Repository}}:{{.Tag}} {{.ID}}' 2>&1 | head -90 || true
 echo '=== running containers ==='; docker ps --format '{{.Names}} {{.Image}} {{.Ports}}' 2>&1 || true
 echo '=== ingress binary ==='; find serving/common_ingress/target -type f -name comet_common_ingress -printf '%p %s bytes\n' 2>/dev/null | head -10
 echo '=== listener ports ==='; ss -ltnp 2>/dev/null | grep -E ':(808[0-9]|81[0-9][0-9]|82[0-9][0-9])\b' || true
} > "$OUT/environment.txt" 2>&1
python3 - "$OUT" <<'PY'
from pathlib import Path
import sys,json,re
out=Path(sys.argv[1]); root=Path.cwd()
report={}
for m in ('rf','svm'):
    w=root/'wasm'/f'tenant_{m}_real'/'src/lib.rs'
    d=root/'docker'/f'{m}_server'/'src/main.rs'
    entry={'wasm_source_exists':w.is_file(),'docker_source_exists':d.is_file()}
    for key,p in [('wasm',w),('docker',d)]:
        if p.is_file():
            s=p.read_text(); entry[f'{key}_feature_constants']=re.findall(r'const\s+N_FEATURES\s*:\s*usize\s*=\s*(\d+)',s)[:2]
            entry[f'{key}_entrypoints']=[line.strip() for line in s.splitlines() if any(t in line for t in ('export_name', 'pub extern "C" fn','fn infer(', 'fn predict_', 'pub fn infer('))][:20]
    report[m]=entry
(out/'model_interface.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
PY
# Capture only relevant source; do not include datasets, trained model artifacts or secrets.
mkdir -p "$OUT/source"
for p in serving/common_ingress/src/main.rs serving/common_ingress/src/wasm_adapter.rs serving/common_ingress/src/inference_protocol.rs serving/common_ingress/src/routes.rs research_enhancement/v2_loadgen/src/main.rs research_enhancement/v2_loadgen/src/http_dispatcher.rs research_enhancement/v2_loadgen/src/inference_protocol.rs research_enhancement/v2_workloads/generate_trace.py wasm/tenant_rf_real/Cargo.toml wasm/tenant_svm_real/Cargo.toml docker/rf_server/Cargo.toml docker/svm_server/Cargo.toml; do
 if [[ -f "$p" ]]; then mkdir -p "$OUT/source/$(dirname "$p")"; cp "$p" "$OUT/source/$p"; fi
done
# Record output schemas only, without copying large reference datasets.
python3 - "$OUT" <<'PY'
from pathlib import Path
import sys,json
root=Path.cwd(); out=Path(sys.argv[1]); a=[]
for p in (root/'research_enhancement').rglob('*.json'):
 if 'golden' not in p.name.lower() and 'trace' not in p.name.lower(): continue
 try:
  if p.stat().st_size>15_000_000: continue
  x=json.loads(p.read_text())
  if not isinstance(x,dict): continue
  a.append({'path':str(p.relative_to(root)),'model':x.get('model'),'dataset':x.get('dataset'),'schema_version':x.get('schema_version'),'sample_count':x.get('sample_count'),'request_count':x.get('request_count'),'first_record_keys':list(x.get('records',[{}])[0]) if x.get('records') else [],'first_request_keys':list(x.get('requests',[{}])[0]) if x.get('requests') else []})
 except (OSError,ValueError,IndexError): continue
(out/'reference_inventory.json').write_text(json.dumps(a,indent=2)+'\n')
PY
ARCHIVE="$HOME/comet_v2_rf_svm_readiness.tar.gz"
tar -czf "$ARCHIVE" -C "$OUT" .
echo "DONE: $OUT"
echo "ARCHIVE: $ARCHIVE"
echo 'No existing services, containers, or tracked source files were changed.'
