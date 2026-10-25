use crate::{http_client::HttpClient, schedule::scheduled_offset};
use anyhow::{bail, Result};
use hyper::{StatusCode, Uri};
use serde::Serialize;
use std::sync::Arc;
use tokio::{
    sync::Semaphore,
    task::JoinSet,
    time::{sleep_until, Instant},
};

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
        Self {
            sequence,
            scheduled_ns,
            dispatch_ns: None,
            completion_ns: None,
            scheduling_delay_ns: None,
            latency_from_dispatch_ns: None,
            latency_from_schedule_ns: None,
            http_status: None,
            success: false,
            timed_out: false,
            dropped: false,
            error: None,
        }
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
pub struct Run {
    pub records: Vec<Record>,
    pub summary: Summary,
}
fn percentile(xs: &[u128], p: f64) -> Option<f64> {
    if xs.is_empty() {
        None
    } else {
        Some(xs[((xs.len() - 1) as f64 * p).ceil() as usize] as f64 / 1e6)
    }
}
pub async fn dispatch(
    count: usize,
    rps: f64,
    uri: Uri,
    client: HttpClient,
    max_inflight: usize,
) -> Result<Run> {
    if count == 0 || max_inflight == 0 {
        bail!("count and max_inflight must be positive");
    }
    scheduled_offset(0, rps)?;
    let capacity = Arc::new(Semaphore::new(max_inflight));
    let start = Instant::now();
    let mut tasks = JoinSet::new();
    let mut records = Vec::with_capacity(count);
    for seq in 0..count {
        let offset = scheduled_offset(seq, rps)?;
        sleep_until(start + offset).await;
        let mut rec = Record::new(seq, offset.as_nanos());
        let permit = match capacity.clone().try_acquire_owned() {
            Ok(p) => p,
            Err(_) => {
                rec.dropped = true;
                rec.error = Some("inflight_capacity_exhausted".into());
                records.push(rec);
                continue;
            }
        };
        let client = client.clone();
        let uri = uri.clone();
        tasks.spawn(async move {
            let _permit = permit;
            let dispatched = start.elapsed().as_nanos();
            rec.dispatch_ns = Some(dispatched);
            rec.scheduling_delay_ns = Some(dispatched.saturating_sub(rec.scheduled_ns));
            let response = client.get_noop(uri).await;
            let completed = start.elapsed().as_nanos();
            rec.completion_ns = Some(completed);
            rec.latency_from_dispatch_ns = Some(completed.saturating_sub(dispatched));
            rec.latency_from_schedule_ns = Some(completed.saturating_sub(rec.scheduled_ns));
            match response {
                Ok(resp) => {
                    rec.http_status = Some(resp.status.as_u16());
                    if resp.status == StatusCode::NO_CONTENT && resp.body.is_empty() {
                        rec.success = true;
                    } else {
                        rec.error = Some(format!(
                            "unexpected_status_or_body_{}",
                            resp.status.as_u16()
                        ));
                    }
                }
                Err(e) => {
                    let msg = e.to_string();
                    rec.timed_out = msg.contains("HTTP request timed out");
                    rec.error = Some(msg);
                }
            }
            rec
        });
    }
    while let Some(res) = tasks.join_next().await {
        records.push(res?);
    }
    let elapsed = start.elapsed().as_secs_f64();
    records.sort_by_key(|r| r.sequence);
    if records.len() != count || records.iter().enumerate().any(|(i, r)| i != r.sequence) {
        bail!("No-op accounting failed");
    }
    let mut lat: Vec<u128> = records
        .iter()
        .filter(|r| r.success)
        .filter_map(|r| r.latency_from_schedule_ns)
        .collect();
    lat.sort_unstable();
    let mut delay: Vec<u128> = records
        .iter()
        .filter_map(|r| r.scheduling_delay_ns)
        .collect();
    delay.sort_unstable();
    let success = records.iter().filter(|r| r.success).count();
    let dropped = records.iter().filter(|r| r.dropped).count();
    let timed_out = records.iter().filter(|r| r.timed_out).count();
    let failed = count - success - dropped - timed_out;
    Ok(Run {
        summary: Summary {
            mode: "noop",
            offered_rps: rps,
            offered_requests: count,
            successful_requests: success,
            failed_requests: failed,
            timed_out_requests: timed_out,
            dropped_requests: dropped,
            elapsed_seconds: elapsed,
            achieved_success_rps: success as f64 / elapsed,
            p50_latency_ms: percentile(&lat, 0.5),
            p95_latency_ms: percentile(&lat, 0.95),
            p99_latency_ms: percentile(&lat, 0.99),
            p99_scheduling_delay_ms: percentile(&delay, 0.99),
        },
        records,
    })
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn empty_percentile_is_none() {
        assert_eq!(percentile(&[], 0.95), None);
    }
    #[test]
    fn percentile_calculation() {
        assert_eq!(
            percentile(&[1_000_000, 2_000_000, 3_000_000], 0.5),
            Some(2.0)
        );
    }
}
