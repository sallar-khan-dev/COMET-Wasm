COMET_ABI_VERSION = "comet-abi-v1"

REQUIRED_WASM_EXPORTS = {
    "memory",
    "input_ptr",
    "feature_count",
    "predict",
}

ABI_DESCRIPTION = {
    "version":
        COMET_ABI_VERSION,

    "input_encoding":
        "contiguous f32 vector in guest linear memory",

    "exports": {
        "memory":
            "WebAssembly linear memory",

        "input_ptr":
            "() -> i32",

        "feature_count":
            "() -> i32",

        "predict":
            "() -> i32",
    },

    "semantics": {
        "input_ptr":
            "Returns byte offset of model input buffer",

        "feature_count":
            "Returns expected number of f32 input features",

        "predict":
            "Runs inference using values written to input buffer",
    },
}
