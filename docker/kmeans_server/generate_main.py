#!/usr/bin/env python3

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

m = json.loads(
    (ROOT / "models/kmeans/iris/model.json").read_text()
)

K = m["n_clusters"]
D = m["n_features"]

def arr1(values):
    return "[" + ", ".join(
        f"{float(v):.10e}f32" for v in values
    ) + "]"

def arr2(rows):
    return "[\n" + ",\n".join(
        "    " + arr1(row) for row in rows
    ) + "\n]"

code = f'''use axum::{{extract::Json, routing::post, Router}};
use serde::{{Deserialize, Serialize}};
use std::{{net::SocketAddr, time::Instant}};

const K: usize = {K};
const D: usize = {D};

const CENTROIDS: [[f32; D]; K] =
{arr2(m["centroids"])};

#[derive(Deserialize)]
struct InferenceRequest {{
    features: Vec<f32>,
}}

#[derive(Serialize)]
struct InferenceResponse {{
    prediction: i32,
    inference_time_ns: u128,
}}

fn predict_kmeans(input: &[f32]) -> i32 {{
    let mut best_cluster = 0usize;
    let mut best_distance = f32::INFINITY;

    let mut c = 0usize;

    while c < K {{
        let mut distance = 0.0f32;
        let mut i = 0usize;

        while i < D {{
            let diff = input[i] - CENTROIDS[c][i];
            distance += diff * diff;
            i += 1;
        }}

        if distance < best_distance {{
            best_distance = distance;
            best_cluster = c;
        }}

        c += 1;
    }}

    best_cluster as i32
}}

async fn infer(
    Json(payload): Json<InferenceRequest>
) -> Result<Json<InferenceResponse>, (axum::http::StatusCode, String)> {{

    if payload.features.len() != D {{
        return Err((
            axum::http::StatusCode::BAD_REQUEST,
            format!("Expected {{}} features, received {{}}", D, payload.features.len())
        ));
    }}

    let start = Instant::now();
    let prediction = predict_kmeans(&payload.features);

    Ok(Json(InferenceResponse {{
        prediction,
        inference_time_ns: start.elapsed().as_nanos(),
    }}))
}}

#[tokio::main]
async fn main() -> anyhow::Result<()> {{

    println!("Starting Native Docker K-Means Server");

    let app = Router::new()
        .route("/infer", post(infer));

    let addr = SocketAddr::from(([0,0,0,0], 8085));

    println!("Docker K-Means server listening on http://{{}}", addr);

    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;

    Ok(())
}}
'''

out = Path(__file__).parent / "src/main.rs"
out.write_text(code)

print("Generated:", out)
print("Clusters:", K)
print("Features:", D)
