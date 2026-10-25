use serde::Serialize;

#[derive(Debug, Clone, Serialize)]
pub struct RequestRecord {
    pub sequence: usize,
    pub request_id: String,
    pub tenant_slot: usize,
    pub model: String,
    pub expected_prediction: i64,

    pub scheduled_ns: u128,
    pub dispatch_ns: Option<u128>,
    pub completion_ns: Option<u128>,

    pub scheduling_delay_ns: Option<u128>,
    pub latency_from_dispatch_ns: Option<u128>,
    pub latency_from_schedule_ns: Option<u128>,

    pub http_status: Option<u16>,
    pub actual_prediction: Option<i64>,
    pub served_backend: Option<String>,

    pub success: bool,
    pub timed_out: bool,
    pub dropped: bool,
    pub error: Option<String>,
}

impl RequestRecord {
    pub fn new(
        sequence: usize,
        request_id: String,
        tenant_slot: usize,
        model: String,
        expected_prediction: i64,
        scheduled_ns: u128,
    ) -> Self {
        Self {
            sequence,
            request_id,
            tenant_slot,
            model,
            expected_prediction,
            scheduled_ns,
            dispatch_ns: None,
            completion_ns: None,
            scheduling_delay_ns: None,
            latency_from_dispatch_ns: None,
            latency_from_schedule_ns: None,
            http_status: None,
            actual_prediction: None,
            served_backend: None,
            success: false,
            timed_out: false,
            dropped: false,
            error: None,
        }
    }

    pub fn record_dispatch(&mut self, dispatch_ns: u128) {
        self.dispatch_ns = Some(dispatch_ns);
        self.scheduling_delay_ns = Some(dispatch_ns.saturating_sub(self.scheduled_ns));
    }

    pub fn record_completion(&mut self, completion_ns: u128) {
        self.completion_ns = Some(completion_ns);

        if let Some(dispatch_ns) = self.dispatch_ns {
            self.latency_from_dispatch_ns = Some(completion_ns.saturating_sub(dispatch_ns));
        }

        self.latency_from_schedule_ns = Some(completion_ns.saturating_sub(self.scheduled_ns));
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn records_both_latency_definitions() {
        let mut record = RequestRecord::new(0, "v2-00000000".into(), 0, "lr".into(), 1, 1_000);

        record.record_dispatch(1_200);
        record.record_completion(2_000);

        assert_eq!(record.scheduling_delay_ns, Some(200));
        assert_eq!(record.latency_from_dispatch_ns, Some(800));
        assert_eq!(record.latency_from_schedule_ns, Some(1_000));
    }

    #[test]
    fn pending_request_has_no_fabricated_latency() {
        let record = RequestRecord::new(0, "v2-00000000".into(), 0, "lr".into(), 1, 1_000);

        assert!(record.dispatch_ns.is_none());
        assert!(record.completion_ns.is_none());
        assert!(record.latency_from_schedule_ns.is_none());
        assert!(!record.success);
    }
}
