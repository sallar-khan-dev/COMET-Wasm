use anyhow::Result;
use comet_worker_pool::WasmWorkerPool;
use wasmtime::{Engine, Module};

#[test]
fn create_multiple_workers() -> Result<()> {
    let engine = Engine::default();

    let module_path =
        "../../wasm/tenant_nb_real/target/wasm32-unknown-unknown/release/tenant_nb_real.wasm";

    let module =
        Module::from_file(&engine, module_path)?;

    let pool =
        WasmWorkerPool::new(&engine, &module, 4)?;

    assert_eq!(pool.len(), 4);

    for tenant in 0..8 {
        assert!(
            pool.worker_for_tenant(tenant).is_some()
        );
    }

    Ok(())
}
