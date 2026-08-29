import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
m = json.loads((ROOT / "models" / "logistic_regression" / "iris_lr" / "model.json").read_text())
def arr(vals): return "[" + ", ".join(f"{v:.10}f32" for v in vals) + "]"
code = f'''use axum::{{extract::Json, routing::post, Router}};
use serde::{{Deserialize, Serialize}};
use std::{{net::SocketAddr, time::Instant}};
#[derive(Deserialize)]
struct InferenceRequest {{ f1: f32, f2: f32, f3: f32, f4: f32 }}
#[derive(Serialize)]
struct InferenceResponse {{
    prediction: i32,
    inference_time_ns: u128,
    execution_time_ns: u128,
}}

fn predict_lr(input: &[f32; 4]) -> i32 {{
    let weights: [f32; 4] = {arr(m["weights"])};
    let mean: [f32; 4] = {arr(m["mean"])};
    let scale: [f32; 4] = {arr(m["scale"])};

    let mut z: f32 = {m["bias"]:.10}f32;

    for i in 0..4 {{
        let x_scaled =
            (input[i] - mean[i]) / scale[i];

        z += weights[i] * x_scaled;
    }}

    let probability =
        1.0f32 /
        (1.0f32 + (-z).exp());

    if probability >= 0.5 {{
        1
    }} else {{
        0
    }}
}}

async fn infer(
    Json(payload): Json<InferenceRequest>
) -> Json<InferenceResponse> {{

    let start = Instant::now();

    let input: [f32; 4] = [
        payload.f1,
        payload.f2,
        payload.f3,
        payload.f4
    ];

    let execution_start =
        Instant::now();

    let prediction =
        predict_lr(&input);

    let execution_time_ns =
        execution_start.elapsed().as_nanos();

    Json(InferenceResponse {{
        prediction,
        inference_time_ns:
            start.elapsed().as_nanos(),
        execution_time_ns,
    }})
}}
#[tokio::main]
async fn main() -> anyhow::Result<()> {{
    println!("Starting Native Docker LR Server");
    let app = Router::new().route("/infer", post(infer));
    let addr = SocketAddr::from(([0, 0, 0, 0], 8085));
    println!("Docker LR server listening on http://{{}}", addr);
    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;
    Ok(())
}}
'''
Path("src/main.rs").write_text(code)
print("Generated src/main.rs")
