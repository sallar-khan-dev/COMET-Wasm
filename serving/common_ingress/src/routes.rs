use anyhow::{bail, Context, Result};
use serde::Deserialize;
use std::{collections::HashMap, fs, path::Path};

#[derive(Debug, Clone, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum Backend {
    Wasmtime,
    Docker,
    Native,
}

#[derive(Debug, Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TenantRoute {
    pub backend: Backend,
    pub model: String,
    #[serde(default)]
    pub url: Option<String>,
}

pub type RouteTable = HashMap<String, TenantRoute>;

pub fn load_routes(path: impl AsRef<Path>) -> Result<RouteTable> {
    let contents =
        fs::read_to_string(path.as_ref()).context("Failed to read tenant routing configuration")?;

    let routes: RouteTable =
        serde_json::from_str(&contents).context("Invalid routing configuration JSON")?;

    if routes.is_empty() {
        bail!("Routing configuration cannot be empty");
    }

    for (tenant, route) in &routes {
        if tenant.is_empty() || tenant.parse::<u64>().is_err() {
            bail!("Invalid tenant ID: {tenant}");
        }

        if !matches!(
            route.model.as_str(),
            "lr" | "nb" | "dt" | "kmeans" | "rf" | "svm" | "mlp"
        ) {
            bail!("Unsupported model for tenant {tenant}: {}", route.model);
        }

        match route.backend {
            Backend::Wasmtime => {
                if route.url.is_some() {
                    bail!("Embedded Wasmtime must not use an HTTP URL (tenant {tenant})");
                }
            }
            Backend::Docker | Backend::Native => {
                let url = route.url.as_deref().ok_or_else(|| {
                    anyhow::anyhow!("Missing external backend URL for tenant {tenant}")
                })?;

                if !url.starts_with("http://127.0.0.1:") && !url.starts_with("http://localhost:") {
                    bail!("External backend must use a loopback HTTP URL (tenant {tenant})");
                }
            }
        }
    }

    Ok(routes)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn write_and_load(contents: &str) -> Result<RouteTable> {
        let path = std::env::temp_dir().join(format!(
            "comet_routes_v2_{}_{}.json",
            std::process::id(),
            std::thread::current().name().unwrap_or("test")
        ));

        fs::write(&path, contents).unwrap();
        let result = load_routes(&path);
        let _ = fs::remove_file(&path);
        result
    }

    #[test]
    fn accepts_valid_routes() {
        let routes = write_and_load(
            r#"{
                "0": {"backend":"wasmtime","model":"lr"},
                "1": {"backend":"docker","model":"rf","url":"http://127.0.0.1:8085/infer"}
            }"#,
        )
        .unwrap();

        assert_eq!(routes["0"].backend, Backend::Wasmtime);
        assert_eq!(routes["0"].model, "lr");
        assert!(routes["0"].url.is_none());
        assert_eq!(routes["1"].backend, Backend::Docker);
    }

    #[test]
    fn rejects_unknown_backend() {
        let result = write_and_load(r#"{"0":{"backend":"unknown","model":"lr"}}"#);
        assert!(result.is_err());
    }

    #[test]
    fn rejects_invalid_url() {
        let result = write_and_load(
            r#"{"0":{"backend":"docker","model":"lr","url":"http://remote-host:8080/infer"}}"#,
        );
        assert!(result.is_err());
    }

    #[test]
    fn rejects_wasmtime_http_url() {
        let result = write_and_load(
            r#"{"0":{"backend":"wasmtime","model":"lr","url":"http://127.0.0.1:8100/infer"}}"#,
        );
        assert!(result.is_err());
    }

    #[test]
    fn rejects_missing_external_url() {
        let result = write_and_load(r#"{"0":{"backend":"docker","model":"lr"}}"#);
        assert!(result.is_err());
    }

    #[test]
    fn rejects_unknown_model() {
        let result = write_and_load(r#"{"0":{"backend":"wasmtime","model":"unknown"}}"#);
        assert!(result.is_err());
    }

    #[test]
    fn rejects_empty_route_table() {
        let result = write_and_load("{}");
        assert!(result.is_err());
    }
}
