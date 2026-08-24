#!/usr/bin/env python3

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

m = json.loads(
    (ROOT / "models/mlp/breast_cancer/model.json").read_text()
)

N_INPUT = 30
N_HIDDEN = 32

w1 = [
    value
    for row in m["weights"][0]
    for value in row
]

w2 = [
    row[0]
    for row in m["weights"][1]
]

b1 = m["biases"][0]
b2 = m["biases"][1][0]

def f32_array(values):
    return "[" + ", ".join(
        f"{float(v):.10e}f32" for v in values
    ) + "]"

code = f'''use axum::{{extract::Json, routing::post, Router}};
use serde::{{Deserialize, Serialize}};
use std::{{net::SocketAddr, time::Instant}};

const N_INPUT: usize = {N_INPUT};
const N_HIDDEN: usize = {N_HIDDEN};

const MEAN: [f32; N_INPUT] =
    {f32_array(m["mean"])};

const SCALE: [f32; N_INPUT] =
    {f32_array(m["scale"])};

const W1: [f32; N_INPUT * N_HIDDEN] =
    {f32_array(w1)};

const B1: [f32; N_HIDDEN] =
    {f32_array(b1)};

const W2: [f32; N_HIDDEN] =
    {f32_array(w2)};

const B2: f32 =
    {float(b2):.10e}f32;

#[derive(Deserialize)]
struct InferenceRequest {{
    features: Vec<f32>,
}}

#[derive(Serialize)]
struct InferenceResponse {{
    prediction: i32,
    inference_time_ns: u128,
}}

fn predict_mlp(input: &[f32]) -> i32 {{

    let mut hidden = [0.0f32; N_HIDDEN];

    let mut h = 0usize;

    while h < N_HIDDEN {{

        let mut sum = B1[h];
        let mut i = 0usize;

        while i < N_INPUT {{

            let x =
                (input[i] - MEAN[i]) /
                SCALE[i];

            sum +=
                x * W1[i * N_HIDDEN + h];

            i += 1;
        }}

        hidden[h] =
            if sum > 0.0f32 {{
                sum
            }} else {{
                0.0f32
            }};

        h += 1;
    }}

    let mut out = B2;

    h = 0;

    while h < N_HIDDEN {{
        out += hidden[h] * W2[h];
        h += 1;
    }}

    let probability =
        1.0f32 /
        (1.0f32 + (-out).exp());

    if probability >= 0.5f32 {{
        1
    }} else {{
        0
    }}
}}

async fn infer(
    Json(payload): Json<InferenceRequest>
) -> Result<Json<InferenceResponse>, (axum::http::StatusCode, String)> {{

    if payload.features.len() != N_INPUT {{
        return Err((
            axum::http::StatusCode::BAD_REQUEST,
            format!(
                "Expected {{}} features, received {{}}",
                N_INPUT,
                payload.features.len()
            )
        ));
    }}

    let start = Instant::now();

    let prediction =
        predict_mlp(&payload.features);

    Ok(Json(InferenceResponse {{
        prediction,
        inference_time_ns: start.elapsed().as_nanos(),
    }}))
}}

#[tokio::main]
async fn main() -> anyhow::Result<()> {{

    println!("Starting Native Docker MLP Server");

    let app =
        Router::new().route("/infer", post(infer));

    let addr =
        SocketAddr::from(([0,0,0,0], 8085));

    println!(
        "Docker MLP server listening on http://{{}}",
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
print("Input:", N_INPUT)
print("Hidden:", N_HIDDEN)
print("W1 values:", len(w1))
print("W2 values:", len(w2))
