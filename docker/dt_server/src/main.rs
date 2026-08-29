use axum::{extract::Json, routing::post, Router};
use serde::{Deserialize, Serialize};
use std::{net::SocketAddr, time::Instant};

const N_FEATURES: usize = 30;
const N_NODES: usize = 31;

const MEAN: [f32; N_FEATURES] =
    [1.4093846734e+01f32, 1.9341532663e+01f32, 9.1698944724e+01f32, 6.5078417085e+02f32, 9.5789271357e-02f32, 1.0314344221e-01f32, 8.8445768090e-02f32, 4.8048728643e-02f32, 1.8049296482e-01f32, 6.2709572864e-02f32, 3.9191708543e-01f32, 1.1979816583e+00f32, 2.7735881910e+00f32, 3.8215334171e+01f32, 6.9815025126e-03f32, 2.5361748744e-02f32, 3.2184890955e-02f32, 1.1531678392e-02f32, 2.0681623116e-02f32, 3.8061535176e-03f32, 1.6266560302e+01f32, 2.5816306533e+01f32, 1.0722067839e+02f32, 8.7969673367e+02f32, 1.3225909548e-01f32, 2.5716997487e-01f32, 2.7870954020e-01f32, 1.1448460050e-01f32, 2.9293768844e-01f32, 8.4229221106e-02f32];

const SCALE: [f32; N_FEATURES] =
    [3.4851709336e+00f32, 4.4947997773e+00f32, 2.4033630664e+01f32, 3.3986740760e+02f32, 1.3332303375e-02f32, 5.3295364002e-02f32, 8.1406440023e-02f32, 3.8648249082e-02f32, 2.8020223328e-02f32, 7.3046229300e-03f32, 2.3050050777e-01f32, 5.4148989791e-01f32, 1.7050214018e+00f32, 3.4268918774e+01f32, 3.0305670786e-03f32, 1.8678246920e-02f32, 3.3409656712e-02f32, 6.3459312357e-03f32, 8.7387637721e-03f32, 2.9068455555e-03f32, 4.8437163221e+00f32, 6.3203664321e+00f32, 3.3731614256e+01f32, 5.6471107320e+02f32, 2.2652731966e-02f32, 1.6449859681e-01f32, 2.2138310416e-01f32, 6.7630781826e-02f32, 6.5055190614e-02f32, 1.9025909711e-02f32];

const CHILDREN_LEFT: [i32; N_NODES] =
    [1, 2, 3, 4, -1, -1, 7, 8, -1, 10, -1, -1, 13, 14, -1, -1, -1, 18, 19, -1, -1, 22, -1, -1, 25, -1, 27, 28, -1, -1, -1];

const CHILDREN_RIGHT: [i32; N_NODES] =
    [24, 17, 6, 5, -1, -1, 12, 9, -1, 11, -1, -1, 16, 15, -1, -1, -1, 21, 20, -1, -1, 23, -1, -1, 26, -1, 30, 29, -1, -1, -1];

const FEATURE: [i32; N_NODES] =
    [20, 27, 14, 29, -2, -2, 13, 21, -2, 21, -2, -2, 24, 15, -2, -2, -2, 21, 20, -2, -2, 9, -2, -2, 11, -2, 26, 21, -2, -2, -2];

const THRESHOLD: [f32; N_NODES] =
    [1.0909798369e-01f32, 4.2385137081e-01f32, -1.2167698145e+00f32, -7.0583856106e-01f32, -2.0000000000e+00f32, -2.0000000000e+00f32, -8.1132825464e-02f32, 1.1793134809e+00f32, -2.0000000000e+00f32, 1.2631694078e+00f32, -2.0000000000e+00f32, -2.0000000000e+00f32, 5.8451689780e-01f32, -8.1092989445e-01f32, -2.0000000000e+00f32, -2.0000000000e+00f32, -2.0000000000e+00f32, -3.2851047814e-01f32, -3.8515943103e-02f32, -2.0000000000e+00f32, -2.0000000000e+00f32, -2.5046780705e-01f32, -2.0000000000e+00f32, -2.0000000000e+00f32, -1.3729372621e+00f32, -2.0000000000e+00f32, -3.9754407108e-01f32, 8.1620165706e-01f32, -2.0000000000e+00f32, -2.0000000000e+00f32, -2.0000000000e+00f32];

const LEAF_CLASS: [i32; N_NODES] =
    [1, 1, 1, 1, 1, 0, 1, 1, 1, 1, 0, 1, 1, 1, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0, 0, 1, 0, 1, 1, 0, 0];

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

fn predict_dt(input: &[f32]) -> i32 {

    let mut node: usize = 0;

    loop {

        let left = CHILDREN_LEFT[node];
        let right = CHILDREN_RIGHT[node];

        if left == -1 && right == -1 {
            return LEAF_CLASS[node];
        }

        let feature = FEATURE[node];

        if feature < 0 {
            return LEAF_CLASS[node];
        }

        let idx = feature as usize;

        let x =
            (input[idx] - MEAN[idx]) /
            SCALE[idx];

        if x <= THRESHOLD[node] {
            node = left as usize;
        } else {
            node = right as usize;
        }
    }
}

async fn infer(
    Json(payload): Json<InferenceRequest>
) -> Result<Json<InferenceResponse>, (axum::http::StatusCode, String)> {

    if payload.features.len() != N_FEATURES {
        return Err((
            axum::http::StatusCode::BAD_REQUEST,
            format!(
                "Expected {} features, received {}",
                N_FEATURES,
                payload.features.len()
            )
        ));
    }

    let start = Instant::now();

    let execution_start =
        Instant::now();

    let prediction =
        predict_dt(&payload.features);

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

    println!("Starting Native Docker Decision Tree Server");

    let app =
        Router::new().route("/infer", post(infer));

    let addr =
        SocketAddr::from(([0, 0, 0, 0], 8085));

    println!(
        "Docker DT server listening on http://{}",
        addr
    );

    let listener =
        tokio::net::TcpListener::bind(addr).await?;

    axum::serve(listener, app).await?;

    Ok(())
}
