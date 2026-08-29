#!/usr/bin/env python3

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

m = json.loads(
    (ROOT / "models/svm/breast_cancer/model.json").read_text()
)

N_FEATURES = len(m["mean"])
N_SV = m["n_support_total"]

support_flat = [
    value
    for row in m["support_vectors"]
    for value in row
]

def f32_array(values):
    return "[" + ", ".join(
        f"{float(v):.10e}f32" for v in values
    ) + "]"

code = f'''use axum::{{extract::Json, routing::post, Router}};
use serde::{{Deserialize, Serialize}};
use std::{{net::SocketAddr, time::Instant}};

const N_FEATURES: usize = {N_FEATURES};
const N_SV: usize = {N_SV};
const N_SV_VALUES: usize = N_FEATURES * N_SV;

const GAMMA: f32 =
    {float(m["gamma"]):.10e}f32;

const INTERCEPT: f32 =
    {float(m["intercept"]):.10e}f32;

const MEAN: [f32; N_FEATURES] =
    {f32_array(m["mean"])};

const SCALE: [f32; N_FEATURES] =
    {f32_array(m["scale"])};

const SUPPORT_VECTORS: [f32; N_SV_VALUES] =
    {f32_array(support_flat)};

const DUAL_COEF: [f32; N_SV] =
    {f32_array(m["dual_coef"])};

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

fn predict_svm(input: &[f32]) -> i32 {{

    let mut decision = INTERCEPT;
    let mut sv = 0usize;

    while sv < N_SV {{

        let mut distance_sq = 0.0f32;
        let mut f = 0usize;

        while f < N_FEATURES {{

            let x =
                (input[f] - MEAN[f]) /
                SCALE[f];

            let sv_value =
                SUPPORT_VECTORS[
                    sv * N_FEATURES + f
                ];

            let diff = x - sv_value;

            distance_sq += diff * diff;

            f += 1;
        }}

        let kernel =
            (-GAMMA * distance_sq).exp();

        decision +=
            DUAL_COEF[sv] * kernel;

        sv += 1;
    }}

    if decision > 0.0f32 {{
        1
    }} else {{
        0
    }}
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

    let prediction =
        predict_svm(&payload.features);

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

    println!("Starting Native Docker SVM-RBF Server");

    let app =
        Router::new().route("/infer", post(infer));

    let addr =
        SocketAddr::from(([0,0,0,0], 8085));

    println!(
        "Docker SVM server listening on http://{{}}",
        addr
    );

    let listener =
        tokio::net::TcpListener::bind(addr).await?;

    axum::serve(listener, app).await?;

    Ok(())
}}
'''

out = Path(__file__).parent / "src/main.rs"
out.write_text(code)

print("Generated:", out)
print("Features:", N_FEATURES)
print("Support vectors:", N_SV)
print("Packed SV values:", len(support_flat))
