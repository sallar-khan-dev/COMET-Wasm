#!/usr/bin/env bash
set -euo pipefail

ROOT="$(pwd)"
echo "============================================================"
echo " Installing COMET-Wasm Framework"
echo " Root: ${ROOT}"
echo "============================================================"

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "WARNING: '$1' not found. Some parts may not build until installed."
  else
    echo "✓ Found $1"
  fi
}

need_cmd python3
need_cmd pip3
need_cmd cargo
need_cmd rustc
need_cmd docker
need_cmd curl
need_cmd hey

DIRS=(
  datasets/iris datasets/breast_cancer datasets/wine datasets/digits
  models/logistic_regression models/naive_bayes models/decision_tree models/random_forest models/svm models/kmeans models/mlp
  training/python training/export training/preprocessing
  wasm/tenant_lr_real wasm/tenant_nb_real wasm/tenant_dt_real wasm/tenant_rf_real wasm/tenant_svm_real wasm/tenant_kmeans_real wasm/tenant_mlp_real
  docker/lr_server docker/nb_server docker/dt_server docker/rf_server docker/svm_server docker/kmeans_server docker/mlp_server
  serving/wasm_server/host_lr_server serving/docker_server serving/scheduler serving/runtime_pool serving/gateway
  comet/characteriser comet/scheduler comet/backend_selector comet/scoring comet/taxonomy comet/equations
  experiments/throughput experiments/latency experiments/coldstart experiments/density experiments/scalability experiments/scheduler experiments/mixed_workloads
  scripts/ci scripts/analysis scripts/plotting scripts/statistics
  results/ci_runs results/coldstart results/density results/throughput results/scheduler
  figures papers docs
)
for d in "${DIRS[@]}"; do mkdir -p "$ROOT/$d"; done

cat > "$ROOT/requirements.txt" <<'REQ'
numpy
pandas
scipy
scikit-learn
matplotlib
joblib
requests
REQ

python3 -m venv "$ROOT/.venv"
source "$ROOT/.venv/bin/activate"
python -m pip install --upgrade pip
pip install -r "$ROOT/requirements.txt"

cat > "$ROOT/README.md" <<'MD'
# COMET-Wasm Framework

**Title:** Multi-Tenant ML Inference Serving on WebAssembly: A Compute and Memory Characterisation

COMET-Wasm = **Characterisation-Oriented Multi-Tenant Execution and Scheduling Technique for WebAssembly**.

This framework supports real ML workload export, Wasm execution, Docker baseline serving, CI-controlled experiments, cold-start evaluation, memory-density evaluation, and a COMET-Wasm scheduler skeleton.
MD

cat > "$ROOT/training/python/train_export_models.py" <<'PY'
import json
from pathlib import Path
import pandas as pd
from sklearn.datasets import load_iris, load_breast_cancer, load_wine, load_digits
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import accuracy_score, precision_recall_fscore_support
from sklearn.linear_model import LogisticRegression
from sklearn.naive_bayes import GaussianNB
from sklearn.tree import DecisionTreeClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.svm import SVC
from sklearn.cluster import KMeans
from sklearn.neural_network import MLPClassifier

ROOT = Path(__file__).resolve().parents[2]

def save_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2))

def save_csv(path, X, y, feature_names):
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(X, columns=feature_names)
    df["label"] = y
    df.to_csv(path, index=False)

def metrics(y_true, y_pred):
    avg = "binary" if len(set(y_true)) == 2 else "macro"
    p, r, f1, _ = precision_recall_fscore_support(y_true, y_pred, average=avg, zero_division=0)
    return {"accuracy": float(accuracy_score(y_true, y_pred)), "precision": float(p), "recall": float(r), "f1": float(f1)}

