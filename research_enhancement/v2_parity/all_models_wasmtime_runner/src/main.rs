
use anyhow::{anyhow, Context, Result};
use serde_json::{json, Value};
use std::{env, fs};
use wasmtime::{Engine, Instance, Module, Store};
fn main() -> Result<()> {
    let args: Vec<String> = env::args().collect();
    if args.len() != 4 { return Err(anyhow!("usage: runner wasm reference output")); }
    let data: Value = serde_json::from_slice(&fs::read(&args[2])?)?;
    let records = data["records"].as_array().context("missing records")?;
    let engine = Engine::default();
    let module = Module::from_file(&engine, &args[1])?;
    let mut store = Store::new(&engine, ());
    let instance = Instance::new(&mut store, &module, &[])?;
    let ptr_fn = instance.get_typed_func::<(), i32>(&mut store, "input_ptr")?;
    let count_fn = instance.get_typed_func::<(), i32>(&mut store, "feature_count")?;
    let predict_fn = instance.get_typed_func::<(), i32>(&mut store, "predict")?;
    let memory = instance.get_memory(&mut store, "memory").context("missing memory export")?;
    let n = count_fn.call(&mut store, ())? as usize;
    let ptr = ptr_fn.call(&mut store, ())? as usize;
    let mut matched = 0usize;
    let mut mismatches = Vec::new();
    for (index, record) in records.iter().enumerate() {
        let features = record["features"].as_array().context("missing features")?;
        if features.len() != n { return Err(anyhow!("record {} has {} features, expected {}", index, features.len(), n)); }
        let mut bytes = Vec::with_capacity(4*n);
        for v in features { bytes.extend_from_slice(&(v.as_f64().context("invalid feature")? as f32).to_le_bytes()); }
        memory.write(&mut store, ptr, &bytes)?;
        let got = predict_fn.call(&mut store, ())?;
        let expected = record["prediction"].as_i64().context("missing prediction")? as i32;
        if got == expected { matched += 1; }
        else if mismatches.len() < 25 { mismatches.push(json!({"id": record["id"], "expected": expected, "actual": got})); }
    }
    let report = json!({"status": if matched == records.len() {"PASS"} else {"FAIL"}, "records": records.len(), "matched": matched, "mismatches": records.len()-matched, "examples": mismatches});
    fs::write(&args[3], serde_json::to_vec_pretty(&report)?)?;
    println!("{}", report);
    Ok(())
}
