use anyhow::Result;

use axum::{
    extract::State,
    http::StatusCode,
    routing::{get, post},
    Json,
    Router,
};

use comet_worker_pool::WasmWorkerPool;

use serde::{Deserialize, Serialize};

use std::{
    env,
    net::SocketAddr,
    sync::Arc,
    time::Instant,
};

use wasmtime::{Engine, Module};


#[derive(Clone)]
struct AppState {
    pool: Arc<WasmWorkerPool>,
    model_name: String,
    worker_count: usize,
}


#[derive(Deserialize)]
struct InferenceRequest {
    tenant_id: u64,
    features: Vec<f32>,
}


#[derive(Serialize)]
struct InferenceResponse {
    tenant_id: u64,
    worker_id: usize,
    prediction: i32,
    inference_time_ns: u128,
    execution_time_ns: u128,
}


#[derive(Serialize)]
struct HealthResponse {
    status: String,
}


#[derive(Serialize)]
struct MetadataResponse {
    model: String,
    workers: usize,
    backend: String,
    isolation: String,
}


async fn health() -> Json<HealthResponse> {
    Json(HealthResponse {
        status: "ok".to_string(),
    })
}


async fn metadata(
    State(state): State<AppState>,
) -> Json<MetadataResponse> {
    Json(MetadataResponse {
        model: state.model_name.clone(),
        workers: state.worker_count,
        backend: "wasmtime".to_string(),
        isolation: "independent_store_instance".to_string(),
    })
}


async fn infer(
    State(state): State<AppState>,
    Json(payload): Json<InferenceRequest>,
) -> Result<Json<InferenceResponse>, (StatusCode, String)> {

    if state.pool.is_empty() {
        return Err((
            StatusCode::SERVICE_UNAVAILABLE,
            "Worker pool is empty".to_string(),
        ));
    }

    let worker_id =
        (payload.tenant_id as usize) % state.worker_count;

    let worker = state
        .pool
        .worker_for_tenant(payload.tenant_id)
        .ok_or_else(|| (
            StatusCode::SERVICE_UNAVAILABLE,
            "No worker available".to_string(),
        ))?;

    let start = Instant::now();

    let (prediction, execution_time_ns) = {
        let mut worker = worker
            .lock()
            .map_err(|_| (
                StatusCode::INTERNAL_SERVER_ERROR,
                "Worker lock poisoned".to_string(),
            ))?;

        worker
            .infer_timed(&payload.features)
            .map_err(|e| (
                StatusCode::BAD_REQUEST,
                format!("Inference failed: {e}")
            ))?
    };

    Ok(Json(InferenceResponse {
        tenant_id: payload.tenant_id,
        worker_id,
        prediction,
        inference_time_ns: start.elapsed().as_nanos(),
        execution_time_ns,
    }))
}


#[tokio::main]
async fn main() -> Result<()> {

    let args: Vec<String> = env::args().collect();

    if args.len() != 5 {
        eprintln!(
            "Usage: {} <model_name> <wasm_path> <workers> <port>",
            args[0]
        );

        std::process::exit(1);
    }

    let model_name = args[1].clone();
    let wasm_path = &args[2];

    let worker_count: usize =
        args[3].parse()?;

    let port: u16 =
        args[4].parse()?;

    println!("Starting COMET-Wasm Multi-Tenant Server");
    println!("Model: {}", model_name);
    println!("Wasm: {}", wasm_path);
    println!("Workers: {}", worker_count);

    let engine = Engine::default();

    let module =
        Module::from_file(&engine, wasm_path)?;

    let pool =
        WasmWorkerPool::new(
            &engine,
            &module,
            worker_count
        )?;

    println!(
        "Created {} independent Wasmtime workers",
        pool.len()
    );

    let state = AppState {
        pool: Arc::new(pool),
        model_name,
        worker_count,
    };

    let app = Router::new()
        .route("/health", get(health))
        .route("/metadata", get(metadata))
        .route("/infer", post(infer))
        .with_state(state);

    let addr =
        SocketAddr::from(
            ([0, 0, 0, 0], port)
        );

    println!(
        "Multi-tenant server listening on http://{}",
        addr
    );

    let listener =
        tokio::net::TcpListener::bind(addr).await?;

    axum::serve(listener, app).await?;

    Ok(())
}