def export_lr_iris():
    data = load_iris()
    X = data.data.astype(float)
    y = (data.target == 2).astype(int)
    feature_names = [n.replace(" (cm)", "").replace(" ", "_") for n in data.feature_names]
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.30, random_state=42, stratify=y)
    scaler = StandardScaler()
    X_train_s = scaler.fit_transform(X_train)
    X_test_s = scaler.transform(X_test)
    clf = LogisticRegression(max_iter=1000, random_state=42)
    clf.fit(X_train_s, y_train)
    pred = clf.predict(X_test_s)
    model = {
        "model": "LogisticRegression", "dataset": "Iris", "task": "virginica_vs_non_virginica",
        "feature_names": feature_names, "weights": clf.coef_[0].astype(float).tolist(),
        "bias": float(clf.intercept_[0]), "mean": scaler.mean_.astype(float).tolist(),
        "scale": scaler.scale_.astype(float).tolist(), "metrics": metrics(y_test, pred),
        "profile_hint": {"compute_class": "lightweight_linear", "memory_class": "very_low", "complexity": "O(d)", "features": int(X.shape[1]), "train_samples": int(X_train.shape[0]), "test_samples": int(X_test.shape[0])}
    }
    out_dir = ROOT / "models" / "logistic_regression" / "iris_lr"
    save_json(out_dir / "model.json", model)
    save_csv(out_dir / "test_samples.csv", X_test, y_test, feature_names)
    save_csv(ROOT / "datasets" / "iris" / "iris_binary_test.csv", X_test, y_test, feature_names)
    save_json(ROOT / "datasets" / "iris" / "iris_lr_metadata.json", model)
    print("Saved LR model:", out_dir / "model.json")
    print(json.dumps(model["metrics"], indent=2))

def export_sklearn_zoo():
    datasets = {"breast_cancer": load_breast_cancer(), "wine": load_wine(), "digits": load_digits()}
    classifiers = {
        "naive_bayes": GaussianNB(),
        "decision_tree": DecisionTreeClassifier(max_depth=8, random_state=42),
        "random_forest": RandomForestClassifier(n_estimators=50, max_depth=8, random_state=42),
        "svm": SVC(kernel="rbf", gamma="scale", probability=False, random_state=42),
        "mlp": MLPClassifier(hidden_layer_sizes=(32,), max_iter=500, random_state=42),
    }
    summary = []
    for dname, data in datasets.items():
        X = data.data.astype(float)
        y = data.target
        feature_names = [str(n).replace(" ", "_").replace("(", "").replace(")", "") for n in getattr(data, "feature_names", [f"f{i}" for i in range(X.shape[1])])]
        X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.30, random_state=42, stratify=y)
        scaler = StandardScaler()
        X_train_s = scaler.fit_transform(X_train)
        X_test_s = scaler.transform(X_test)
        save_csv(ROOT / "datasets" / dname / "test_samples.csv", X_test, y_test, feature_names)
        for mname, clf in classifiers.items():
            try:
                clf.fit(X_train_s, y_train)
                pred = clf.predict(X_test_s)
                met = metrics(y_test, pred)
                obj = {"model": mname, "dataset": dname, "feature_names": feature_names, "mean": scaler.mean_.astype(float).tolist(), "scale": scaler.scale_.astype(float).tolist(), "metrics": met, "profile_hint": {"features": int(X.shape[1]), "train_samples": int(X_train.shape[0]), "test_samples": int(X_test.shape[0])}}
                out = ROOT / "models" / mname / dname
                save_json(out / "metadata.json", obj)
                save_csv(out / "test_samples.csv", X_test, y_test, feature_names)
                summary.append({"dataset": dname, "model": mname, **met})
            except Exception as e:
                summary.append({"dataset": dname, "model": mname, "error": str(e)})
    iris = load_iris()
    X = iris.data.astype(float)
    km = KMeans(n_clusters=3, n_init=10, random_state=42)
    labels = km.fit_predict(X)
    save_json(ROOT / "models" / "kmeans" / "iris" / "metadata.json", {"model": "KMeans", "dataset": "iris", "centroids": km.cluster_centers_.astype(float).tolist(), "profile_hint": {"compute_class": "centroid_distance", "memory_class": "low_medium", "complexity": "O(k*d)"}})
    save_csv(ROOT / "models" / "kmeans" / "iris" / "samples.csv", X, labels, [f"f{i}" for i in range(X.shape[1])])
    summary.append({"dataset": "iris", "model": "kmeans", "note": "unsupervised_centroid_export"})
    save_json(ROOT / "models" / "model_zoo_summary.json", summary)
    print("Saved model zoo summary:", ROOT / "models" / "model_zoo_summary.json")

