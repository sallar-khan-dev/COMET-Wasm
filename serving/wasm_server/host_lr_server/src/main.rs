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
