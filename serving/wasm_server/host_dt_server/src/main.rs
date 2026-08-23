use anyhow::{bail, Result};
use axum::{
    extract::State,
    http::StatusCode,
    routing::post,
    Json, Router,
};
use serde::{Deserialize, Serialize};
use std::{
    net::SocketAddr,
    sync::{Arc, Mutex},
    time::Instant,
};
use wasmtime::{Engine, Instance, Memory, Module, Store, TypedFunc};

const N_FEATURES: usize = 30;

#[derive(Clone)]
struct AppState {
    runtime: Arc<Mutex<WasmRuntime>>,
}

struct WasmRuntime {
    store: Store<()>,
    memory: Memory,
    input_ptr: usize,
    predict: TypedFunc<(), i32>,
}

#[derive(Deserialize)]
struct InferenceRequest {
    features: Vec<f32>,
}

#[derive(Serialize)]
struct InferenceResponse {
    prediction: i32,
    inference_time_ns: u128,
}

async fn infer(
    State(state): State<AppState>,
    Json(payload): Json<InferenceRequest>,
) -> Result<Json<InferenceResponse>, (StatusCode, String)> {

    if payload.features.len() != N_FEATURES {
        return Err((
            StatusCode::BAD_REQUEST,
            format!(
                "Expected {} features, received {}",
                N_FEATURES,
                payload.features.len()
            ),
        ));
    }

    let start = Instant::now();

    let mut runtime = state.runtime.lock().map_err(|_| (
        StatusCode::INTERNAL_SERVER_ERROR,
        "Runtime lock poisoned".to_string(),
    ))?;

    let mut bytes = Vec::with_capacity(N_FEATURES * 4);

    for value in &payload.features {
        bytes.extend_from_slice(&value.to_le_bytes());
    }

    let input_ptr = runtime.input_ptr;
    let memory = runtime.memory;

    memory
        .write(&mut runtime.store, input_ptr, &bytes)
        .map_err(|e| (
            StatusCode::INTERNAL_SERVER_ERROR,
            format!("Wasm memory write failed: {e}")
        ))?;

    let predict = runtime.predict.clone();

    let prediction = predict
        .call(&mut runtime.store, ())
        .map_err(|e| (
            StatusCode::INTERNAL_SERVER_ERROR,
            format!("Wasm prediction failed: {e}")
        ))?;

    Ok(Json(InferenceResponse {
        prediction,
        inference_time_ns: start.elapsed().as_nanos(),
    }))
}

#[tokio::main]
async fn main() -> Result<()> {

    println!("Starting COMET-Wasm Decision Tree Wasmtime Server");

    let engine = Engine::default();

    let module_path =
        "../../../wasm/tenant_dt_real/target/wasm32-unknown-unknown/release/tenant_dt_real.wasm";

    let module = Module::from_file(&engine, module_path)?;

    let mut store = Store::new(&engine, ());

    let instance = Instance::new(
        &mut store,
        &module,
        &[],
    )?;

    let memory = instance
        .get_memory(&mut store, "memory")
        .ok_or_else(|| anyhow::anyhow!("Wasm module does not export memory"))?;

    let input_ptr_fn = instance
        .get_typed_func::<(), i32>(&mut store, "input_ptr")?;

    let feature_count_fn = instance
        .get_typed_func::<(), i32>(&mut store, "feature_count")?;

    let predict = instance
        .get_typed_func::<(), i32>(&mut store, "predict")?;

    let feature_count = feature_count_fn.call(&mut store, ())?;

    if feature_count != N_FEATURES as i32 {
        bail!(
            "Feature mismatch: host expects {}, guest reports {}",
            N_FEATURES,
            feature_count
        );
    }

    let input_ptr = input_ptr_fn.call(&mut store, ())? as usize;

    println!("DT Wasm module loaded");
    println!("Feature count: {}", feature_count);
    println!("Input pointer: {}", input_ptr);

    let runtime = WasmRuntime {
        store,
        memory,
        input_ptr,
        predict,
    };

    let state = AppState {
        runtime: Arc::new(Mutex::new(runtime)),
    };

    let app = Router::new()
        .route("/infer", post(infer))
        .with_state(state);

    let addr = SocketAddr::from(([0, 0, 0, 0], 8030));

    println!("Wasm DT server listening on http://{}", addr);

    let listener = tokio::net::TcpListener::bind(addr).await?;

    axum::serve(listener, app).await?;

    Ok(())
}