if __name__ == "__main__":
    export_lr_iris()
    export_sklearn_zoo()
PY
python "$ROOT/training/python/train_export_models.py"

if command -v cargo >/dev/null 2>&1; then
  echo "Creating Rust Wasm Logistic Regression tenant..."
  cd "$ROOT/wasm"
  if [ ! -f tenant_lr_real/Cargo.toml ]; then rm -rf tenant_lr_real; cargo new tenant_lr_real --lib; fi
  cat > "$ROOT/wasm/tenant_lr_real/Cargo.toml" <<'TOML'
[package]
name = "tenant_lr_real"
version = "0.1.0"
edition = "2021"

[lib]
crate-type = ["cdylib"]

[dependencies]
TOML
  cat > "$ROOT/wasm/tenant_lr_real/generate_lr_lib.py" <<'PY'
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
m = json.loads((ROOT / "models" / "logistic_regression" / "iris_lr" / "model.json").read_text())
def arr(vals): return "[" + ", ".join(f"{v:.10}f32" for v in vals) + "]"
code = f'''#[no_mangle]
pub extern "C" fn predict(f1: f32, f2: f32, f3: f32, f4: f32) -> i32 {{
    let weights: [f32; 4] = {arr(m["weights"])};
    let mean: [f32; 4] = {arr(m["mean"])};
    let scale: [f32; 4] = {arr(m["scale"])};
    let input: [f32; 4] = [f1, f2, f3, f4];
    let mut z: f32 = {m["bias"]:.10}f32;
    let mut i = 0;
    while i < 4 {{
        let x_scaled = (input[i] - mean[i]) / scale[i];
        z += weights[i] * x_scaled;
        i += 1;
    }}
    let probability = 1.0f32 / (1.0f32 + (-z).exp());
    if probability >= 0.5 {{ 1 }} else {{ 0 }}
}}
'''
Path("src/lib.rs").write_text(code)
print("Generated src/lib.rs")
PY
  cd "$ROOT/wasm/tenant_lr_real"
  python generate_lr_lib.py
  rustup target add wasm32-unknown-unknown || true
  cargo build --release --target wasm32-unknown-unknown || true
fi

if command -v cargo >/dev/null 2>&1; then
  echo "Creating Wasm host LR server..."
  cd "$ROOT/serving/wasm_server"
  if [ ! -f host_lr_server/Cargo.toml ]; then rm -rf host_lr_server; cargo new host_lr_server; fi
  cat > "$ROOT/serving/wasm_server/host_lr_server/Cargo.toml" <<'TOML'
[package]
name = "host_lr_server"
version = "0.1.0"
edition = "2021"

[dependencies]
axum = "0.7"
tokio = { version = "1", features = ["full"] }
serde = { version = "1", features = ["derive"] }
anyhow = "1"
wasmtime = "44"
TOML
  cat > "$ROOT/serving/wasm_server/host_lr_server/src/main.rs" <<'RS'
use axum::{extract::State, routing::post, Json, Router};
use serde::{Deserialize, Serialize};
use std::{net::SocketAddr, sync::{Arc, Mutex}, time::Instant};
use wasmtime::*;

#[derive(Clone)]
struct AppState { runtime: Arc<Mutex<WasmRuntime>> }
struct WasmRuntime { store: Store<()>, predict: TypedFunc<(f32, f32, f32, f32), i32> }
#[derive(Deserialize)]
struct InferenceRequest { f1: f32, f2: f32, f3: f32, f4: f32 }
#[derive(Serialize)]
struct InferenceResponse { prediction: i32, inference_time_ns: u128 }

