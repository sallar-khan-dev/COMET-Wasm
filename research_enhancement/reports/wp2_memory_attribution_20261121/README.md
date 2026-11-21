# WP2 Memory Attribution

Existing experimental evidence only; no measurements repeated.

- JIT ready PSS: 10502.72 KiB
- AOT ready PSS: 5092.46 KiB
- Observed AOT memory reduction: 51.51%
- Ready-PSS CI precision accepted: True
- All reported stage metrics accepted: False

Statistical protocol: 95% Student-t and bootstrap CIs, relative half-width <=2.5%.

Stage-level base, engine, module and worker measurements are in memory_component_precision.csv.

**Limitations:** Docker helper PSS inaccessible; no invented zero overhead.
Stage deltas do not establish independent model-resident memory ownership.
Historical thread-parity and complete WP2 acceptance remain unresolved.
