use anyhow::{anyhow, Context, Result};
use serde::Serialize;
use std::env;
use wasmtime::{Engine, ExternType, Module, ValType};

#[derive(Serialize)]
struct ExportInfo {
    name: String,
    kind: String,
    signature: Option<String>,
}

#[derive(Serialize)]
struct ProbeResult {
    artifact: String,
    valid_wasm: bool,
    exports: Vec<ExportInfo>,
    required_exports_present: bool,
    missing_exports: Vec<String>,
    comet_abi_v1_compatible: bool,
}

fn valtype_name(t: &ValType) -> String {
    format!("{:?}", t)
}

fn main() -> Result<()> {
    let path = env::args()
        .nth(1)
        .context("usage: comet-wasm-probe <module.wasm>")?;

    let engine = Engine::default();

    let module = Module::from_file(&engine, &path)
        .map_err(|e| {
            anyhow!(
                "failed to load wasm module {}: {}",
                path,
                e
            )
        })?;

    let mut exports = Vec::new();

    for export in module.exports() {
        let name = export.name().to_string();

        match export.ty() {
            ExternType::Func(func) => {
                let params = func
                    .params()
                    .map(|p| valtype_name(&p))
                    .collect::<Vec<_>>()
                    .join(", ");

                let results = func
                    .results()
                    .map(|r| valtype_name(&r))
                    .collect::<Vec<_>>()
                    .join(", ");

                exports.push(ExportInfo {
                    name,
                    kind: "func".to_string(),
                    signature: Some(format!("({}) -> ({})", params, results)),
                });
            }

            ExternType::Memory(_) => {
                exports.push(ExportInfo {
                    name,
                    kind: "memory".to_string(),
                    signature: None,
                });
            }

            ExternType::Global(_) => {
                exports.push(ExportInfo {
                    name,
                    kind: "global".to_string(),
                    signature: None,
                });
            }

            ExternType::Table(_) => {
                exports.push(ExportInfo {
                    name,
                    kind: "table".to_string(),
                    signature: None,
                });
            }

            _ => {
                exports.push(ExportInfo {
                    name,
                    kind: "other".to_string(),
                    signature: None,
                });
            }
        }
    }

    let required = [
        "memory",
        "input_ptr",
        "feature_count",
        "predict",
    ];

    let exported_names = exports
        .iter()
        .map(|e| e.name.as_str())
        .collect::<Vec<_>>();

    let missing_exports = required
        .iter()
        .filter(|name| !exported_names.contains(name))
        .map(|name| name.to_string())
        .collect::<Vec<_>>();

    let required_exports_present =
        missing_exports.is_empty();

    let mut abi_signatures_ok = true;

    for export in &exports {
        match export.name.as_str() {
            "input_ptr" |
            "feature_count" |
            "predict" => {
                let expected = "() -> (i32)";

                if export.signature.as_deref()
                    != Some(expected)
                {
                    abi_signatures_ok = false;
                }
            }

            "memory" => {
                if export.kind != "memory" {
                    abi_signatures_ok = false;
                }
            }

            _ => {}
        }
    }

    let result = ProbeResult {
        artifact: path,
        valid_wasm: true,
        exports,
        required_exports_present,
        missing_exports,
        comet_abi_v1_compatible:
            required_exports_present
            && abi_signatures_ok,
    };

    println!(
        "{}",
        serde_json::to_string_pretty(&result)?
    );

    Ok(())
}