async fn infer(State(state): State<AppState>, Json(payload): Json<InferenceRequest>) -> Json<InferenceResponse> {
    let start = Instant::now();
    let mut runtime = state.runtime.lock().unwrap();
    let predict = runtime.predict.clone();
    let prediction = predict.call(&mut runtime.store, (payload.f1, payload.f2, payload.f3, payload.f4)).unwrap_or(-1);
    Json(InferenceResponse { prediction, inference_time_ns: start.elapsed().as_nanos() })
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    println!("Starting COMET-Wasm LR Wasmtime Server");
    let engine = Engine::default();
    let module_path = "../../../wasm/tenant_lr_real/target/wasm32-unknown-unknown/release/tenant_lr_real.wasm";
    let module = Module::from_file(&engine, module_path)?;
    let mut store = Store::new(&engine, ());
    let instance = Instance::new(&mut store, &module, &[])?;
    let predict = instance.get_typed_func::<(f32, f32, f32, f32), i32>(&mut store, "predict")?;
    let runtime = WasmRuntime { store, predict };
    let state = AppState { runtime: Arc::new(Mutex::new(runtime)) };
    let app = Router::new().route("/infer", post(infer)).with_state(state);
    let addr = SocketAddr::from(([0, 0, 0, 0], 8010));
    println!("Wasm LR server listening on http://{}", addr);
    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;
    Ok(())
}
RS
  cd "$ROOT/serving/wasm_server/host_lr_server"
  cargo build --release || true
fi

if command -v cargo >/dev/null 2>&1; then
  echo "Creating Docker-native LR server..."
  cd "$ROOT/docker"
  if [ ! -f lr_server/Cargo.toml ]; then rm -rf lr_server; cargo new lr_server; fi
  cat > "$ROOT/docker/lr_server/Cargo.toml" <<'TOML'
[package]
name = "docker_lr_server"
version = "0.1.0"
edition = "2021"

[dependencies]
axum = "0.7"
tokio = { version = "1", features = ["full"] }
serde = { version = "1", features = ["derive"] }
anyhow = "1"
TOML
  cat > "$ROOT/docker/lr_server/generate_main.py" <<'PY'
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
m = json.loads((ROOT / "models" / "logistic_regression" / "iris_lr" / "model.json").read_text())
def arr(vals): return "[" + ", ".join(f"{v:.10}f32" for v in vals) + "]"
code = f'''use axum::{{extract::Json, routing::post, Router}};
use serde::{{Deserialize, Serialize}};
use std::{{net::SocketAddr, time::Instant}};
#[derive(Deserialize)]
struct InferenceRequest {{ f1: f32, f2: f32, f3: f32, f4: f32 }}
#[derive(Serialize)]
struct InferenceResponse {{ prediction: i32, inference_time_ns: u128 }}
async fn infer(Json(payload): Json<InferenceRequest>) -> Json<InferenceResponse> {{
    let start = Instant::now();
    let weights: [f32; 4] = {arr(m["weights"])};
    let mean: [f32; 4] = {arr(m["mean"])};
    let scale: [f32; 4] = {arr(m["scale"])};
    let input: [f32; 4] = [payload.f1, payload.f2, payload.f3, payload.f4];
    let mut z: f32 = {m["bias"]:.10}f32;
    for i in 0..4 {{
        let x_scaled = (input[i] - mean[i]) / scale[i];
        z += weights[i] * x_scaled;
    }}
    let probability = 1.0f32 / (1.0f32 + (-z).exp());
    let prediction = if probability >= 0.5 {{ 1 }} else {{ 0 }};
    Json(InferenceResponse {{ prediction, inference_time_ns: start.elapsed().as_nanos() }})
}}
#[tokio::main]
async fn main() -> anyhow::Result<()> {{
    println!("Starting Native Docker LR Server");
    let app = Router::new().route("/infer", post(infer));
    let addr = SocketAddr::from(([0, 0, 0, 0], 8085));
    println!("Docker LR server listening on http://{{}}", addr);
    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;
    Ok(())
}}
'''
Path("src/main.rs").write_text(code)
print("Generated src/main.rs")
PY
  cd "$ROOT/docker/lr_server"
  python generate_main.py
  cargo build --release || true
  cat > "$ROOT/docker/lr_server/Dockerfile" <<'DOCKER'
