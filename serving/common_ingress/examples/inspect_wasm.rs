use wasmtime::{Engine, Module};

fn main() -> anyhow::Result<()> {
    let path = std::env::args()
        .nth(1)
        .expect("Usage: inspect_wasm <module.wasm>");

    let engine = Engine::default();

    let module = Module::from_file(&engine, &path)
        .map_err(|e| anyhow::anyhow!("Cannot load {}: {}", path, e))?;

    println!("Wasm module: {}", path);
    println!("Exports:");

    for export in module.exports() {
        println!("  {}: {:?}", export.name(), export.ty());
    }

    Ok(())
}
