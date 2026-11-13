# WP3 §6.1 batched LR kernel pilot

- Batches: 500 invocations per input; 135 deterministic input rows; 20 repeated rounds per backend.
- Native mean: 7.720 ns/call
- Wasmtime mean: 33.514 ns/call
- Ratio Wasmtime/native: 4.341

The Wasmtime measured block includes typed-call overhead, not just guest instructions. It excludes input copy, HTTP and admission. This pilot does not certify WP3 or establish cold start/admission parity.
