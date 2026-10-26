use anyhow::{bail, Result};
use serde::Serialize;

use crate::TraceRequest;

#[derive(Serialize)]
struct InferencePayload<'a> {
    request_id: &'a str,
    tenant_id: u64,
    model: &'a str,
    features: Vec<f32>,
}

pub fn encode_request(request: &TraceRequest) -> Result<Vec<u8>> {
    let tenant_id = u64::try_from(request.tenant_slot)?;

    if request.request_id.trim().is_empty()
        || request.model.trim().is_empty()
        || request.features.is_empty()
    {
        bail!("Invalid inference request metadata");
    }

    let mut features = Vec::with_capacity(request.features.len());

    for &value in &request.features {
        if !value.is_finite() {
            bail!("Non-finite trace feature");
        }

        let converted = value as f32;

        if !converted.is_finite() {
            bail!("Feature outside finite f32 range");
        }

        features.push(converted);
    }

    Ok(serde_json::to_vec(&InferencePayload {
        request_id: &request.request_id,
        tenant_id,
        model: &request.model,
        features,
    })?)
}

#[derive(Debug, serde::Deserialize)]
#[serde(deny_unknown_fields)]
pub struct InferenceResponse {
    pub request_id: String,
    pub tenant_id: u64,
    pub model: String,
    pub backend: String,
    pub worker_id: Option<usize>,
    pub prediction: i32,
    pub inference_time_ns: u128,
    pub execution_time_ns: u128,
    pub request_total_ns: u128,
    pub adapter_roundtrip_ns: Option<u128>,
}

pub fn validate_response(
    body: &[u8],
    request: &TraceRequest,
    expected_backend: &str,
) -> Result<InferenceResponse> {
    let response: InferenceResponse = serde_json::from_slice(body)?;

    let expected_tenant = u64::try_from(request.tenant_slot)?;

    if response.request_id != request.request_id {
        bail!("Response request ID mismatch");
    }

    if response.tenant_id != expected_tenant {
        bail!("Response tenant ID mismatch");
    }

    if response.model != request.model {
        bail!("Response model mismatch");
    }

    if response.backend != expected_backend {
        bail!(
            "Backend mismatch: expected {}, received {}",
            expected_backend,
            response.backend
        );
    }

    if i64::from(response.prediction) != request.expected_prediction {
        bail!(
            "Prediction mismatch: expected {}, received {}",
            request.expected_prediction,
            response.prediction
        );
    }

    Ok(response)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample_request() -> TraceRequest {
        TraceRequest {
            request_id: "v2-00000000".into(),
            sequence: 0,
            tenant_slot: 2,
            model: "lr".into(),
            source_row_index: 0,
            features: vec![5.1, 3.5, 1.4, 0.2],
            expected_prediction: 1,
            ground_truth_label: 1,
        }
    }

    #[test]
    fn serializes_exact_ingress_fields() {
        let bytes = encode_request(&sample_request()).unwrap();
        let value: serde_json::Value = serde_json::from_slice(&bytes).unwrap();

        assert_eq!(value["request_id"], "v2-00000000");
        assert_eq!(value["tenant_id"], 2);
        assert_eq!(value["model"], "lr");
        assert_eq!(value["features"].as_array().unwrap().len(), 4);
        assert_eq!(value.as_object().unwrap().len(), 4);
        assert!(value.get("tenant_slot").is_none());
    }

    fn sample_response() -> Vec<u8> {
        serde_json::to_vec(&serde_json::json!({
            "request_id": "v2-00000000",
            "tenant_id": 2,
            "model": "lr",
            "backend": "native",
            "worker_id": null,
            "prediction": 1,
            "inference_time_ns": 100,
            "execution_time_ns": 150,
            "request_total_ns": 200,
            "adapter_roundtrip_ns": 180
        }))
        .unwrap()
    }

    #[test]
    fn accepts_valid_inference_response() {
        let response = validate_response(&sample_response(), &sample_request(), "native").unwrap();

        assert_eq!(response.prediction, 1);
        assert_eq!(response.backend, "native");
        assert_eq!(response.worker_id, None);
        assert_eq!(response.inference_time_ns, 100);
        assert_eq!(response.execution_time_ns, 150);
        assert_eq!(response.request_total_ns, 200);
        assert_eq!(response.adapter_roundtrip_ns, Some(180));
    }

    #[test]
    fn rejects_incorrect_backend() {
        assert!(validate_response(&sample_response(), &sample_request(), "wasmtime",).is_err());
    }

    #[test]
    fn rejects_incorrect_prediction() {
        let mut request = sample_request();
        request.expected_prediction = 0;

        assert!(validate_response(&sample_response(), &request, "native",).is_err());
    }

    #[test]
    fn rejects_incorrect_request_identity() {
        let mut request = sample_request();
        request.request_id = "different-request".into();

        assert!(validate_response(&sample_response(), &request, "native",).is_err());
    }

    #[test]
    fn rejects_feature_overflow() {
        let mut request = sample_request();
        request.features[0] = f64::MAX;

        assert!(encode_request(&request).is_err());
    }

    #[test]
    fn rejects_nonfinite_features() {
        let mut request = sample_request();
        request.features[0] = f64::NAN;

        assert!(encode_request(&request).is_err());
    }
}