FROM rust:1.89
WORKDIR /app
COPY . .
RUN cargo build --release
EXPOSE 8085
CMD ["./target/release/docker_lr_server"]
DOCKER
fi

cat > "$ROOT/scripts/ci/servingMetricsPlusCI.py" <<'PY'
#!/usr/bin/env python3
import argparse, csv, re, subprocess, time
from pathlib import Path
import numpy as np
from scipy import stats

def run_hey(url, body, concurrency, duration_s):
    cmd = ["hey", "-z", f"{duration_s}s", "-c", str(concurrency), "-m", "POST", "-H", "Content-Type: application/json", "-d", body, url]
    out = subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)
    def extract(pattern, default=np.nan):
        m = re.search(pattern, out)
        return float(m.group(1)) if m else default
    return {"rps": extract(r"Requests/sec:\s+([0-9.]+)"), "avg_ms": extract(r"Average:\s+([0-9.]+)")*1000, "p50_ms": extract(r"50%% in\s+([0-9.]+)")*1000, "p95_ms": extract(r"95%% in\s+([0-9.]+)")*1000, "p99_ms": extract(r"99%% in\s+([0-9.]+)")*1000}

def rel_ci(values, confidence=0.95):
    arr = np.array(values, dtype=float); n = len(arr); mean = float(np.mean(arr))
    if n < 2 or mean == 0: return mean, float("inf")
    h = stats.sem(arr) * stats.t.ppf((1 + confidence) / 2.0, n - 1)
    return mean, abs(h / mean)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True); ap.add_argument("--url", required=True); ap.add_argument("--body", required=True)
    ap.add_argument("--concurrency", type=int, default=32); ap.add_argument("--duration-s", type=int, default=5); ap.add_argument("--warmup", type=int, default=1)
    ap.add_argument("--repeat-min", type=int, default=20); ap.add_argument("--repeat-max", type=int, default=60); ap.add_argument("--rel-precision", type=float, default=0.025); ap.add_argument("--cooldown-s", type=float, default=1.0)
    args = ap.parse_args()
    out_dir = Path("results/ci_runs"); out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = out_dir / f"{args.name}_raw.csv"; summary_path = out_dir / f"{args.name}_summary.csv"
    print(f"Experiment: {args.name}\nURL: {args.url}\nConcurrency: {args.concurrency}\nDuration per repeat: {args.duration_s}s\nPrecision target: {args.rel_precision*100:.2f}%")
    for i in range(args.warmup): print(f"Warmup {i+1}/{args.warmup}"); run_hey(args.url, args.body, args.concurrency, args.duration_s)
    rows = []
    with raw_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["run", "rps", "avg_ms", "p50_ms", "p95_ms", "p99_ms"]); writer.writeheader()
        for i in range(1, args.repeat_max + 1):
            print(f"Measured run {i}/{args.repeat_max}"); row = run_hey(args.url, args.body, args.concurrency, args.duration_s); row["run"] = i; rows.append(row); writer.writerow(row); f.flush()
            if i >= args.repeat_min:
                p95_mean, p95_rel = rel_ci([r["p95_ms"] for r in rows]); rps_mean, rps_rel = rel_ci([r["rps"] for r in rows])
                print(f"  p95 mean={p95_mean:.4f} ms, relCI={p95_rel*100:.2f}%"); print(f"  rps mean={rps_mean:.2f}, relCI={rps_rel*100:.2f}%")
                if p95_rel <= args.rel_precision and rps_rel <= args.rel_precision: print("Precision target reached."); break
            time.sleep(args.cooldown_s)
    with summary_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["metric", "mean", "std", "min", "max", "p95_rel_ci", "n"]); writer.writeheader()
        for metric in ["rps", "avg_ms", "p50_ms", "p95_ms", "p99_ms"]:
            vals = [r[metric] for r in rows]; mean, rel = rel_ci(vals)
            writer.writerow({"metric": metric, "mean": mean, "std": float(np.std(vals, ddof=1)) if len(vals)>1 else 0, "min": float(np.min(vals)), "max": float(np.max(vals)), "p95_rel_ci": rel, "n": len(vals)})
    print(f"Saved raw results: {raw_path}\nSaved summary: {summary_path}")
