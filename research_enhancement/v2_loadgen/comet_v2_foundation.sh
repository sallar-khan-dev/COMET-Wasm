#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="${HOME}/wasiMultitenant"
LOAD="$ROOT/research_enhancement/v2_loadgen"
ING="$ROOT/serving/common_ingress"
STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$ROOT/research_enhancement/v2_foundation_runs/$STAMP"
mkdir -p "$OUT" "$OUT/backups"
exec > >(tee -a "$OUT/run.log") 2>&1
trap 'echo "FAILED at line $LINENO; see $OUT/run.log"' ERR
printf 'Output: %s\n' "$OUT"
[[ -f "$LOAD/src/main.rs" && -f "$ING/src/main.rs" ]] || { echo 'Unexpected repository layout'; exit 1; }
[[ "$(cd "$ROOT" && git branch --show-current)" == comet-v2-implementation ]] || { echo 'Wrong git branch'; exit 1; }
command -v python3 >/dev/null
command -v cargo >/dev/null
command -v curl >/dev/null
command -v flock >/dev/null
exec 9>"$ROOT/research_enhancement/.comet_v2_foundation.lock"
flock -n 9 || { echo 'Another foundation run holds the lock'; exit 1; }
# Avoid touching an already running ingress.
python3 - <<'PY'
import socket
s=socket.socket()
try:
    s.bind(('127.0.0.1',8200))
except OSError as e:
    raise SystemExit(f'Port 8200 busy: {e}; refusing to start/modify run')
finally:
    s.close()
PY
cp -p "$LOAD/src/main.rs" "$OUT/backups/loadgen_main.rs"
cp -p "$LOAD/src/http_client.rs" "$OUT/backups/http_client.rs"
cp -p "$ING/src/main.rs" "$OUT/backups/ingress_main.rs"
for name in noop_record.rs noop_dispatcher.rs; do if [[ -e "$LOAD/src/$name" ]]; then cp -p "$LOAD/src/$name" "$OUT/backups/$name"; fi; done
export COMET_LOAD="$LOAD" COMET_ING="$ING"
python3 - <<'PY'
from pathlib import Path
import os
load=Path(os.environ['COMET_LOAD']); ing=Path(os.environ['COMET_ING'])
main=load/'src/main.rs'; s=main.read_text()
# Dedicated no-op mode, intentionally separate from inference trace and predictions.
if 'mod noop_dispatcher;' not in s:
    anchor='mod jsonl_output;'
    assert s.count(anchor)==1
    s=s.replace(anchor,anchor+'\nmod noop_dispatcher;',1)
