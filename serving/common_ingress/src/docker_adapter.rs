use anyhow::{bail, Context, Result};
use bytes::Bytes;
use http_body_util::{BodyExt, Full};
use hyper::{Method, Request, StatusCode};
use hyper_util::{
    client::legacy::{connect::HttpConnector, Client},
    rt::TokioExecutor,
};
use serde::{Deserialize, Serialize};
use std::time::{Duration, Instant};

#[derive(Clone)]
pub struct DockerAdapter {
    client: Client<HttpConnector, Full<Bytes>>,
}

#[derive(Debug, Serialize)]
struct DockerInferenceRequest<'a> {
    features: &'a [f32],
}

#[derive(Debug, Deserialize)]
struct DockerInferenceResponse {
    prediction: i32,
    inference_time_ns: u128,
    execution_time_ns: u128,
}

#[derive(Debug)]
pub struct DockerInferenceResult {
    pub prediction: i32,
    pub inference_time_ns: u128,
    pub execution_time_ns: u128,
    pub adapter_roundtrip_ns: u128,
}

impl DockerAdapter {
    pub fn new() -> Self {
        let mut connector = HttpConnector::new();
        connector.enforce_http(true);

        let client = Client::builder(TokioExecutor::new())
            .build(connector);

        Self { client }
    }

    pub async fn infer(
        &self,
        url: &str,
        features: &[f32],
    ) -> Result<DockerInferenceResult> {
        if features.is_empty() || features.iter().any(|x| !x.is_finite()) {
            bail!("Invalid Docker inference features");
        }

        let payload = serde_json::to_vec(
            &DockerInferenceRequest { features }
        )?;

        let request = Request::builder()
            .method(Method::POST)
            .uri(url)
            .header("content-type", "application/json")
            .body(Full::new(Bytes::from(payload)))
            .context("Cannot construct Docker inference request")?;

        let start = Instant::now();

        let response = tokio::time::timeout(
            Duration::from_secs(5),
            self.client.request(request),
        )
        .await
        .context("Docker inference request timed out")?
        .context("Docker inference transport failed")?;

        if response.status() != StatusCode::OK {
            bail!("Docker backend returned HTTP {}", response.status());
        }

        let body = tokio::time::timeout(
            Duration::from_secs(5),
            response.into_body().collect(),
        )
        .await
        .context("Docker response body timed out")?
        .context("Cannot read Docker response body")?
        .to_bytes();

        let result: DockerInferenceResponse =
            serde_json::from_slice(&body)
                .context("Invalid Docker inference response")?;

        if result.prediction < 0 {
            bail!("Docker backend returned invalid prediction");
        }

        Ok(DockerInferenceResult {
            prediction: result.prediction,
            inference_time_ns: result.inference_time_ns,
            execution_time_ns: result.execution_time_ns,
            adapter_roundtrip_ns: start.elapsed().as_nanos(),
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn parses_successful_docker_prediction() {
        use axum::{routing::post, Json, Router};
        use serde_json::{json, Value};

        async fn mock_infer(Json(payload): Json<Value>) -> Json<Value> {
            assert_eq!(
                payload["features"],
                json!([5.1, 3.5, 1.4, 0.2])
            );

            Json(json!({
                "prediction": 0,
                "inference_time_ns": 1000,
                "execution_time_ns": 500
            }))
        }

        let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
            .await
            .unwrap();

        let port = listener.local_addr().unwrap().port();

        let app = Router::new().route("/infer", post(mock_infer));

        let server = tokio::spawn(async move {
            axum::serve(listener, app).await.unwrap();
        });

        let adapter = DockerAdapter::new();

        let result = adapter
            .infer(
                &format!("http://127.0.0.1:{port}/infer"),
                &[5.1, 3.5, 1.4, 0.2],
            )
            .await
            .expect("Docker adapter should parse a successful response");

        assert_eq!(result.prediction, 0);
        assert_eq!(result.inference_time_ns, 1000);
        assert_eq!(result.execution_time_ns, 500);
        assert!(result.adapter_roundtrip_ns > 0);

        server.abort();
    }

    #[tokio::test]
    async fn rejects_empty_features() {
        let adapter = DockerAdapter::new();

        let result = adapter
            .infer("http://127.0.0.1:8085/infer", &[])
            .await;

        assert!(result.is_err());
    }

    #[tokio::test]
    async fn rejects_nonfinite_features() {
        let adapter = DockerAdapter::new();

        let result = adapter
            .infer(
                "http://127.0.0.1:8085/infer",
                &[f32::NAN],
            )
            .await;

        assert!(result.is_err());
    }

    #[tokio::test]
    async fn rejects_unavailable_backend() {
        let adapter = DockerAdapter::new();

        let result = adapter
            .infer(
                "http://127.0.0.1:1/infer",
                &[5.1, 3.5, 1.4, 0.2],
            )
            .await;

        assert!(result.is_err());
    }
}
