mod docker_adapter;
mod routes;
mod wasm_adapter;

use axum::{
    extract::State,
    http::StatusCode,
    routing::{get, post},
    Json, Router,
};
use docker_adapter::DockerAdapter;
use routes::{load_routes, Backend, RouteTable};
use serde::{Deserialize, Serialize};
use std::{net::SocketAddr, sync::Arc, time::Instant};
use wasm_adapter::WasmAdapter;

#[derive(Clone)]
struct AppState {
    routes: Arc<RouteTable>,
    wasm_lr: Option<WasmAdapter>,
    docker: DockerAdapter,
}

#[derive(Debug, Deserialize)]
struct InferenceRequest {
    request_id: String,
    tenant_id: u64,
    model: String,
    features: Vec<f32>,
}

#[derive(Debug, Serialize)]
struct InferenceResponse {
    request_id: String,
    tenant_id: u64,
    model: String,
    backend: &'static str,
    worker_id: Option<usize>,
    prediction: i32,
    inference_time_ns: u128,
    execution_time_ns: u128,
    request_total_ns: u128,
    adapter_roundtrip_ns: Option<u128>,
}

#[derive(Debug, Serialize)]
struct ErrorResponse {
    error: &'static str,
    request_id: Option<String>,
    tenant_id: Option<u64>,
}

async fn noop() -> StatusCode {
    StatusCode::NO_CONTENT
}

async fn health() -> &'static str {
    "ok"
}

async fn infer(
    State(state): State<AppState>,
    Json(request): Json<InferenceRequest>,
) -> Result<Json<InferenceResponse>, (StatusCode, Json<ErrorResponse>)> {
    let request_start = Instant::now();
    let request_id = Some(request.request_id.clone());
    let tenant_id = Some(request.tenant_id);

    if request.request_id.trim().is_empty()
        || request.model.trim().is_empty()
        || request.features.is_empty()
        || request.features.iter().any(|x| !x.is_finite())
    {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(ErrorResponse {
                error: "invalid_inference_request",
                request_id,
                tenant_id,
            }),
        ));
    }

    let tenant_key = request.tenant_id.to_string();

    let route = state.routes.get(&tenant_key).ok_or_else(|| {
        (
            StatusCode::NOT_FOUND,
            Json(ErrorResponse {
                error: "tenant_not_admitted",
                request_id: Some(request.request_id.clone()),
                tenant_id,
            }),
        )
    })?;

    if request.model != route.model {
        return Err((
            StatusCode::BAD_REQUEST,
            Json(ErrorResponse {
                error: "model_route_mismatch",
                request_id: Some(request.request_id),
                tenant_id,
            }),
        ));
    }

    if matches!(route.backend, Backend::Docker | Backend::Native) {
        let url = route.url.as_deref().ok_or_else(|| {
            (
                StatusCode::INTERNAL_SERVER_ERROR,
                Json(ErrorResponse {
                    error: "external_route_missing_url",
                    request_id: Some(request.request_id.clone()),
                    tenant_id,
                }),
            )
        })?;

        let result = state
            .docker
            .infer(url, &request.features)
            .await
            .map_err(|_| {
                (
                    StatusCode::BAD_GATEWAY,
                    Json(ErrorResponse {
                        error: "external_inference_failed",
                        request_id: Some(request.request_id.clone()),
                        tenant_id,
                    }),
                )
            })?;

        return Ok(Json(InferenceResponse {
            request_id: request.request_id,
            tenant_id: request.tenant_id,
            model: route.model.clone(),
            backend: if route.backend == Backend::Docker {
                "docker"
            } else {
                "native"
            },
            worker_id: None,
            prediction: result.prediction,
            inference_time_ns: result.inference_time_ns,
            execution_time_ns: result.execution_time_ns,
            request_total_ns: request_start.elapsed().as_nanos(),
            adapter_roundtrip_ns: Some(result.adapter_roundtrip_ns),
        }));
    }

    if route.backend != Backend::Wasmtime || route.model != "lr" {
        return Err((
            StatusCode::NOT_IMPLEMENTED,
            Json(ErrorResponse {
                error: "backend_adapter_not_implemented",
                request_id: Some(request.request_id),
                tenant_id,
            }),
        ));
    }

    let adapter = state.wasm_lr.as_ref().ok_or_else(|| {
        (
            StatusCode::SERVICE_UNAVAILABLE,
            Json(ErrorResponse {
                error: "wasmtime_adapter_unavailable",
                request_id: Some(request.request_id.clone()),
                tenant_id,
            }),
        )
    })?;

    let result = adapter
        .infer(request.tenant_id, request.features)
        .await
        .map_err(|_| {
            (
                StatusCode::UNPROCESSABLE_ENTITY,
                Json(ErrorResponse {
                    error: "wasmtime_inference_failed",
                    request_id: Some(request.request_id.clone()),
                    tenant_id,
                }),
            )
        })?;

    Ok(Json(InferenceResponse {
        request_id: request.request_id,
        tenant_id: request.tenant_id,
        model: route.model.clone(),
        backend: "wasmtime",
        worker_id: Some(result.worker_id),
        prediction: result.prediction,
        inference_time_ns: result.inference_time_ns,
        execution_time_ns: result.execution_time_ns,
        request_total_ns: request_start.elapsed().as_nanos(),
        adapter_roundtrip_ns: None,
    }))
}

