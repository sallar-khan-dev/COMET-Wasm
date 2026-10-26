use anyhow::{Context, Result};
use serde_json::Value;
use std::{fs, path::PathBuf};
use wasmtime::{Engine, Instance, Module, Store};

fn main() -> Result<()> {
    let root = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../..");
    let golden_path = root.join("research_enhancement/v2_references/kmeans_iris_golden_v1.json");
    let wasm_path = root.join("wasm/tenant_kmeans_real/target/wasm32-unknown-unknown/release/tenant_kmeans_real.wasm");

    let data: Value = serde_json::from_slice(&fs::read(&golden_path)?)?;
    let records = data["records"].as_array().context("Missing records")?;

    let engine = Engine::default();
    let module = Module::from_file(&engine, &wasm_path)?;
    let mut store = Store::new(&engine, ());
    let instance = Instance::new(&mut store, &module, &[])?;

    let input_ptr = instance.get_typed_func::<(), i32>(&mut store, "input_ptr")?;
    let feature_count = instance.get_typed_func::<(), i32>(&mut store, "feature_count")?;
    let predict = instance.get_typed_func::<(), i32>(&mut store, "predict")?;
    let memory = instance.get_memory(&mut store, "memory").context("Missing memory export")?;

    let dim = feature_count.call(&mut store, ())? as usize;
    let ptr = input_ptr.call(&mut store, ())? as usize;

    let mut mismatches = 0;

    for (i, record) in records.iter().enumerate() {
        let features = record["features"].as_array().context("Missing features")?;
        anyhow::ensure!(features.len() == dim, "Feature dimension mismatch");

        for (j, value) in features.iter().enumerate() {
            let x = value.as_f64().context("Invalid feature")? as f32;
            memory.write(&mut store, ptr + j * 4, &x.to_le_bytes())?;
        }

        let actual = predict.call(&mut store, ())?;
        let expected = record["expected_prediction"]
            .as_i64().context("Missing prediction")? as i32;

        if actual != expected {
            mismatches += 1;
            if mismatches <= 10 {
                println!("Mismatch row {}: expected {}, actual {}", i, expected, actual);
            }
        }
    }

    println!("KMEANS WASM PARITY: {}/{}", records.len() - mismatches, records.len());
    anyhow::ensure!(mismatches == 0, "{} prediction mismatches", mismatches);
    println!("PASS: All predictions match the independent reference");
    Ok(())
}
