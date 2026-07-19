use serde::{Deserialize, Serialize};

use super::{
    DeliveryAttemptRecord, DeliveryDedupeKey, ExternalDeliveryResult, ExternalDeliveryStatus,
};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum HostDeliveryDiagnosticSeverity {
    Info,
    Warning,
    Error,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct HostDeliveryDiagnostic {
    pub running_alert_id: String,
    pub script_snapshot_id: String,
    pub adapter_id: String,
    pub dedupe_key: DeliveryDedupeKey,
    pub severity: HostDeliveryDiagnosticSeverity,
    pub code: String,
    pub message: String,
}

pub fn host_delivery_diagnostic_from_result(
    attempt: &DeliveryAttemptRecord,
    result: &ExternalDeliveryResult,
) -> Option<HostDeliveryDiagnostic> {
    let severity = match result.status {
        ExternalDeliveryStatus::Delivered => return None,
        ExternalDeliveryStatus::TransientFailure => HostDeliveryDiagnosticSeverity::Warning,
        ExternalDeliveryStatus::PermanentFailure => HostDeliveryDiagnosticSeverity::Error,
    };
    let code = result
        .failure_code
        .as_deref()
        .map(sanitize_failure_code)
        .unwrap_or_else(|| default_failure_code(result.status).to_owned());
    let mut message = format!(
        "external delivery {} for adapter {} attempt {}",
        status_label(result.status),
        attempt.adapter_id,
        attempt.attempt_number
    );
    if let Some(provider_status_class) = result
        .provider_status_code
        .as_deref()
        .and_then(redacted_provider_status_class)
    {
        message.push_str(" with provider status class ");
        message.push_str(provider_status_class);
    }

    Some(HostDeliveryDiagnostic {
        running_alert_id: attempt.dedupe_key.running_alert_id.clone(),
        script_snapshot_id: attempt.dedupe_key.script_snapshot_id.clone(),
        adapter_id: attempt.adapter_id.clone(),
        dedupe_key: attempt.dedupe_key.clone(),
        severity,
        code,
        message,
    })
}

fn sanitize_failure_code(code: &str) -> String {
    let trimmed = code.trim();
    if !trimmed.is_empty()
        && trimmed.len() <= 64
        && trimmed
            .chars()
            .all(|ch| ch.is_ascii_alphanumeric() || matches!(ch, '_' | '-' | '.'))
    {
        trimmed.to_owned()
    } else {
        "externalDeliveryFailure".to_owned()
    }
}

fn default_failure_code(status: ExternalDeliveryStatus) -> &'static str {
    match status {
        ExternalDeliveryStatus::Delivered => "externalDeliveryDelivered",
        ExternalDeliveryStatus::TransientFailure => "externalDeliveryTransientFailure",
        ExternalDeliveryStatus::PermanentFailure => "externalDeliveryPermanentFailure",
    }
}

fn status_label(status: ExternalDeliveryStatus) -> &'static str {
    match status {
        ExternalDeliveryStatus::Delivered => "delivered",
        ExternalDeliveryStatus::TransientFailure => "transientFailure",
        ExternalDeliveryStatus::PermanentFailure => "permanentFailure",
    }
}