fn main() -> anyhow::Result<()> {
    let workers: usize = std::env::var("COMET_INGRESS_WORKERS")
        .unwrap_or_else(|_| "2".to_string())
        .parse()?;
    anyhow::ensure!(
        workers > 0 && workers <= 32,
        "COMET_INGRESS_WORKERS must be 1..32"
    );
    println!("Ingress Tokio workers: {workers}");
    tokio::runtime::Builder::new_multi_thread()
        .worker_threads(workers)
        .enable_all()
        .build()?
        .block_on(serve())
}

async fn serve() -> anyhow::Result<()> {
    let routes_path = std::env::args()
        .nth(1)
        .unwrap_or_else(|| "research_enhancement/routes.example.json".to_string());

    let routes = load_routes(&routes_path)?;

    println!(
        "Loaded {} admitted tenant routes from {}",
        routes.len(),
        routes_path
    );

    let wasm_lr = if routes
        .values()
        .any(|route| route.backend == Backend::Wasmtime && route.model == "lr")
    {
        let path = std::env::var("COMET_LR_WASM_PATH").map_err(|_| {
            anyhow::anyhow!("COMET_LR_WASM_PATH is required for LR Wasmtime routes")
        })?;

        let workers: usize = std::env::var("COMET_WASM_WORKERS")
            .unwrap_or_else(|_| "2".to_string())
            .parse()?;

        Some(WasmAdapter::new(&path, workers)?)
    } else {
        None
    };

    let state = AppState {
        routes: Arc::new(routes),
        wasm_lr,
        docker: DockerAdapter::new(),
    };

    let app = Router::new()
        .route("/health", get(health))
        .route("/noop", get(noop))
        .route("/infer", post(infer))
        .with_state(state);

    let addr = SocketAddr::from(([127, 0, 0, 1], 8200));
    let listener = tokio::net::TcpListener::bind(addr).await?;

    println!("COMET-Wasm V2 common ingress listening on {addr}");

    axum::serve(listener, app).await?;

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use routes::{Backend, TenantRoute};
    use std::collections::HashMap;

    fn test_state() -> AppState {
        let mut routes = HashMap::new();

        routes.insert(
            "0".to_string(),
            TenantRoute {
                backend: Backend::Wasmtime,
                model: "lr".to_string(),
                url: None,
            },
        );

        AppState {
            routes: Arc::new(routes),
            wasm_lr: None,
            docker: DockerAdapter::new(),
        }
    }

    fn request(tenant_id: u64) -> InferenceRequest {
        InferenceRequest {
            request_id: "test-001".to_string(),
            tenant_id,
            model: "lr".to_string(),
            features: vec![1.0, 2.0, 3.0, 4.0],
        }
    }

    #[tokio::test]
    async fn noop_returns_204() {
        assert_eq!(noop().await, StatusCode::NO_CONTENT);
    }

    #[tokio::test]
    async fn health_returns_ok() {
        assert_eq!(health().await, "ok");
    }

    #[tokio::test]
    async fn admitted_tenant_reaches_adapter_boundary() {
        let result = infer(State(test_state()), Json(request(0))).await;
        let (status, body) = result.err().unwrap();

        assert_eq!(status, StatusCode::SERVICE_UNAVAILABLE);
        assert_eq!(body.0.error, "wasmtime_adapter_unavailable");
    }

    #[tokio::test]
    async fn unknown_tenant_is_rejected() {
        let result = infer(State(test_state()), Json(request(99))).await;
        let (status, body) = result.err().unwrap();

        assert_eq!(status, StatusCode::NOT_FOUND);
        assert_eq!(body.0.error, "tenant_not_admitted");
    }

    #[tokio::test]
    async fn empty_features_are_rejected() {
        let mut req = request(0);
        req.features.clear();

        let result = infer(State(test_state()), Json(req)).await;
        let (status, body) = result.err().unwrap();

        assert_eq!(status, StatusCode::BAD_REQUEST);
        assert_eq!(body.0.error, "invalid_inference_request");
    }
}
