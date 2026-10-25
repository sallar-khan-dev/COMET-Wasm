use anyhow::{bail, Result};
use std::time::Duration;

/// Deterministic, evenly spaced open-loop arrival schedule.
///
/// Arrival n is calculated independently of request completion.
/// `rate_rps` is the offered arrival rate, not achieved throughput.
pub fn scheduled_offset(sequence: usize, rate_rps: f64) -> Result<Duration> {
    if !rate_rps.is_finite() || rate_rps <= 0.0 {
        bail!("Offered RPS must be finite and positive");
    }

    let seconds = (sequence as f64) / rate_rps;

    if !seconds.is_finite() || seconds > Duration::MAX.as_secs_f64() {
        bail!("Scheduled arrival exceeds supported duration");
    }

    Ok(Duration::from_secs_f64(seconds))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn first_request_arrives_at_zero() {
        assert_eq!(scheduled_offset(0, 100.0).unwrap(), Duration::ZERO);
    }

    #[test]
    fn one_hundred_rps_has_ten_ms_spacing() {
        assert_eq!(
            scheduled_offset(1, 100.0).unwrap(),
            Duration::from_millis(10)
        );
        assert_eq!(
            scheduled_offset(100, 100.0).unwrap(),
            Duration::from_secs(1)
        );
    }

    #[test]
    fn schedule_does_not_depend_on_completion() {
        let expected = scheduled_offset(50, 25.0).unwrap();
        assert_eq!(expected, Duration::from_secs(2));
    }

    #[test]
    fn invalid_rates_are_rejected() {
        for rate in [0.0, -1.0, f64::NAN, f64::INFINITY] {
            assert!(scheduled_offset(1, rate).is_err());
        }
    }
}
