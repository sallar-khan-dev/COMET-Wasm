# WP1/WP3 Native common-ingress attribution campaign

**Status:** NATIVE_CAMPAIGN_COMPLETE
**Native trials:** 100/100
**Historical backend request-series read:** 30

## Scope limits and supervisor acceptance
- Native route uses isolated copies of the real gateway/native Rust sources with environment-configured ports, not a third scheduler backend.
- Only native path runs now; Wasmtime/Docker historical campaigns have three repetitions and possibly different max-inflight settings, so pooled cross-backend statistical equivalence is NOT asserted.
- Existing Docker gateway route uses a published loopback port; verified Docker bridge internals still require a separate deployment review.
- Execution, inference, adapter and gateway timings have nested boundaries; guest-call/input-copy isolation cannot be inferred by subtraction alone.
- No-go remains until WP1 generator headroom, matched threads and WP2 helper visibility are scientifically resolved.

**WP1–WP3 Stop/Go remains NO-GO pending acceptance.**

See `TIMING_DECOMPOSITION.csv` and `RESULT.json` for evidence.
