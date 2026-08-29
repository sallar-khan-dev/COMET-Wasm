use axum::{extract::Json, routing::post, Router};
use serde::{Deserialize, Serialize};
use std::{net::SocketAddr, time::Instant};

const K: usize = 3;
const D: usize = 4;

const CENTROIDS: [[f32; D]; K] =
[
    [5.9016129032e+00f32, 2.7483870968e+00f32, 4.3935483871e+00f32, 1.4338709677e+00f32],
    [5.0060000000e+00f32, 3.4280000000e+00f32, 1.4620000000e+00f32, 2.4600000000e-01f32],
    [6.8500000000e+00f32, 3.0736842105e+00f32, 5.7421052632e+00f32, 2.0710526316e+00f32]
];

#[derive(Deserialize)]
struct InferenceRequest {
    features: Vec<f32>,
}

#[derive(Serialize)]
struct InferenceResponse {
    prediction: i32,
    inference_time_ns: u128,
    execution_time_ns: u128,
}

fn predict_kmeans(input: &[f32]) -> i32 {
    let mut best_cluster = 0usize;
    let mut best_distance = f32::INFINITY;

    let mut c = 0usize;

    while c < K {
        let mut distance = 0.0f32;
        let mut i = 0usize;

        while i < D {
            let diff = input[i] - CENTROIDS[c][i];
            distance += diff * diff;
            i += 1;
        }

        if distance < best_distance {
            best_distance = distance;
            best_cluster = c;
        }

        c += 1;
    }

    best_cluster as i32
}

async fn infer(
    Json(payload): Json<InferenceRequest>
) -> Result<Json<InferenceResponse>, (axum::http::StatusCode, String)> {

    if payload.features.len() != D {
        return Err((
            axum::http::StatusCode::BAD_REQUEST,
            format!("Expected {} features, received {}", D, payload.features.len())
        ));
    }

    let start = Instant::now();
    let execution_start =
        Instant::now();

    let prediction =
        predict_kmeans(&payload.features);

    let execution_time_ns =
        execution_start.elapsed().as_nanos();

    Ok(Json(InferenceResponse {
        prediction,
        inference_time_ns: start.elapsed().as_nanos(),
        execution_time_ns,
    }))
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {

    println!("Starting Native Docker K-Means Server");

    let app = Router::new()
        .route("/infer", post(infer));

    let addr = SocketAddr::from(([0,0,0,0], 8085));

    println!("Docker K-Means server listening on http://{}", addr);

    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;

    Ok(())
}
