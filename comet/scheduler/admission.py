def validate_request(model, concurrency, tenants):
    if not model:
        raise ValueError("model is required")

    if int(concurrency) < 1:
        raise ValueError("concurrency must be >= 1")

    if int(tenants) < 1:
        raise ValueError("tenants must be >= 1")

    return True
