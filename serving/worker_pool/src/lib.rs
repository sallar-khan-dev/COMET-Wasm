use anyhow::{anyhow, bail, Result};
use wasmtime::{Engine, Instance, Memory, Module, Store, TypedFunc};

pub struct WasmWorker {
    store: Store<()>,
    memory: Memory,
    input_ptr: usize,
    feature_count: usize,
    predict: TypedFunc<(), i32>,
}

impl WasmWorker {
    pub fn new(engine: &Engine, module: &Module) -> Result<Self> {
        let mut store = Store::new(engine, ());
        let instance = Instance::new(&mut store, module, &[])?;

        let memory = instance
            .get_memory(&mut store, "memory")
            .ok_or_else(|| anyhow!("Guest does not export memory"))?;

        let input_ptr_fn =
            instance.get_typed_func::<(), i32>(&mut store, "input_ptr")?;

        let feature_count_fn =
            instance.get_typed_func::<(), i32>(&mut store, "feature_count")?;

        let predict =
            instance.get_typed_func::<(), i32>(&mut store, "predict")?;

        let feature_count =
            feature_count_fn.call(&mut store, ())?;

        if feature_count <= 0 {
            bail!("Invalid feature count returned by guest: {}", feature_count);
        }

        let input_ptr =
            input_ptr_fn.call(&mut store, ())?;

        if input_ptr < 0 {
            bail!("Invalid input pointer returned by guest: {}", input_ptr);
        }

        Ok(Self {
            store,
            memory,
            input_ptr: input_ptr as usize,
            feature_count: feature_count as usize,
            predict,
        })
    }

    pub fn feature_count(&self) -> usize {
        self.feature_count
    }

    pub fn infer(&mut self, features: &[f32]) -> Result<i32> {
        if features.len() != self.feature_count {
            bail!(
                "Expected {} features, received {}",
                self.feature_count,
                features.len()
            );
        }

        let mut bytes =
            Vec::with_capacity(self.feature_count * std::mem::size_of::<f32>());

        for value in features {
            bytes.extend_from_slice(&value.to_le_bytes());
        }

        self.memory.write(
            &mut self.store,
            self.input_ptr,
            &bytes,
        )?;

        let prediction =
            self.predict.call(&mut self.store, ())?;

        Ok(prediction)
    }
}

use std::sync::{Arc, Mutex};

pub struct WasmWorkerPool {
    workers: Vec<Arc<Mutex<WasmWorker>>>,
}

impl WasmWorkerPool {
    pub fn new(
        engine: &Engine,
        module: &Module,
        worker_count: usize,
    ) -> Result<Self> {
        if worker_count == 0 {
            bail!("Worker count must be greater than zero");
        }

        let mut workers = Vec::with_capacity(worker_count);

        for _ in 0..worker_count {
            workers.push(
                Arc::new(Mutex::new(
                    WasmWorker::new(engine, module)?
                ))
            );
        }

        Ok(Self { workers })
    }

    pub fn len(&self) -> usize {
        self.workers.len()
    }

    pub fn is_empty(&self) -> bool {
        self.workers.is_empty()
    }

    pub fn worker(&self, index: usize) -> Option<Arc<Mutex<WasmWorker>>> {
        self.workers.get(index).cloned()
    }
}

impl WasmWorkerPool {
    pub fn worker_for_tenant(
        &self,
        tenant_id: u64,
    ) -> Option<Arc<Mutex<WasmWorker>>> {
        if self.workers.is_empty() {
            return None;
        }

        let index =
            (tenant_id as usize) % self.workers.len();

        self.worker(index)
    }
}