if 'fn run_noop_mode(' not in s:
    anchor='fn main() -> Result<()> {'
    assert s.count(anchor)==1
    func=r'''fn run_noop_mode(args: &[String]) -> Result<()> {
    use std::{path::Path, time::Duration, io::Write};
    use hyper::Uri;
    if args.len() != 8 { bail!("Usage: comet_v2_loadgen noop <http://127.0.0.1:8200/noop> <rps> <seconds> <timeout_ms> <max_inflight> <output_prefix>"); }
    let uri: Uri = args[2].parse().context("Invalid no-op URL")?;
    if uri.scheme_str()!=Some("http") || uri.path()!="/noop" || !matches!(uri.host(), Some("127.0.0.1" | "localhost")) { bail!("No-op endpoint must be a loopback HTTP URL ending in /noop"); }
    let rps: f64 = args[3].parse().context("Invalid RPS")?;
    schedule::scheduled_offset(0, rps)?;
    let seconds: f64 = args[4].parse().context("Invalid duration")?;
    if !seconds.is_finite() || seconds <= 0.0 || seconds > 30.0 { bail!("Duration must be >0 and <=30 seconds for guarded calibration"); }
    let n_float = rps * seconds;
    if !n_float.is_finite() || n_float < 1.0 || n_float > 15000.0 { bail!("Calibration request count must be 1..15000"); }
    let count = n_float.round() as usize;
    let timeout_ms: u64 = args[5].parse()?;
    if timeout_ms == 0 || timeout_ms > 10000 { bail!("Timeout must be 1..10000ms"); }
    let max_inflight: usize = args[6].parse()?;
    if max_inflight == 0 || max_inflight > 1024 { bail!("max_inflight must be 1..1024"); }
    let workers: usize = std::env::var("COMET_LOADGEN_WORKERS").unwrap_or_else(|_| "2".into()).parse()?;
    if workers == 0 || workers > 32 { bail!("COMET_LOADGEN_WORKERS must be 1..32"); }
    let prefix = Path::new(&args[7]);
    let jsonl = prefix.with_extension("requests.jsonl");
    let summary = prefix.with_extension("summary.json");
    if jsonl.exists() || summary.exists() { bail!("Refusing to overwrite calibration results"); }
    let runtime = tokio::runtime::Builder::new_multi_thread().worker_threads(workers).enable_all().build()?;
    let client = http_client::HttpClient::new(Duration::from_millis(timeout_ms))?;
    let result = runtime.block_on(noop_dispatcher::dispatch(count, rps, uri, client, max_inflight))?;
    let mut file = std::fs::OpenOptions::new().write(true).create_new(true).open(&jsonl)?;
    for rec in &result.records { serde_json::to_writer(&mut file, rec)?; writeln!(file)?; }
    file.sync_all()?;
    let mut file = std::fs::OpenOptions::new().write(true).create_new(true).open(&summary)?;
    serde_json::to_writer_pretty(&mut file, &result.summary)?;
    file.sync_all()?;
    println!("NOOP CALIBRATION: {} requests, {} success, {} fail, {} timeout, {} dropped, achieved {:.2} success/s, P95 {:?} ms", result.summary.offered_requests, result.summary.successful_requests, result.summary.failed_requests, result.summary.timed_out_requests, result.summary.dropped_requests, result.summary.achieved_success_rps, result.summary.p95_latency_ms);
    println!("Summary: {}", summary.display());
    Ok(())
}

'''
    s=s.replace(anchor,func+anchor,1)
    anchor='    let args: Vec<String> = env::args().collect();'
    assert s.count(anchor)==1
    s=s.replace(anchor,anchor+'\n    if args.get(1).map(String::as_str) == Some("noop") { return run_noop_mode(&args); }',1)
main.write_text(s)
# Ingress worker count control: replace the Tokio main attribute with an explicit runtime wrapper.
p=ing/'src/main.rs'; s=p.read_text()
if '#[tokio::main]' in s and 'COMET_INGRESS_WORKERS' not in s:
    anchor='#[tokio::main]\nasync fn main() -> anyhow::Result<()> {'
    assert s.count(anchor)==1
    replacement='''fn main() -> anyhow::Result<()> {
    let workers: usize = std::env::var("COMET_INGRESS_WORKERS")
        .unwrap_or_else(|_| "2".to_string()).parse()?;
    anyhow::ensure!(workers > 0 && workers <= 32, "COMET_INGRESS_WORKERS must be 1..32");
    println!("Ingress Tokio workers: {workers}");
    tokio::runtime::Builder::new_multi_thread()
        .worker_threads(workers).enable_all().build()?.block_on(serve())
}

async fn serve() -> anyhow::Result<()> {'''
    s=s.replace(anchor,replacement,1)
p.write_text(s)
PY
cat > "$LOAD/src/noop_dispatcher.rs" <<'RS'
use anyhow::{bail, Result};
use hyper::{StatusCode, Uri};
use serde::Serialize;
use std::sync::Arc;
use tokio::{sync::Semaphore, task::JoinSet, time::{sleep_until, Instant}};
use crate::{http_client::HttpClient, schedule::scheduled_offset};

