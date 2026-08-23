use axum::{extract::Json, routing::post, Router};
use serde::{Deserialize, Serialize};
use std::{net::SocketAddr, time::Instant};
#[derive(Deserialize)]
struct InferenceRequest { f1: f32, f2: f32, f3: f32, f4: f32 }
#[derive(Serialize)]
struct InferenceResponse { prediction: i32, inference_time_ns: u128 }
async fn infer(Json(payload): Json<InferenceRequest>) -> Json<InferenceResponse> {
    let start = Instant::now();
    let weights: [f32; 4] = [0.5435686295f32, -0.3396157602f32, 1.878629174f32, 2.737636864f32];
    let mean: [f32; 4] = [5.835238095f32, 3.098095238f32, 3.697142857f32, 1.179047619f32];
    let scale: [f32; 4] = [0.8678359459f32, 0.4318246894f32, 1.841503379f32, 0.7945882717f32];
    let input: [f32; 4] = [payload.f1, payload.f2, payload.f3, payload.f4];
    let mut z: f32 = -3.441903479f32;
    for i in 0..4 {
        let x_scaled = (input[i] - mean[i]) / scale[i];
        z += weights[i] * x_scaled;
    }
    let probability = 1.0f32 / (1.0f32 + (-z).exp());
    let prediction = if probability >= 0.5 { 1 } else { 0 };
    Json(InferenceResponse { prediction, inference_time_ns: start.elapsed().as_nanos() })
}
#[tokio::main]
async fn main() -> anyhow::Result<()> {
    println!("Starting Native Docker LR Server");
    let app = Router::new().route("/infer", post(infer));
    let addr = SocketAddr::from(([0, 0, 0, 0], 8085));
    println!("Docker LR server listening on http://{}", addr);
    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;
    Ok(())
}
