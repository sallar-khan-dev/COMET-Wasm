use anyhow::{bail, Context, Result};
use comet_worker_pool::WasmWorkerPool;
use std::{sync::Arc, time::Instant};
use wasmtime::{Engine, Module};

#[derive(Clone)]
pub struct WasmAdapter {
    pool: Arc<WasmWorkerPool>,
}

#[derive(Debug)]
pub struct WasmInferenceResult {
    pub worker_id: usize,
    pub prediction: i32,
    pub inference_time_ns: u128,
    pub execution_time_ns: u128,
}

impl WasmAdapter {
    pub fn new(wasm_path: &str, worker_count: usize) -> Result<Self> {
        if worker_count == 0 {
            bail!("Wasmtime worker count must be greater than zero");
        }

        let engine = Engine::default();

        let module = Module::from_file(&engine, wasm_path)
            .map_err(|e| anyhow::anyhow!(
                "Cannot load Wasm module {}: {}",
                wasm_path,
                e
            ))?;

        let pool = WasmWorkerPool::new(&engine, &module, worker_count)?;

        Ok(Self {
            pool: Arc::new(pool),
        })
    }

    pub fn worker_count(&self) -> usize {
        self.pool.len()
    }

    pub async fn infer(
        &self,
        tenant_id: u64,
        features: Vec<f32>,
    ) -> Result<WasmInferenceResult> {
        let pool = Arc::clone(&self.pool);

        tokio::task::spawn_blocking(move || {
            let worker_id = (tenant_id as usize) % pool.len();

            let worker = pool
                .worker_for_tenant(tenant_id)
                .context("No Wasmtime worker available")?;

            let start = Instant::now();

            let mut worker = worker
                .lock()
                .map_err(|_| anyhow::anyhow!("Wasmtime worker lock poisoned"))?;

            let (prediction, execution_time_ns) =
                worker.infer_timed(&features)?;

            Ok(WasmInferenceResult {
                worker_id,
                prediction,
                inference_time_ns: start.elapsed().as_nanos(),
                execution_time_ns,
            })
        })
        .await
        .context("Wasmtime blocking task failed")?
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_zero_workers() {
        let result = WasmAdapter::new("/nonexistent/model.wasm", 0);
        assert!(result.is_err());
    }

    #[tokio::test]
    async fn executes_real_lr_prediction() {
        let path = concat!(
            env!("CARGO_MANIFEST_DIR"),
            "/../../wasm/tenant_lr_real/target/",
            "wasm32-unknown-unknown/release/tenant_lr_real.wasm"
        );

        let adapter = WasmAdapter::new(path, 2)
            .expect("LR Wasm module should load");

        assert_eq!(adapter.worker_count(), 2);

        let samples = [
            ([5.1, 3.5, 1.4, 0.2], 0),
            ([6.7, 3.0, 5.2, 2.3], 1),
        ];

        for (i, (features, expected)) in samples.into_iter().enumerate() {
            let result = adapter
                .infer(i as u64, features.to_vec())
                .await
                .expect("LR inference should succeed");

            assert_eq!(
                result.prediction, expected,
                "Incorrect prediction for sample {i}"
            );

            assert_eq!(result.worker_id, i);
        }
    }

    #[test]
    fn rejects_missing_module() {
        let result = WasmAdapter::new("/nonexistent/model.wasm", 1);
        assert!(result.is_err());
    }
}
