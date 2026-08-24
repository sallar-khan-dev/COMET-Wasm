# COMET-Wasm Workload ABI v1

Each vector-based WebAssembly ML guest should expose:

- `input_ptr() -> i32`
  Returns the byte offset of the guest input buffer in linear memory.

- `feature_count() -> i32`
  Returns the expected number of `f32` input features.

- `predict() -> i32`
  Runs inference using the values currently stored in the input buffer.

Optional workload-specific metadata exports may include:

- `tree_count() -> i32`
- `support_vector_count() -> i32`
- `hidden_count() -> i32`
- `cluster_count() -> i32`

Input representation:

- contiguous IEEE-754 `f32`
- little-endian
- exactly `feature_count * 4` bytes

Output:

- classification workloads: class index as `i32`
- K-Means: cluster index as `i32`

The host is responsible for:
1. validating input dimensionality;
2. writing the feature vector into guest linear memory;
3. calling `predict`;
4. returning the result through the serving API.

Version: 1
