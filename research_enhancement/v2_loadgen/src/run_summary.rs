use serde::Serialize;

use crate::request_record::RequestRecord;

#[derive(Debug, Serialize)]
pub struct RunSummary {
    pub offered_requests: usize,
    pub successful_requests: usize,
    pub failed_requests: usize,
    pub timed_out_requests: usize,
    pub dropped_requests: usize,
    pub p50_latency_ms: Option<f64>,
    pub p95_latency_ms: Option<f64>,
    pub p99_latency_ms: Option<f64>,
}

fn percentile(sorted: &[u128], p: f64) -> Option<f64> {
    if sorted.is_empty() {
        return None;
    }

    let rank = ((sorted.len() as f64 - 1.0) * p).ceil() as usize;
    Some(sorted[rank] as f64 / 1_000_000.0)
}

pub fn summarize(records: &[RequestRecord]) -> RunSummary {
    let mut latencies = Vec::new();

    let mut successful = 0;
    let mut failed = 0;
    let mut timed_out = 0;
    let mut dropped = 0;

    for record in records {
        if record.dropped {
            dropped += 1;
        } else if record.timed_out {
            timed_out += 1;
        } else if record.success {
            successful += 1;

            if let Some(latency) = record.latency_from_schedule_ns {
                latencies.push(latency);
            }
        } else {
            failed += 1;
        }
    }

    latencies.sort_unstable();

    RunSummary {
        offered_requests: records.len(),
        successful_requests: successful,
        failed_requests: failed,
        timed_out_requests: timed_out,
        dropped_requests: dropped,
        p50_latency_ms: percentile(&latencies, 0.50),
        p95_latency_ms: percentile(&latencies, 0.95),
        p99_latency_ms: percentile(&latencies, 0.99),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn computes_counts_and_percentiles() {
        let mut records = Vec::new();

        for sequence in 0..5 {
            let mut record =
                RequestRecord::new(sequence, format!("v2-{sequence:08}"), 0, "lr".into(), 1, 0);

            record.record_dispatch(0);
            record.record_completion((sequence as u128 + 1) * 1_000_000);
            record.http_status = Some(200);
            record.actual_prediction = Some(1);
            record.success = true;

            records.push(record);
        }

        let summary = summarize(&records);

        assert_eq!(summary.offered_requests, 5);
        assert_eq!(summary.successful_requests, 5);
        assert_eq!(summary.failed_requests, 0);
        assert_eq!(summary.p50_latency_ms, Some(3.0));
        assert_eq!(summary.p95_latency_ms, Some(5.0));
        assert_eq!(summary.p99_latency_ms, Some(5.0));
    }

    #[test]
    fn separates_dropped_and_timed_out_requests() {
        let mut dropped = RequestRecord::new(0, "a".into(), 0, "lr".into(), 1, 0);
        dropped.dropped = true;

        let mut timeout = RequestRecord::new(1, "b".into(), 0, "lr".into(), 1, 0);
        timeout.record_dispatch(100);
        timeout.record_completion(200);
        timeout.timed_out = true;

        let summary = summarize(&[dropped, timeout]);

        assert_eq!(summary.dropped_requests, 1);
        assert_eq!(summary.timed_out_requests, 1);
        assert_eq!(summary.successful_requests, 0);
        assert_eq!(summary.failed_requests, 0);
        assert!(summary.p95_latency_ms.is_none());
    }
}