if __name__ == "__main__": main()
PY
chmod +x "$ROOT/scripts/ci/servingMetricsPlusCI.py"

cat > "$ROOT/experiments/coldstart/wasm_lr_coldstart.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
echo "Starting REAL Wasm LR cold-start test..."
START=$(date +%s%3N)
cd "$ROOT/serving/wasm_server/host_lr_server"
cargo run --release > /tmp/wasm_lr_server.log 2>&1 &
SERVER_PID=$!
sleep 2
curl -s -X POST http://localhost:8010/infer -H "Content-Type: application/json" -d '{"f1":6.3,"f2":3.3,"f3":6.0,"f4":2.5}' > /dev/null || true
END=$(date +%s%3N)
echo "REAL Wasm LR cold-start time: $((END - START)) ms"
kill "$SERVER_PID" > /dev/null 2>&1 || true
wait "$SERVER_PID" 2>/dev/null || true
SH

cat > "$ROOT/experiments/coldstart/docker_lr_coldstart.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
echo "Starting REAL Docker LR cold-start test..."
docker rm -f docker_lr_coldstart >/dev/null 2>&1 || true
START=$(date +%s%3N)
docker run -d -p 8090:8085 --name docker_lr_coldstart docker-lr-server > /dev/null
sleep 2
curl -s -X POST http://localhost:8090/infer -H "Content-Type: application/json" -d '{"f1":6.3,"f2":3.3,"f3":6.0,"f4":2.5}' > /dev/null || true
END=$(date +%s%3N)
echo "REAL Docker LR cold-start time: $((END - START)) ms"
docker rm -f docker_lr_coldstart >/dev/null 2>&1 || true
SH
chmod +x "$ROOT/experiments/coldstart/"*.sh

cat > "$ROOT/comet/scoring/comet_score.py" <<'PY'
from dataclasses import dataclass
@dataclass
class ModelProfile:
    compute_intensity: float; memory_intensity: float; latency_sensitivity: float; tenant_pressure: float; model_size: float; density_sensitivity: float; cold_start_sensitivity: float
@dataclass
class BackendProfile:
    name: str; compute_capability: float; available_memory: float; tenant_capacity: float; sla_compliance: float; startup_efficiency: float; current_memory: float; current_tenants: int; p95_latency: float
@dataclass
class Constraints:
    memory_budget: float; sla_latency: float; tenant_capacity: int

def comet_score(m, b, lambdas=None):
    if lambdas is None: lambdas = [1.0, 1.0, 1.0, 1.0, 1.0]
    l1, l2, l3, l4, l5 = lambdas
    return l1*m.compute_intensity*b.compute_capability + l2*m.memory_intensity*b.available_memory + l3*m.tenant_pressure*b.tenant_capacity + l4*m.latency_sensitivity*b.sla_compliance + l5*m.cold_start_sensitivity*b.startup_efficiency

def feasible(b, c): return b.current_memory <= c.memory_budget and b.p95_latency <= c.sla_latency and b.current_tenants <= c.tenant_capacity

def select_backend(model, backends, constraints):
    candidates = [b for b in backends if feasible(b, constraints)]
    return None if not candidates else max(candidates, key=lambda b: comet_score(model, b))

if __name__ == "__main__":
    model = ModelProfile(0.2, 0.1, 0.8, 0.9, 0.1, 0.9, 0.8)
    backends = [BackendProfile("wasmtime",0.7,0.9,0.95,0.9,0.95,0.4,10,0.4), BackendProfile("docker",0.9,0.6,0.55,0.75,0.4,0.7,10,0.7), BackendProfile("wasi-nn",0.95,0.8,0.7,0.9,0.6,0.5,5,0.5)]
    selected = select_backend(model, backends, Constraints(1.0, 1.0, 20))
    print("Selected backend:", selected.name if selected else "none")
