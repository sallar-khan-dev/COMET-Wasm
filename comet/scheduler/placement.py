def placement_plan(backend, tenants):
    tenants = int(tenants)

    if backend == "wasmtime":
        return {
            "backend": "wasmtime",
            "isolation_unit": "store",
            "tenant_count": tenants,
            "policy": "shared-runtime-isolated-store",
        }

    if backend == "docker":
        return {
            "backend": "docker",
            "isolation_unit": "container",
            "tenant_count": tenants,
            "policy": "container-isolated-tenant",
        }

    raise ValueError(f"Unsupported backend: {backend}")