#[derive(Debug, Serialize)]
pub struct Record {
    sequence: usize,
    scheduled_ns: u128,
    dispatch_ns: Option<u128>,
    completion_ns: Option<u128>,
    scheduling_delay_ns: Option<u128>,
    latency_from_dispatch_ns: Option<u128>,
    latency_from_schedule_ns: Option<u128>,
    http_status: Option<u16>,
    success: bool,
    timed_out: bool,
    dropped: bool,
    error: Option<String>,
}
impl Record {
    fn new(sequence: usize, scheduled_ns: u128) -> Self {
        Self {sequence, scheduled_ns, dispatch_ns:None, completion_ns:None, scheduling_delay_ns:None, latency_from_dispatch_ns:None, latency_from_schedule_ns:None, http_status:None, success:false, timed_out:false, dropped:false, error:None}
    }
}
#[derive(Debug, Serialize)]
pub struct Summary {
    pub mode: &'static str,
    pub offered_rps: f64,
    pub offered_requests: usize,
    pub successful_requests: usize,
    pub failed_requests: usize,
    pub timed_out_requests: usize,
    pub dropped_requests: usize,
    pub elapsed_seconds: f64,
    pub achieved_success_rps: f64,
    pub p50_latency_ms: Option<f64>,
    pub p95_latency_ms: Option<f64>,
    pub p99_latency_ms: Option<f64>,
    pub p99_scheduling_delay_ms: Option<f64>,
}
pub struct Run { pub records: Vec<Record>, pub summary: Summary }
fn percentile(xs: &[u128], p:f64) -> Option<f64> {
    if xs.is_empty() {None} else {Some(xs[((xs.len()-1) as f64*p).ceil() as usize] as f64 / 1e6)}
}
pub async fn dispatch(count:usize, rps:f64, uri:Uri, client:HttpClient, max_inflight:usize) -> Result<Run> {
    if count==0 || max_inflight==0 { bail!("count and max_inflight must be positive"); }
    scheduled_offset(0,rps)?;
    let capacity=Arc::new(Semaphore::new(max_inflight));
    let start=Instant::now();
    let mut tasks=JoinSet::new();
    let mut records=Vec::with_capacity(count);
    for seq in 0..count {
        let offset=scheduled_offset(seq,rps)?;
        sleep_until(start+offset).await;
        let mut rec=Record::new(seq,offset.as_nanos());
        let permit=match capacity.clone().try_acquire_owned() {
            Ok(p)=>p,
            Err(_)=>{rec.dropped=true;rec.error=Some("inflight_capacity_exhausted".into());records.push(rec);continue;}
        };
        let client=client.clone();let uri=uri.clone();
        tasks.spawn(async move {
            let _permit=permit;
            let dispatched=start.elapsed().as_nanos();
            rec.dispatch_ns=Some(dispatched);
            rec.scheduling_delay_ns=Some(dispatched.saturating_sub(rec.scheduled_ns));
            let response=client.get_noop(uri).await;
            let completed=start.elapsed().as_nanos();
            rec.completion_ns=Some(completed);
            rec.latency_from_dispatch_ns=Some(completed.saturating_sub(dispatched));
            rec.latency_from_schedule_ns=Some(completed.saturating_sub(rec.scheduled_ns));
            match response {
                Ok(resp)=>{
                    rec.http_status=Some(resp.status.as_u16());
                    if resp.status==StatusCode::NO_CONTENT && resp.body.is_empty(){rec.success=true;}
                    else {rec.error=Some(format!("unexpected_status_or_body_{}",resp.status.as_u16()));}
                }
                Err(e)=>{let msg=e.to_string();rec.timed_out=msg.contains("HTTP request timed out");rec.error=Some(msg);}
            }
            rec
        });
    }
    while let Some(res)=tasks.join_next().await { records.push(res?); }
    let elapsed=start.elapsed().as_secs_f64();
    records.sort_by_key(|r|r.sequence);
    if records.len()!=count || records.iter().enumerate().any(|(i,r)|i!=r.sequence) {bail!("No-op accounting failed");}
    let mut lat:Vec<u128>=records.iter().filter(|r|r.success).filter_map(|r|r.latency_from_schedule_ns).collect();lat.sort_unstable();
    let mut delay:Vec<u128>=records.iter().filter_map(|r|r.scheduling_delay_ns).collect();delay.sort_unstable();
    let success=records.iter().filter(|r|r.success).count();
    let dropped=records.iter().filter(|r|r.dropped).count();
    let timed_out=records.iter().filter(|r|r.timed_out).count();
    let failed=count-success-dropped-timed_out;
    Ok(Run {summary:Summary {mode:"noop",offered_rps:rps,offered_requests:count,successful_requests:success,failed_requests:failed,timed_out_requests:timed_out,dropped_requests:dropped,elapsed_seconds:elapsed,achieved_success_rps:success as f64/elapsed,p50_latency_ms:percentile(&lat,0.5),p95_latency_ms:percentile(&lat,0.95),p99_latency_ms:percentile(&lat,0.99),p99_scheduling_delay_ms:percentile(&delay,0.99)},records})
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test] fn empty_percentile_is_none(){assert_eq!(percentile(&[],0.95),None);}
    #[test] fn percentile_calculation(){assert_eq!(percentile(&[1_000_000,2_000_000,3_000_000],0.5),Some(2.0));}
}
RS
# Existing GET method was implemented in previous step. Guard against partial state.
grep -q 'pub async fn get_noop' "$LOAD/src/http_client.rs" || { echo 'Missing get_noop; refusing to continue'; exit 1; }
(
cd "$LOAD"
cargo fmt
cargo test --locked --offline
cargo build --release --locked --offline
)
(
cd "$ING"
cargo fmt
cargo test --locked --offline
cargo build --release --locked --offline
)
# Start only our ingress process; clean it up on every exit.
ING_PID=''
cleanup(){ if [[ -n "$ING_PID" ]]; then kill "$ING_PID" 2>/dev/null || :; wait "$ING_PID" 2>/dev/null || :; fi; }
trap cleanup EXIT
# Use a synthetic route configuration, avoiding Wasmtime module loading or real inference.
cat > "$OUT/noop_routes.json" <<'JSON'
{"0":{"backend":"native","model":"lr","url":"http://127.0.0.1:18999/infer"}}
JSON
COMET_INGRESS_WORKERS=2 "$ING/target/release/comet_common_ingress" "$OUT/noop_routes.json" >"$OUT/ingress.log" 2>&1 &
ING_PID=$!
READY=0
for _ in $(seq 1 40); do
 if ! kill -0 "$ING_PID" 2>/dev/null; then echo 'Ingress exited unexpectedly'; cat "$OUT/ingress.log"; exit 1; fi
 if curl -fsS --max-time 1 http://127.0.0.1:8200/health >/dev/null 2>&1; then READY=1; break; fi
 sleep 0.25
