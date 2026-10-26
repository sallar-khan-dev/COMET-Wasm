use anyhow::{bail, Context, Result};
use serde_json::{json, Value};
use std::fs;
use wasmtime::{Engine, Linker, Module, Store};

fn main() -> Result<()> {
    let root = std::env::current_dir()?;

    let golden_path = root.join(
        "research_enhancement/v2_references/svm_breast_cancer_golden_v1.json"
    );
    let wasm_path = root.join(
        "wasm/tenant_svm_real/target/wasm32-unknown-unknown/release/tenant_svm_real.wasm"
    );
    let report_path = root.join(
        "research_enhancement/v2_parity/SVM_WASMTIME_PARITY_REPORT.json"
    );

    let golden: Value = serde_json::from_slice(&fs::read(&golden_path)?)?;
    let records = golden["records"]
        .as_array()
        .context("Golden reference has no records array")?;

    if records.len() != 569 {
        bail!("Expected 569 records, found {}", records.len());
    }

    let engine = Engine::default();
    let module = Module::from_file(&engine, &wasm_path)
        .context("Could not load RF Wasm module")?;

    let mut store = Store::new(&engine, ());
    let linker = Linker::new(&engine);

    let instance = linker.instantiate(&mut store, &module)?;

    let memory = instance
        .get_memory(&mut store, "memory")
        .context("Wasm memory export missing")?;

    let input_ptr = instance
        .get_typed_func::<(), i32>(&mut store, "input_ptr")?;

    let feature_count = instance
        .get_typed_func::<(), i32>(&mut store, "feature_count")?;

    let tree_count = instance
        .get_typed_func::<(), i32>(&mut store, "support_vector_count")?;

    let predict = instance
        .get_typed_func::<(), i32>(&mut store, "predict")?;

    let n_features = feature_count.call(&mut store, ())?;
    let n_trees = tree_count.call(&mut store, ())?;

    if n_features != 30 || n_trees != 91 {
        bail!("Unexpected model shape: features={n_features}, support_vectors={n_trees}");
    }

    let ptr = input_ptr.call(&mut store, ())?;
    if ptr < 0 {
        bail!("Invalid input pointer: {ptr}");
    }
    let ptr = ptr as usize;

    let mut mismatches = Vec::new();
    let mut matched = 0usize;

    for record in records {
        let id = record["id"].as_u64().context("Missing record ID")?;
        let features = record["features"]
            .as_array()
            .context("Missing features")?;

        if features.len() != 30 {
            bail!("Record {id}: expected 30 features");
        }

        let expected = record["prediction"]
            .as_i64()
            .context("Missing expected prediction")?;

        let mut bytes = Vec::with_capacity(30 * 4);

        for feature in features {
            let x = feature.as_f64().context("Invalid feature")? as f32;
            if !x.is_finite() {
                bail!("Record {id}: non-finite feature");
            }
            bytes.extend_from_slice(&x.to_le_bytes());
        }

        memory.write(&mut store, ptr, &bytes)
            .with_context(|| format!("Memory write failed for record {id}"))?;

        let actual = predict.call(&mut store, ())
            .with_context(|| format!("Prediction failed for record {id}"))?;

        if i64::from(actual) == expected {
            matched += 1;
        } else {
            mismatches.push(json!({
                "id": id,
                "expected": expected,
                "actual": actual
            }));
        }
    }

    let passed = matched == records.len();

    let report = json!({
        "model": "SVM_RBF",
        "backend": "embedded_wasmtime",
        "reference": golden_path.display().to_string(),
        "wasm_module": wasm_path.display().to_string(),
        "total": records.len(),
        "matched": matched,
        "mismatched": mismatches.len(),
        "status": if passed { "PASS" } else { "FAIL" },
        "mismatches": mismatches
    });

    fs::write(&report_path, serde_json::to_vec_pretty(&report)?)?;

    println!("====================================");
    println!("SVM WASMTIME PARITY");
    println!("====================================");
    println!("Records: {}", records.len());
    println!("Matched: {matched}");
    println!("Mismatches: {}", records.len() - matched);
    println!("Status: {}", if passed { "PASS" } else { "FAIL" });
    println!("Report: {}", report_path.display());

    if !passed {
        bail!("SVM Wasmtime parity failed");
    }

    Ok(())
}
