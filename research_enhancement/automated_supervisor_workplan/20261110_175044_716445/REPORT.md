# COMET-Wasm supervisor work-plan automation report

WP1 status: **DATA COLLECTED; ACCEPTANCE REVIEW REQUIRED**

> WP1 acceptance cannot be inferred solely from zero-error runs; the supervisor requires proven gateway/load-generator headroom above the fastest backend and no client-side saturation.

## WP1 capacity evidence

| Model | Backend | Offered RPS | Rep | Correct | P95 ms | P99 ms | P99 scheduling ms | Client CPU % |
|---|---|---:|---:|---|---:|---:|---:|---:|
| lr | wasmtime | 100 | 1 | True | 2.571445 | 2.65131 | 1.951178 | 1.49 |
| lr | wasmtime | 100 | 2 | True | 2.574984 | 2.743807 | 1.860478 | 3.59 |
| lr | wasmtime | 100 | 3 | True | 2.562279 | 2.594939 | 1.779481 | 4.14 |
| lr | wasmtime | 300 | 1 | True | 2.232108 | 2.605932 | 1.746031 | 6.44 |
| lr | wasmtime | 300 | 2 | True | 2.765636 | 2.883891 | 2.12564 | 7.86 |
| lr | wasmtime | 300 | 3 | True | 2.831328 | 2.967503 | 2.17395 | 7.73 |
| lr | wasmtime | 600 | 1 | True | 2.498171 | 2.577312 | 1.955654 | 4.27 |
| lr | wasmtime | 600 | 2 | True | 2.58012 | 2.92706 | 2.126389 | 8.47 |
| lr | wasmtime | 600 | 3 | True | 2.966644 | 3.03079 | 2.231413 | 14.98 |
| lr | wasmtime | 1200 | 1 | True | 2.4268 | 2.658181 | 2.023447 | 9.47 |
| lr | wasmtime | 1200 | 2 | True | 2.369843 | 2.59617 | 1.967262 | 9.47 |
| lr | wasmtime | 1200 | 3 | True | 2.368055 | 2.630952 | 2.012615 | 9.0 |
| lr | wasmtime | 2400 | 1 | True | 2.22001 | 2.47193 | 1.94028 | 15.8 |
| lr | wasmtime | 2400 | 2 | True | 2.303624 | 2.565493 | 1.985029 | 15.8 |
| lr | wasmtime | 2400 | 3 | False | 2.263205 | 2.555323 | 1.945148 | 16.13 |
| lr | docker | 100 | 1 | True | 3.522327 | 3.5629 | 1.437989 | 4.2 |
| lr | docker | 100 | 2 | True | 3.608264 | 3.726528 | 1.608962 | 4.14 |
| lr | docker | 100 | 3 | True | 4.134881 | 4.169174 | 2.035081 | 4.2 |
| lr | docker | 300 | 1 | True | 4.118426 | 4.444472 | 2.138318 | 11.25 |
| lr | docker | 300 | 2 | True | 4.153255 | 4.404833 | 2.129233 | 11.12 |
| lr | docker | 300 | 3 | True | 3.801024 | 4.124134 | 1.919948 | 10.85 |
| lr | docker | 600 | 1 | True | 3.509395 | 4.049984 | 2.073269 | 13.36 |
| lr | docker | 600 | 2 | True | 3.394834 | 3.758109 | 1.806258 | 13.15 |
| lr | docker | 600 | 3 | True | 3.447812 | 3.84411 | 1.953222 | 13.63 |
| lr | docker | 1200 | 1 | True | 2.539822 | 2.96127 | 2.018878 | 9.47 |
| lr | docker | 1200 | 2 | True | 2.719996 | 3.082366 | 2.005012 | 9.47 |
| lr | docker | 1200 | 3 | True | 2.552478 | 2.938811 | 1.872162 | 9.33 |
| lr | docker | 2400 | 1 | True | 2.716639 | 3.174853 | 1.924496 | 14.27 |
| lr | docker | 2400 | 2 | True | 2.56849 | 3.00589 | 1.923396 | 14.33 |
| lr | docker | 2400 | 3 | True | 2.569859 | 2.965764 | 1.939011 | 14.13 |
| rf | wasmtime | 100 | 1 | True | 2.550808 | 2.730616 | 1.868311 | 4.2 |
| rf | wasmtime | 100 | 2 | True | 2.408016 | 2.532509 | 1.689503 | 4.27 |
| rf | wasmtime | 100 | 3 | True | 2.596003 | 2.690697 | 1.790172 | 4.27 |
| rf | wasmtime | 300 | 1 | True | 2.561798 | 2.824444 | 2.056867 | 4.88 |
| rf | wasmtime | 300 | 2 | True | 2.164207 | 2.590175 | 2.031516 | 2.85 |
| rf | wasmtime | 300 | 3 | True | 2.400311 | 2.715347 | 1.838034 | 7.73 |
| rf | wasmtime | 600 | 1 | True | 2.481857 | 2.778944 | 1.99068 | 8.07 |
| rf | wasmtime | 600 | 2 | True | 2.529461 | 2.661357 | 1.867351 | 7.73 |
| rf | wasmtime | 600 | 3 | True | 2.451456 | 2.762211 | 1.859483 | 14.44 |
| rf | wasmtime | 1200 | 1 | True | 2.081591 | 2.406408 | 2.058279 | 13.87 |
| rf | wasmtime | 1200 | 2 | True | 2.278111 | 2.548047 | 1.920755 | 10.47 |
| rf | wasmtime | 1200 | 3 | True | 2.274751 | 2.539586 | 1.892003 | 9.87 |
| rf | wasmtime | 2400 | 1 | True | 1.832027 | 2.078043 | 1.856946 | 16.4 |
| rf | wasmtime | 2400 | 2 | True | 2.201702 | 2.453227 | 1.963397 | 16.73 |
| rf | wasmtime | 2400 | 3 | True | 2.247384 | 2.550956 | 1.981379 | 16.67 |
| rf | docker | 100 | 1 | True | 2.325743 | 2.436632 | 1.78934 | 1.42 |
| rf | docker | 100 | 2 | True | 2.356361 | 2.462702 | 1.821493 | 1.42 |
| rf | docker | 100 | 3 | True | 1.803545 | 1.901311 | 1.248418 | 1.63 |
| rf | docker | 300 | 1 | True | 2.085625 | 2.200557 | 1.915028 | 2.64 |
| rf | docker | 300 | 2 | True | 2.140268 | 2.267798 | 1.971036 | 2.64 |
| rf | docker | 300 | 3 | True | 1.952601 | 2.08224 | 1.780553 | 2.64 |
| rf | docker | 600 | 1 | True | 2.211266 | 2.31517 | 1.941846 | 4.68 |
| rf | docker | 600 | 2 | True | 2.198479 | 2.284242 | 1.907044 | 4.95 |
| rf | docker | 600 | 3 | True | 2.254693 | 2.369669 | 2.020484 | 4.41 |
| rf | docker | 1200 | 1 | True | 2.088355 | 2.34912 | 1.920423 | 8.41 |
| rf | docker | 1200 | 2 | True | 2.144577 | 2.363791 | 1.939722 | 9.07 |
| rf | docker | 1200 | 3 | True | 2.158911 | 2.312945 | 1.951158 | 8.8 |
| rf | docker | 2400 | 1 | True | 2.35523 | 2.719395 | 2.017983 | 14.73 |
| rf | docker | 2400 | 2 | True | 2.321493 | 2.657552 | 2.009658 | 15.2 |
| rf | docker | 2400 | 3 | True | 2.251884 | 5.296344 | 2.002108 | 13.87 |

## Work-package acceptance status

WP1: DATA COLLECTED; ACCEPTANCE REVIEW REQUIRED
WP2: Evidence inventoried; acceptance not established
WP3: Evidence inventoried; acceptance not established
WP4: Existing kernels preserved; service crossover acceptance not established
WP5: Not launched; requires approved WP1–WP4 evidence and scheduler implementation
WP6: Not launched; requires frozen WP5 scheduler and held-out protocol

## Blockers

- None encountered in execution; final acceptance review still required.
