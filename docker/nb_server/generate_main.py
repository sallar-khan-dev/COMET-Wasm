#!/usr/bin/env python3

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODEL = ROOT / "models" / "naive_bayes" / "breast_cancer" / "model.json"

m = json.loads(MODEL.read_text())

n_features = len(m["mean"])
n_classes = len(m["classes"])

def arr1(values):
    return "[" + ", ".join(f"{float(v):.10e}f32" for v in values) + "]"

def arr2(rows):
    return "[\n" + ",\n".join(
        "    " + arr1(row) for row in rows
    ) + "\n]"

code = f'''use axum::{{extract::Json, routing::post, Router}};
use serde::{{Deserialize, Serialize}};
use std::{{net::SocketAddr, time::Instant}};

const N_FEATURES: usize = {n_features};
const N_CLASSES: usize = {n_classes};

const MEAN: [f32; N_FEATURES] = {arr1(m["mean"])};
const SCALE: [f32; N_FEATURES] = {arr1(m["scale"])};
const CLASS_PRIOR: [f32; N_CLASSES] = {arr1(m["class_prior"])};
const THETA: [[f32; N_FEATURES]; N_CLASSES] = {arr2(m["theta"])};
const VAR: [[f32; N_FEATURES]; N_CLASSES] = {arr2(m["var"])};

#[derive(Deserialize)]
struct InferenceRequest {{
    features: Vec<f32>,
}}

#[derive(Serialize)]
struct InferenceResponse {{
    prediction: i32,
    inference_time_ns: u128,
    execution_time_ns: u128,
}}

fn predict_nb(input: &[f32]) -> i32 {{
    let mut best_class = 0usize;
    let mut best_log_prob = f32::NEG_INFINITY;

    let mut c = 0usize;

    while c < N_CLASSES {{
        let mut log_prob = CLASS_PRIOR[c].ln();

        let mut i = 0usize;

        while i < N_FEATURES {{
            let x = (input[i] - MEAN[i]) / SCALE[i];
            let variance = VAR[c][i];
            let diff = x - THETA[c][i];

            log_prob += -0.5f32 * (
                (2.0f32 * std::f32::consts::PI * variance).ln()
                + ((diff * diff) / variance)
            );

            i += 1;
        }}

        if log_prob > best_log_prob {{
            best_log_prob = log_prob;
            best_class = c;
        }}

        c += 1;
    }}

    best_class as i32
}}

async fn infer(
    Json(payload): Json<InferenceRequest>
) -> Result<Json<InferenceResponse>, (axum::http::StatusCode, String)> {{

    if payload.features.len() != N_FEATURES {{
        return Err((
            axum::http::StatusCode::BAD_REQUEST,
            format!(
                "Expected {{}} features, received {{}}",
                N_FEATURES,
                payload.features.len()
            )
        ));
    }}

    let start = Instant::now();

    let execution_start =
        Instant::now();

    let prediction = predict_nb(&payload.features);

    let execution_time_ns =
        execution_start.elapsed().as_nanos();

    Ok(Json(InferenceResponse {{
        prediction,
        inference_time_ns: start.elapsed().as_nanos(),
        execution_time_ns,
    }}))
}}

#[tokio::main]
async fn main() -> anyhow::Result<()> {{
    println!("Starting Native Docker Gaussian NB Server");

    let app = Router::new().route("/infer", post(infer));

    let addr = SocketAddr::from(([0, 0, 0, 0], 8085));

    println!("Docker NB server listening on http://{{}}", addr);

    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;

    Ok(())
}}
'''

out = Path(__file__).parent / "src" / "main.rs"
out.write_text(code)

print("Generated:", out)
print("Features:", n_features)
print("Classes:", n_classes)
