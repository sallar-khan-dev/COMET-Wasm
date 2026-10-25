#!/usr/bin/env bash
set -euo pipefail
ROOT="${COMET_ROOT:-$HOME/wasiMultitenant}"
cd "$ROOT"
SRC=serving/common_ingress/src/main.rs
[[ -f "$SRC" ]] || { echo "Missing $SRC" >&2; exit 2; }
command -v python3 >/dev/null
command -v cargo >/dev/null
python3 - "$SRC" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1]); s=p.read_text()
if 'wasm_models: Arc<std::collections::HashMap<String, WasmAdapter>>' in s:
    print('Multimodel ingress patch already present'); sys.exit(0)
changes=[
 ('wasm_lr: Option<WasmAdapter>,','wasm_models: Arc<std::collections::HashMap<String, WasmAdapter>>,',1),
 ('if route.backend != Backend::Wasmtime || route.model != "lr" {','if route.backend != Backend::Wasmtime {',1),
 ('let adapter = state.wasm_lr.as_ref().ok_or_else(|| {','let adapter = state.wasm_models.get(&route.model).ok_or_else(|| {',1),
 ('wasm_lr: None,','wasm_models: Arc::new(std::collections::HashMap::new()),',1),
]
for old,new,count in changes:
    found=s.count(old)
    if found != count: raise SystemExit(f'Unexpected source layout: {old!r} occurs {found}, expected {count}; no changes made')
    s=s.replace(old,new)
start=s.index('    let wasm_lr = if routes\n')
end=s.index('    let app = Router::new()',start)
replacement='''    let mut wasm_models = std::collections::HashMap::new();
    let workers: usize = std::env::var("COMET_WASM_WORKERS")
        .unwrap_or_else(|_| "2".to_string()).parse()?;
    for route in routes.values() {
        if route.backend != Backend::Wasmtime || wasm_models.contains_key(&route.model) {
            continue;
        }
        let env_key = format!("COMET_{}_WASM_PATH", route.model.to_ascii_uppercase());
        let path = std::env::var(&env_key).map_err(|_| {
            anyhow::anyhow!("{} is required for Wasmtime model {}", env_key, route.model)
        })?;
        let adapter = WasmAdapter::new(&path, workers)?;
        wasm_models.insert(route.model.clone(), adapter);
    }
    let state = AppState {
        routes: Arc::new(routes),
        wasm_models: Arc::new(wasm_models),
        docker: DockerAdapter::new(),
    };

'''
s=s[:start]+replacement+s[end:]
p.write_text(s)
print('Patched multimodel Wasmtime routing: lr, nb, dt, kmeans, rf, svm, mlp (when module paths are provided)')
PY
if ! cargo test --manifest-path serving/common_ingress/Cargo.toml > /tmp/comet_v2_ingress_patch_test_$$.log 2>&1; then
 echo 'Compilation/tests FAILED. Review latest /tmp/comet_v2_ingress_patch_test_*.log. No services changed.' >&2
 exit 1
fi
cargo build --release --manifest-path serving/common_ingress/Cargo.toml
echo 'PASS: multimodel ingress compiled and tests passed. No processes or containers restarted.'
echo 'Set COMET_RF_WASM_PATH / COMET_SVM_WASM_PATH for RF/SVM routes before starting a NEW ingress instance.'