PY

cat > "$ROOT/comet/equations/COMET_equations.md" <<'MD'
# COMET-Wasm Equations

P(m) = <C_m, M_m, L_m, T_m, S_m, D_m, K_m>

Suitability(m,b) = w_C Fit_C(m,b) + w_M Fit_M(m,b) + w_L Fit_L(m,b) + w_T Fit_T(m,b) + w_K Fit_K(m,b) - w_X SwitchCost(m,b)

COMETScore(m,b) = λ1 C_m R_b + λ2 M_m A_b + λ3 T_m Q_b + λ4 L_m S_b + λ5 K_m H_b

b* = argmax_b COMETScore(m,b)
subject to Memory_b <= Budget, p95_b <= SLA_latency, Tenants_b <= Capacity_b
MD

cat > "$ROOT/experiments/throughput/run_lr_ci_wasm.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
source .venv/bin/activate
python scripts/ci/servingMetricsPlusCI.py --name wasm_real_lr_c32 --url http://localhost:8010/infer --body '{"f1":6.3,"f2":3.3,"f3":6.0,"f4":2.5}' --concurrency 32 --duration-s 5 --warmup 1 --repeat-min 20 --repeat-max 60 --rel-precision 0.025 --cooldown-s 1
SH
cat > "$ROOT/experiments/throughput/run_lr_ci_docker.sh" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
source .venv/bin/activate
python scripts/ci/servingMetricsPlusCI.py --name docker_real_lr_c32 --url http://localhost:8086/infer --body '{"f1":6.3,"f2":3.3,"f3":6.0,"f4":2.5}' --concurrency 32 --duration-s 5 --warmup 1 --repeat-min 20 --repeat-max 60 --rel-precision 0.025 --cooldown-s 1
SH
chmod +x "$ROOT/experiments/throughput/"*.sh

if command -v docker >/dev/null 2>&1; then
  cd "$ROOT/docker/lr_server"
  docker build -t docker-lr-server . || true
fi

cat > "$ROOT/docs/QUICKSTART.md" <<'MD'
# Quickstart

```bash
cd /home/sallar/wasiMultitenant
source .venv/bin/activate
```

## Run Wasm LR server

```bash
cd /home/sallar/wasiMultitenant/serving/wasm_server/host_lr_server
cargo run --release
```

Test:

```bash
curl -X POST http://localhost:8010/infer -H "Content-Type: application/json" -d '{"f1":6.3,"f2":3.3,"f3":6.0,"f4":2.5}'
```

## Run Docker LR server

```bash
cd /home/sallar/wasiMultitenant/docker/lr_server
docker build -t docker-lr-server .
docker run -d -p 8086:8085 --name docker_lr_test docker-lr-server
```

Test:

```bash
curl -X POST http://localhost:8086/infer -H "Content-Type: application/json" -d '{"f1":6.3,"f2":3.3,"f3":6.0,"f4":2.5}'
```

## CI throughput experiments

```bash
./experiments/throughput/run_lr_ci_wasm.sh
./experiments/throughput/run_lr_ci_docker.sh
```

## Cold start experiments

```bash
for i in {1..20}; do ./experiments/coldstart/wasm_lr_coldstart.sh; done | tee results/coldstart/wasm_lr_coldstart_results.txt
for i in {1..20}; do ./experiments/coldstart/docker_lr_coldstart.sh; done | tee results/coldstart/docker_lr_coldstart_results.txt
```

## COMET-Wasm scheduler skeleton

```bash
python comet/scoring/comet_score.py
```
MD

cd "$ROOT"
echo "============================================================"
echo " COMET-Wasm Framework Installation Complete"
echo "============================================================"
echo "Root: $ROOT"
echo "Next: source .venv/bin/activate && cat docs/QUICKSTART.md"
