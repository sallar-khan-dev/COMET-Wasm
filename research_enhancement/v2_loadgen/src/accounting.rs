use anyhow::{bail, Result};
use std::collections::HashSet;

use crate::request_record::RequestRecord;

pub fn validate_records(records: &[RequestRecord], offered: usize) -> Result<()> {
    if records.len() != offered {
        bail!(
            "Request accounting mismatch: offered={}, recorded={}",
            offered,
            records.len()
        );
    }

    let mut seen = HashSet::with_capacity(records.len());

    for record in records {
        if record.sequence >= offered {
            bail!("Request sequence outside offered range");
        }

        if !seen.insert(record.sequence) {
            bail!("Duplicate request sequence: {}", record.sequence);
        }

        if record.dropped {
            if record.success
                || record.timed_out
                || record.dispatch_ns.is_some()
                || record.completion_ns.is_some()
                || record.http_status.is_some()
            {
                bail!("Contradictory dropped-request state");
            }
        }

        if record.success {
            if record.timed_out
                || record.dropped
                || record.http_status != Some(200)
                || record.actual_prediction != Some(record.expected_prediction)
                || record.dispatch_ns.is_none()
                || record.completion_ns.is_none()
            {
                bail!("Contradictory successful-request state");
            }
        }

        if record.timed_out && (record.success || record.dropped) {
            bail!("Contradictory timeout state");
        }

        if record.completion_ns.is_some() && record.dispatch_ns.is_none() {
            bail!("Completion without dispatch");
        }
    }

    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn record(sequence: usize) -> RequestRecord {
        RequestRecord::new(sequence, format!("v2-{sequence:08}"), 0, "lr".into(), 1, 0)
    }

    #[test]
    fn accepts_complete_records() {
        let records = vec![record(0), record(1)];
        assert!(validate_records(&records, 2).is_ok());
    }

    #[test]
    fn rejects_missing_records() {
        assert!(validate_records(&[record(0)], 2).is_err());
    }

    #[test]
    fn rejects_duplicate_sequences() {
        assert!(validate_records(&[record(0), record(0)], 2).is_err());
    }

    #[test]
    fn rejects_contradictory_drop() {
        let mut dropped = record(0);
        dropped.dropped = true;
        dropped.record_dispatch(10);

        assert!(validate_records(&[dropped], 1).is_err());
    }
}
