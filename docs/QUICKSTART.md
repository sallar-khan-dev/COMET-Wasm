# Quickstart

```bash
cd /home/sallar/wasiMultitenant
source .venv/bin/activate
```

## Run Wasm LR server

```bash
cd /home/sallar/wasiMultitenant/serving/wasm_server/host_lr_server
cargo run --release
```

Test:

```bash
curl -X POST http://localhost:8010/infer -H "Content-Type: application/json" -d '{"f1":6.3,"f2":3.3,"f3":6.0,"f4":2.5}'
```

## Run Docker LR server

```bash
cd /home/sallar/wasiMultitenant/docker/lr_server
docker build -t docker-lr-server .
docker run -d -p 8086:8085 --name docker_lr_test docker-lr-server
```

Test:

```bash
curl -X POST http://localhost:8086/infer -H "Content-Type: application/json" -d '{"f1":6.3,"f2":3.3,"f3":6.0,"f4":2.5}'
```

## CI throughput experiments

```bash
./experiments/throughput/run_lr_ci_wasm.sh
./experiments/throughput/run_lr_ci_docker.sh
```

## Cold start experiments

```bash
for i in {1..20}; do ./experiments/coldstart/wasm_lr_coldstart.sh; done | tee results/coldstart/wasm_lr_coldstart_results.txt
for i in {1..20}; do ./experiments/coldstart/docker_lr_coldstart.sh; done | tee results/coldstart/docker_lr_coldstart_results.txt
```

## COMET-Wasm scheduler skeleton

```bash
python comet/scoring/comet_score.py
```