done
[[ "$READY" == 1 ]] || { echo 'Ingress did not become healthy'; exit 1; }
[[ "$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 http://127.0.0.1:8200/noop)" == 204 ]] || { echo 'No-op did not return 204'; exit 1; }
# Controlled preliminary calibration only; not a paper-ready saturation sweep.
for rps in 100 300 600; do
  echo "===== PRELIMINARY NO-OP: $rps RPS, 5s ====="
  COMET_LOADGEN_WORKERS=2 "$LOAD/target/release/comet_v2_loadgen" noop http://127.0.0.1:8200/noop "$rps" 5 1000 128 "$OUT/noop_${rps}rps"
done
python3 - "$OUT" <<'PY'
import json, pathlib, sys
out=pathlib.Path(sys.argv[1]); rows=[]
for rps in (100,300,600):
 p=out/f'noop_{rps}rps.summary.json'
 s=json.loads(p.read_text())
 recs=[json.loads(line) for line in (out/f'noop_{rps}rps.requests.jsonl').read_text().splitlines()]
 assert len(recs)==s['offered_requests']
 assert sorted(r['sequence'] for r in recs)==list(range(len(recs)))
 assert s['offered_requests']==sum(s[k] for k in ('successful_requests','failed_requests','timed_out_requests','dropped_requests'))
 assert all(r['http_status']==204 for r in recs if r['success'])
 rows.append(s)
 print(f"{rps} RPS: success={s['successful_requests']}/{s['offered_requests']}, achieved={s['achieved_success_rps']:.1f}/s, P95={s['p95_latency_ms']}ms, P99 schedule delay={s['p99_scheduling_delay_ms']}ms")
(out/'calibration_index.json').write_text(json.dumps(rows,indent=2))
print('PASS: all calibration accounting checks')
PY
printf '\nCOMPLETE. Preliminary calibration files: %s\n' "$OUT"
printf 'Not a full inference campaign. Ingress will be stopped automatically.\n'
