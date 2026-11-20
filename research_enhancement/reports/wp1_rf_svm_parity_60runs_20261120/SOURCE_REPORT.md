# Supervisor unified pilot checkpoint

Status: **UNACCEPTED_PRECISION_AT_MAX_60**
Independent full repetitions: **60**

- rf|wasmtime|noop: n=60, precision_pass=True
- rf|wasmtime|infer: n=60, precision_pass=False
- rf|docker|noop: n=60, precision_pass=False
- rf|docker|infer: n=60, precision_pass=False
- svm|wasmtime|noop: n=60, precision_pass=True
- svm|wasmtime|infer: n=60, precision_pass=False
- svm|docker|noop: n=60, precision_pass=False
- svm|docker|infer: n=60, precision_pass=False

## Known scientific limits
- Docker shim/helper PSS not observable from unprivileged HPC account
- HTTP /health parity of cold deployment and warm admission not yet proven
- Full request-path/guest-call/input-copy service decomposition not yet proven
- Client/ingress CPU headroom evidence not complete without utilization sampling
- Pilot acceptance review and matched resource fairness still require methodological sign-off

## Blockers

No full seven-model campaign, heavier models, scheduler v2 evaluation, or paper rewrite launched.