fn redacted_provider_status_class(status_code: &str) -> Option<&'static str> {
    match status_code.trim() {
        "1xx" => Some("1xx"),
        "2xx" => Some("2xx"),
        "3xx" => Some("3xx"),
        "4xx" => Some("4xx"),
        "5xx" => Some("5xx"),
        text => text.parse::<u16>().ok().and_then(|code| match code {
            100..=199 => Some("1xx"),
            200..=299 => Some("2xx"),
            300..=399 => Some("3xx"),
            400..=499 => Some("4xx"),
            500..=599 => Some("5xx"),
            _ => None,
        }),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::output::delivery::{DeliveryEventKind, ExternalDeliveryResult};

    fn attempt(attempt_number: u32) -> DeliveryAttemptRecord {
        DeliveryAttemptRecord::new(
            DeliveryDedupeKey {
                running_alert_id: "alert-1".to_owned(),
                script_snapshot_id: "snapshot-1".to_owned(),
                event_kind: DeliveryEventKind::StrategyOrderFill,
                bar_index: 2,
                time: 300,
                event_id: "XL".to_owned(),
            },
            "webhook-main",
            attempt_number,
            1_000,
        )
    }

    #[test]
    fn delivered_result_does_not_emit_host_delivery_diagnostic() {
        assert_eq!(
            host_delivery_diagnostic_from_result(
                &attempt(1),
                &ExternalDeliveryResult::delivered(2_000)
            ),
            None
        );
    }

    #[test]
    fn transient_failure_emits_warning_host_delivery_diagnostic() {
        let diagnostic = host_delivery_diagnostic_from_result(
            &attempt(2),
            &ExternalDeliveryResult::transient_failure(
                2_000,
                "webhookTransportTimeout",
                "timeout with sensitive detail",
            )
            .with_provider_status_code("503"),
        )
        .expect("diagnostic");

        assert_eq!(diagnostic.severity, HostDeliveryDiagnosticSeverity::Warning);
        assert_eq!(diagnostic.code, "webhookTransportTimeout");
        assert_eq!(diagnostic.running_alert_id, "alert-1");
        assert_eq!(diagnostic.script_snapshot_id, "snapshot-1");
        assert_eq!(diagnostic.adapter_id, "webhook-main");
        assert_eq!(
            diagnostic.message,
            "external delivery transientFailure for adapter webhook-main attempt 2 with provider status class 5xx"
        );
    }

    #[test]
    fn permanent_failure_emits_error_host_delivery_diagnostic() {
        let diagnostic = host_delivery_diagnostic_from_result(
            &attempt(1),
            &ExternalDeliveryResult::permanent_failure(
                2_000,
                "webhookProviderRejected",
                "provider rejected",
            )
            .with_provider_status_code("4xx"),
        )
        .expect("diagnostic");

        assert_eq!(diagnostic.severity, HostDeliveryDiagnosticSeverity::Error);
        assert_eq!(diagnostic.code, "webhookProviderRejected");
        assert_eq!(
            diagnostic.message,
            "external delivery permanentFailure for adapter webhook-main attempt 1 with provider status class 4xx"
        );
    }

    #[test]
    fn diagnostic_redacts_failure_message_and_unsafely_shaped_codes() {
        let diagnostic = host_delivery_diagnostic_from_result(
            &attempt(1),
            &ExternalDeliveryResult::permanent_failure(
                2_000,
                "secret=abc123",
                "Authorization: Bearer abc123",
            )
            .with_provider_status_code("Authorization: Bearer abc123"),
        )
        .expect("diagnostic");

        assert_eq!(diagnostic.code, "externalDeliveryFailure");
        assert!(!diagnostic.message.contains("Bearer"));
        assert!(!diagnostic.message.contains("abc123"));
        assert!(!diagnostic.message.contains("Authorization"));
    }

    #[test]
    fn diagnostic_serializes_host_owned_camel_case_shape() {
        let diagnostic = host_delivery_diagnostic_from_result(
            &attempt(1),
            &ExternalDeliveryResult::transient_failure(2_000, "timeout", "timeout"),
        )
        .expect("diagnostic");

        let value = serde_json::to_value(diagnostic).expect("diagnostic serializes");

        assert_eq!(
            value,
            serde_json::json!({
                "runningAlertId": "alert-1",
                "scriptSnapshotId": "snapshot-1",
                "adapterId": "webhook-main",
                "dedupeKey": {
                    "runningAlertId": "alert-1",
                    "scriptSnapshotId": "snapshot-1",
                    "eventKind": "strategyOrderFill",
                    "barIndex": 2,
                    "time": 300,
                    "eventId": "XL",
                },
                "severity": "warning",
                "code": "timeout",
                "message": "external delivery transientFailure for adapter webhook-main attempt 1",
            })
        );
    }
}
