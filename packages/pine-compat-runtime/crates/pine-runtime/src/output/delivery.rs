use std::collections::{BTreeMap, BTreeSet};

use serde::{Deserialize, Serialize};

use super::running_alerts::{
    RunningAlertConfig, RunningAlertEvaluationError, render_strategy_order_fill_running_alert,
};
use super::strategy::StrategyOrderFillAlertOutput;

mod diagnostics;
mod webhook;

pub use diagnostics::{
    HostDeliveryDiagnostic, HostDeliveryDiagnosticSeverity, host_delivery_diagnostic_from_result,
};
pub use webhook::{
    WebhookAdapterConfig, WebhookAdapterConfigError, WebhookBodyMode, WebhookDeliveryAdapter,
    WebhookDeliveryFailure, WebhookPayload, WebhookPayloadError, WebhookRequest,
    WebhookRequestError, WebhookResolvedHeaders, WebhookResolvedHeadersError, WebhookRetryDecision,
    WebhookRetryPolicy, WebhookRetryPolicyError, WebhookRetryRecordError, WebhookSecretResolver,
    WebhookSecretResolverError, WebhookTransport, WebhookTransportOutcome, build_webhook_request,
    classify_webhook_delivery_failure, classify_webhook_http_status, plan_and_record_webhook_retry,
    plan_webhook_retry, render_webhook_payload, resolve_webhook_headers,
};

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum DeliveryEventKind {
    IndicatorAlertCall,
    StrategyOrderFill,
}

impl DeliveryEventKind {
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::IndicatorAlertCall => "indicatorAlertCall",
            Self::StrategyOrderFill => "strategyOrderFill",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DeliveryCandidate {
    pub running_alert_id: String,
    pub script_snapshot_id: String,
    pub event_kind: DeliveryEventKind,
    pub bar_index: usize,
    pub time: i64,
    pub event_id: String,
    pub rendered_message: String,
}

impl DeliveryCandidate {
    pub fn new(
        running_alert_id: impl Into<String>,
        script_snapshot_id: impl Into<String>,
        event_kind: DeliveryEventKind,
        bar_index: usize,
        time: i64,
        event_id: impl Into<String>,
        rendered_message: impl Into<String>,
    ) -> Self {
        Self {
            running_alert_id: running_alert_id.into(),
            script_snapshot_id: script_snapshot_id.into(),
            event_kind,
            bar_index,
            time,
            event_id: event_id.into(),
            rendered_message: rendered_message.into(),
        }
    }

    pub fn dedupe_key(&self) -> DeliveryDedupeKey {
        DeliveryDedupeKey {
            running_alert_id: self.running_alert_id.clone(),
            script_snapshot_id: self.script_snapshot_id.clone(),
            event_kind: self.event_kind,
            bar_index: self.bar_index,
            time: self.time,
            event_id: self.event_id.clone(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DeliveryDedupeKey {
    pub running_alert_id: String,
    pub script_snapshot_id: String,
    pub event_kind: DeliveryEventKind,
    pub bar_index: usize,
    pub time: i64,
    pub event_id: String,
}

impl From<&DeliveryCandidate> for DeliveryDedupeKey {
    fn from(candidate: &DeliveryCandidate) -> Self {
        candidate.dedupe_key()
    }
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ExternalDeliveryIdentity {
    pub adapter_id: String,
    pub dedupe_key: DeliveryDedupeKey,
}

impl ExternalDeliveryIdentity {
    pub fn new(adapter_id: impl Into<String>, dedupe_key: DeliveryDedupeKey) -> Self {
        Self {
            adapter_id: adapter_id.into(),
            dedupe_key,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum DeliveryAttemptStatus {
    Pending,
    InFlight,
    Delivered,
    TransientFailure,
    PermanentFailure,
}

impl DeliveryAttemptStatus {
    pub fn is_terminal(&self) -> bool {
        matches!(self, Self::Delivered | Self::PermanentFailure)
    }

    pub fn is_retryable_failure(&self) -> bool {
        matches!(self, Self::TransientFailure)
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct DeliveryAttemptRecord {
    pub dedupe_key: DeliveryDedupeKey,
    pub adapter_id: String,
    pub attempt_number: u32,
    pub status: DeliveryAttemptStatus,
    pub scheduled_at: i64,
    pub started_at: Option<i64>,
    pub completed_at: Option<i64>,
    pub next_retry_at: Option<i64>,
    pub failure_code: Option<String>,
}

impl DeliveryAttemptRecord {
    pub fn new(
        dedupe_key: DeliveryDedupeKey,
        adapter_id: impl Into<String>,
        attempt_number: u32,
        scheduled_at: i64,
    ) -> Self {
        Self {
            dedupe_key,
            adapter_id: adapter_id.into(),
            attempt_number,
            status: DeliveryAttemptStatus::Pending,
            scheduled_at,
            started_at: None,
            completed_at: None,
            next_retry_at: None,
            failure_code: None,
        }
    }

    pub fn external_identity(&self) -> ExternalDeliveryIdentity {
        ExternalDeliveryIdentity::new(self.adapter_id.clone(), self.dedupe_key.clone())
    }

    pub fn start(mut self, started_at: i64) -> Self {
        self.status = DeliveryAttemptStatus::InFlight;
        self.started_at = Some(started_at);
        self
    }

    pub fn complete(mut self, result: &ExternalDeliveryResult) -> Self {
        self.status = result.status.into();
        self.completed_at = Some(result.completed_at);
        self.failure_code = result.failure_code.clone();
        self
    }

    pub fn schedule_retry(mut self, next_retry_at: i64) -> Self {
        self.next_retry_at = Some(next_retry_at);
        self
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum ExternalDeliveryStatus {
    Delivered,
    TransientFailure,
    PermanentFailure,
}

impl ExternalDeliveryStatus {
    pub fn is_retryable_failure(&self) -> bool {
        matches!(self, Self::TransientFailure)
    }
}

impl From<ExternalDeliveryStatus> for DeliveryAttemptStatus {
    fn from(status: ExternalDeliveryStatus) -> Self {
        match status {
            ExternalDeliveryStatus::Delivered => Self::Delivered,
            ExternalDeliveryStatus::TransientFailure => Self::TransientFailure,
            ExternalDeliveryStatus::PermanentFailure => Self::PermanentFailure,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ExternalDeliveryResult {
    pub status: ExternalDeliveryStatus,
    pub provider_status_code: Option<String>,
    pub failure_code: Option<String>,
    pub failure_message: Option<String>,
    pub completed_at: i64,
}

impl ExternalDeliveryResult {
    pub fn delivered(completed_at: i64) -> Self {
        Self {
            status: ExternalDeliveryStatus::Delivered,
            provider_status_code: None,
            failure_code: None,
            failure_message: None,
            completed_at,
        }
    }

    pub fn transient_failure(
        completed_at: i64,
        failure_code: impl Into<String>,
        failure_message: impl Into<String>,
    ) -> Self {
        Self {
            status: ExternalDeliveryStatus::TransientFailure,
            provider_status_code: None,
            failure_code: Some(failure_code.into()),
            failure_message: Some(failure_message.into()),
            completed_at,
        }
    }

    pub fn permanent_failure(
        completed_at: i64,
        failure_code: impl Into<String>,
        failure_message: impl Into<String>,
    ) -> Self {
        Self {
            status: ExternalDeliveryStatus::PermanentFailure,
            provider_status_code: None,
            failure_code: Some(failure_code.into()),
            failure_message: Some(failure_message.into()),
            completed_at,
        }
    }

    pub fn with_provider_status_code(mut self, status_code: impl Into<String>) -> Self {
        self.provider_status_code = Some(status_code.into());
        self
    }
}

pub trait DeliveryAttemptStore {
    fn reserve(
        &mut self,
        dedupe_key: DeliveryDedupeKey,
        adapter_id: String,
        scheduled_at: i64,
    ) -> DeliveryAttemptRecord;

    fn start(
        &mut self,
        identity: &ExternalDeliveryIdentity,
        attempt_number: u32,
        started_at: i64,
    ) -> Option<DeliveryAttemptRecord>;

    fn complete(
        &mut self,
        identity: &ExternalDeliveryIdentity,
        attempt_number: u32,
        result: &ExternalDeliveryResult,
    ) -> Option<DeliveryAttemptRecord>;

    fn schedule_retry(
        &mut self,
        identity: &ExternalDeliveryIdentity,
        attempt_number: u32,
        next_retry_at: i64,
    ) -> Option<DeliveryAttemptRecord>;
}

#[derive(Debug, Clone, Default)]
pub struct InMemoryDeliveryAttemptStore {
    attempts: BTreeMap<ExternalDeliveryIdentity, Vec<DeliveryAttemptRecord>>,
}

impl InMemoryDeliveryAttemptStore {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn attempts(&self, identity: &ExternalDeliveryIdentity) -> &[DeliveryAttemptRecord] {
        self.attempts
            .get(identity)
            .map(Vec::as_slice)
            .unwrap_or(&[])
    }

    pub fn latest_attempt(
        &self,
        identity: &ExternalDeliveryIdentity,
    ) -> Option<&DeliveryAttemptRecord> {
        self.attempts(identity).last()
    }

    pub fn identity_count(&self) -> usize {
        self.attempts.len()
    }

    fn find_attempt_mut(
        &mut self,
        identity: &ExternalDeliveryIdentity,
        attempt_number: u32,
    ) -> Option<&mut DeliveryAttemptRecord> {
        self.attempts
            .get_mut(identity)?
            .iter_mut()
            .find(|attempt| attempt.attempt_number == attempt_number)
    }
}

impl DeliveryAttemptStore for InMemoryDeliveryAttemptStore {
    fn reserve(
        &mut self,
        dedupe_key: DeliveryDedupeKey,
        adapter_id: String,
        scheduled_at: i64,
    ) -> DeliveryAttemptRecord {
        let identity = ExternalDeliveryIdentity::new(adapter_id.clone(), dedupe_key.clone());
        let attempts = self.attempts.entry(identity).or_default();
        let next_attempt_number = attempts
            .len()
            .checked_add(1)
            .and_then(|count| u32::try_from(count).ok())
            .expect("delivery attempt count fits in u32");
        let record =
            DeliveryAttemptRecord::new(dedupe_key, adapter_id, next_attempt_number, scheduled_at);
        attempts.push(record.clone());
        record
    }

    fn start(
        &mut self,
        identity: &ExternalDeliveryIdentity,
        attempt_number: u32,
        started_at: i64,
    ) -> Option<DeliveryAttemptRecord> {
        let attempt = self.find_attempt_mut(identity, attempt_number)?;
        *attempt = attempt.clone().start(started_at);
        Some(attempt.clone())
    }

    fn complete(
        &mut self,
        identity: &ExternalDeliveryIdentity,
        attempt_number: u32,
        result: &ExternalDeliveryResult,
    ) -> Option<DeliveryAttemptRecord> {
        let attempt = self.find_attempt_mut(identity, attempt_number)?;
        *attempt = attempt.clone().complete(result);
        Some(attempt.clone())
    }

    fn schedule_retry(
        &mut self,
        identity: &ExternalDeliveryIdentity,
        attempt_number: u32,
        next_retry_at: i64,
    ) -> Option<DeliveryAttemptRecord> {
        let attempt = self.find_attempt_mut(identity, attempt_number)?;
        *attempt = attempt.clone().schedule_retry(next_retry_at);
        Some(attempt.clone())
    }
}

pub trait ExternalDeliveryAdapter {
    fn adapter_id(&self) -> &str;

    fn deliver(
        &mut self,
        candidate: &DeliveryCandidate,
        attempt: &DeliveryAttemptRecord,
    ) -> ExternalDeliveryResult;
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct TestCollectorDeliveryRecord {
    pub candidate: DeliveryCandidate,
    pub attempt: DeliveryAttemptRecord,
}

#[derive(Debug, Clone)]
pub struct TestCollectorDeliveryAdapter {
    adapter_id: String,
    completed_at: i64,
    collected: Vec<TestCollectorDeliveryRecord>,
}

impl TestCollectorDeliveryAdapter {
    pub fn new(adapter_id: impl Into<String>, completed_at: i64) -> Self {
        Self {
            adapter_id: adapter_id.into(),
            completed_at,
            collected: Vec::new(),
        }
    }

    pub fn collected(&self) -> &[TestCollectorDeliveryRecord] {
        &self.collected
    }
}

impl ExternalDeliveryAdapter for TestCollectorDeliveryAdapter {
    fn adapter_id(&self) -> &str {
        &self.adapter_id
    }

    fn deliver(
        &mut self,
        candidate: &DeliveryCandidate,
        attempt: &DeliveryAttemptRecord,
    ) -> ExternalDeliveryResult {
        self.collected.push(TestCollectorDeliveryRecord {
            candidate: candidate.clone(),
            attempt: attempt.clone(),
        });
        ExternalDeliveryResult::delivered(self.completed_at)
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DeliveryAdapterRun {
    pub result: ExternalDeliveryResult,
    pub completed_attempt: DeliveryAttemptRecord,
    pub diagnostic: Option<HostDeliveryDiagnostic>,
}

pub fn deliver_candidate_with_attempt_store<S, A>(
    store: &mut S,
    adapter: &mut A,
    candidate: DeliveryCandidate,
    scheduled_at: i64,
    started_at: i64,
) -> DeliveryAdapterRun
where
    S: DeliveryAttemptStore,
    A: ExternalDeliveryAdapter,
{
    let reserved = store.reserve(
        candidate.dedupe_key(),
        adapter.adapter_id().to_owned(),
        scheduled_at,
    );
    let identity = reserved.external_identity();
    let started = store
        .start(&identity, reserved.attempt_number, started_at)
        .expect("reserved delivery attempt can be started");
    let result = adapter.deliver(&candidate, &started);
    let completed_attempt = store
        .complete(&identity, started.attempt_number, &result)
        .expect("started delivery attempt can be completed");
    let diagnostic = host_delivery_diagnostic_from_result(&completed_attempt, &result);

    DeliveryAdapterRun {
        result,
        completed_attempt,
        diagnostic,
    }
}

pub fn strategy_order_fill_delivery_candidate(
    running_alert_id: impl Into<String>,
    config: &RunningAlertConfig,
    alert: &StrategyOrderFillAlertOutput,
) -> Result<DeliveryCandidate, RunningAlertEvaluationError> {
    let rendered_message = render_strategy_order_fill_running_alert(config, alert)?;
    Ok(DeliveryCandidate::new(
        running_alert_id,
        config.script_snapshot_id.clone(),
        DeliveryEventKind::StrategyOrderFill,
        alert.bar_index,
        alert.time,
        alert.id.clone(),
        rendered_message,
    ))
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DeliveryOutcome {
    Delivered,
    Duplicate,
}

pub trait DeliverySink {
    fn deliver(&mut self, candidate: DeliveryCandidate) -> DeliveryOutcome;
}

#[derive(Debug, Clone, Default)]
pub struct InMemoryDeliverySink {
    delivered_keys: BTreeSet<DeliveryDedupeKey>,
    delivered: Vec<DeliveryCandidate>,
}

impl InMemoryDeliverySink {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn delivered(&self) -> &[DeliveryCandidate] {
        &self.delivered
    }

    pub fn delivered_keys(&self) -> &BTreeSet<DeliveryDedupeKey> {
        &self.delivered_keys
    }

    pub fn has_delivered(&self, key: &DeliveryDedupeKey) -> bool {
        self.delivered_keys.contains(key)
    }
}

impl DeliverySink for InMemoryDeliverySink {
    fn deliver(&mut self, candidate: DeliveryCandidate) -> DeliveryOutcome {
        let key = candidate.dedupe_key();
        if !self.delivered_keys.insert(key) {
            return DeliveryOutcome::Duplicate;
        }
        self.delivered.push(candidate);
        DeliveryOutcome::Delivered
    }
}

#[cfg(test)]
mod tests {
    use super::super::running_alerts::{RunningAlertConfig, RunningAlertEventSelection};
    use super::*;

    fn candidate(message: &str) -> DeliveryCandidate {
        DeliveryCandidate::new(
            "alert-1",
            "snapshot-1",
            DeliveryEventKind::StrategyOrderFill,
            2,
            300,
            "XL",
            message,
        )
    }

    fn alert(message: &str) -> StrategyOrderFillAlertOutput {
        StrategyOrderFillAlertOutput {
            id: "XL".to_owned(),
            bar_index: 2,
            time: 300,
            direction: "strategy.exit".to_owned(),
            qty: 1.0,
            price: 99.0,
            entry_id: Some("L".to_owned()),
            exit_id: Some("XL".to_owned()),
            message: message.to_owned(),
        }
    }

    #[test]
    fn delivery_candidate_builds_stable_dedupe_key_without_message() {
        let key = candidate("first").dedupe_key();

        assert_eq!(key.running_alert_id, "alert-1");
        assert_eq!(key.script_snapshot_id, "snapshot-1");
        assert_eq!(key.event_kind, DeliveryEventKind::StrategyOrderFill);
        assert_eq!(key.bar_index, 2);
        assert_eq!(key.time, 300);
        assert_eq!(key.event_id, "XL");
    }

    #[test]
    fn delivery_candidate_serializes_host_owned_shape() {
        let value = serde_json::to_value(candidate("Rendered")).expect("candidate serializes");

        assert_eq!(
            value,
            serde_json::json!({
                "runningAlertId": "alert-1",
                "scriptSnapshotId": "snapshot-1",
                "eventKind": "strategyOrderFill",
                "barIndex": 2,
                "time": 300,
                "eventId": "XL",
                "renderedMessage": "Rendered",
            })
        );
    }

    #[test]
    fn in_memory_sink_collects_candidates_once_per_dedupe_key() {
        let mut sink = InMemoryDeliverySink::new();
        let first = candidate("first");
        let duplicate = candidate("second");
        let key = first.dedupe_key();

        assert_eq!(sink.deliver(first), DeliveryOutcome::Delivered);
        assert_eq!(sink.deliver(duplicate), DeliveryOutcome::Duplicate);

        assert!(sink.has_delivered(&key));
        assert_eq!(sink.delivered_keys().len(), 1);
        assert_eq!(sink.delivered().len(), 1);
        assert_eq!(sink.delivered()[0].rendered_message, "first");
    }

    #[test]
    fn in_memory_sink_allows_same_event_for_different_running_alerts() {
        let mut sink = InMemoryDeliverySink::new();
        let mut second = candidate("second alert");
        second.running_alert_id = "alert-2".to_owned();

        assert_eq!(
            sink.deliver(candidate("first alert")),
            DeliveryOutcome::Delivered
        );
        assert_eq!(sink.deliver(second), DeliveryOutcome::Delivered);

        assert_eq!(sink.delivered_keys().len(), 2);
        assert_eq!(sink.delivered().len(), 2);
    }

    #[test]
    fn external_delivery_identity_combines_adapter_and_dedupe_key() {
        let key = candidate("message").dedupe_key();
        let identity = ExternalDeliveryIdentity::new("webhook-main", key.clone());

        assert_eq!(identity.adapter_id, "webhook-main");
        assert_eq!(identity.dedupe_key, key);
    }

    #[test]
    fn delivery_attempt_record_serializes_host_owned_shape() {
        let record =
            DeliveryAttemptRecord::new(candidate("message").dedupe_key(), "webhook-main", 1, 1_000)
                .start(1_010)
                .complete(
                    &ExternalDeliveryResult::transient_failure(
                        1_020,
                        "timeout",
                        "adapter timed out",
                    )
                    .with_provider_status_code("504"),
                );

        let value = serde_json::to_value(record).expect("attempt record serializes");

        assert_eq!(
            value,
            serde_json::json!({
                "dedupeKey": {
                    "runningAlertId": "alert-1",
                    "scriptSnapshotId": "snapshot-1",
                    "eventKind": "strategyOrderFill",
                    "barIndex": 2,
                    "time": 300,
                    "eventId": "XL",
                },
                "adapterId": "webhook-main",
                "attemptNumber": 1,
                "status": "transientFailure",
                "scheduledAt": 1000,
                "startedAt": 1010,
                "completedAt": 1020,
                "nextRetryAt": null,
                "failureCode": "timeout",
            })
        );
    }

    #[test]
    fn delivery_attempt_record_keeps_external_identity_stable_across_attempts() {
        let key = candidate("message").dedupe_key();
        let first = DeliveryAttemptRecord::new(key.clone(), "webhook-main", 1, 1_000);
        let second = DeliveryAttemptRecord::new(key, "webhook-main", 2, 2_000);

        assert_ne!(first.attempt_number, second.attempt_number);
        assert_eq!(first.external_identity(), second.external_identity());
    }

    #[test]
    fn external_delivery_result_classifies_retryable_status() {
        let delivered = ExternalDeliveryResult::delivered(1_000);
        let transient = ExternalDeliveryResult::transient_failure(1_001, "timeout", "timeout");
        let permanent =
            ExternalDeliveryResult::permanent_failure(1_002, "badRequest", "bad request");

        assert!(!delivered.status.is_retryable_failure());
        assert!(transient.status.is_retryable_failure());
        assert!(!permanent.status.is_retryable_failure());
        assert!(DeliveryAttemptStatus::from(delivered.status).is_terminal());
        assert!(DeliveryAttemptStatus::from(transient.status).is_retryable_failure());
        assert!(DeliveryAttemptStatus::from(permanent.status).is_terminal());
    }

    #[test]
    fn in_memory_attempt_store_reserves_attempts_by_adapter_and_dedupe_key() {
        let mut store = InMemoryDeliveryAttemptStore::new();
        let key = candidate("message").dedupe_key();

        let first = store.reserve(key.clone(), "webhook-main".to_owned(), 1_000);
        let second = store.reserve(key, "webhook-main".to_owned(), 2_000);
        let identity = first.external_identity();

        assert_eq!(first.attempt_number, 1);
        assert_eq!(second.attempt_number, 2);
        assert_eq!(first.status, DeliveryAttemptStatus::Pending);
        assert_eq!(second.status, DeliveryAttemptStatus::Pending);
        assert_eq!(store.identity_count(), 1);
        assert_eq!(store.attempts(&identity), &[first, second]);
    }

    #[test]
    fn in_memory_attempt_store_keeps_adapters_as_distinct_identities() {
        let mut store = InMemoryDeliveryAttemptStore::new();
        let key = candidate("message").dedupe_key();

        let webhook = store.reserve(key.clone(), "webhook-main".to_owned(), 1_000);
        let log = store.reserve(key, "local-log".to_owned(), 1_000);

        assert_eq!(webhook.attempt_number, 1);
        assert_eq!(log.attempt_number, 1);
        assert_ne!(webhook.external_identity(), log.external_identity());
        assert_eq!(store.identity_count(), 2);
    }

    #[test]
    fn in_memory_attempt_store_starts_and_completes_existing_attempt() {
        let mut store = InMemoryDeliveryAttemptStore::new();
        let record = store.reserve(
            candidate("message").dedupe_key(),
            "webhook-main".to_owned(),
            1_000,
        );
        let identity = record.external_identity();

        let started = store
            .start(&identity, record.attempt_number, 1_010)
            .expect("attempt starts");
        let completed = store
            .complete(
                &identity,
                record.attempt_number,
                &ExternalDeliveryResult::delivered(1_020).with_provider_status_code("200"),
            )
            .expect("attempt completes");

        assert_eq!(started.status, DeliveryAttemptStatus::InFlight);
        assert_eq!(started.started_at, Some(1_010));
        assert_eq!(completed.status, DeliveryAttemptStatus::Delivered);
        assert_eq!(completed.completed_at, Some(1_020));
        assert_eq!(store.latest_attempt(&identity), Some(&completed));
    }

    #[test]
    fn in_memory_attempt_store_records_planned_retry_timestamp() {
        let mut store = InMemoryDeliveryAttemptStore::new();
        let record = store.reserve(
            candidate("message").dedupe_key(),
            "webhook-main".to_owned(),
            1_000,
        );
        let identity = record.external_identity();
        let result =
            ExternalDeliveryResult::transient_failure(1_020, "webhookTransportTimeout", "timeout");
        let completed = store
            .complete(&identity, record.attempt_number, &result)
            .expect("attempt completes");

        let scheduled = store
            .schedule_retry(&identity, completed.attempt_number, 2_020)
            .expect("retry timestamp is recorded");

        assert_eq!(scheduled.status, DeliveryAttemptStatus::TransientFailure);
        assert_eq!(scheduled.completed_at, Some(1_020));
        assert_eq!(scheduled.next_retry_at, Some(2_020));
        assert_eq!(store.latest_attempt(&identity), Some(&scheduled));
    }

    #[test]
    fn in_memory_attempt_store_ignores_unknown_attempt_updates() {
        let mut store = InMemoryDeliveryAttemptStore::new();
        let identity =
            ExternalDeliveryIdentity::new("webhook-main", candidate("message").dedupe_key());

        assert_eq!(store.start(&identity, 1, 1_010), None);
        assert_eq!(
            store.complete(&identity, 1, &ExternalDeliveryResult::delivered(1_020)),
            None
        );
        assert_eq!(store.schedule_retry(&identity, 1, 2_020), None);
    }

    #[test]
    fn test_collector_adapter_collects_candidate_with_started_attempt() {
        let mut adapter = TestCollectorDeliveryAdapter::new("test-collector", 1_020);
        let attempt = DeliveryAttemptRecord::new(
            candidate("message").dedupe_key(),
            "test-collector",
            1,
            1_000,
        )
        .start(1_010);
        let result = adapter.deliver(&candidate("message"), &attempt);

        assert_eq!(result, ExternalDeliveryResult::delivered(1_020));
        assert_eq!(adapter.adapter_id(), "test-collector");
        assert_eq!(adapter.collected().len(), 1);
        assert_eq!(adapter.collected()[0].candidate.rendered_message, "message");
        assert_eq!(adapter.collected()[0].attempt, attempt);
    }

    struct FailingDeliveryAdapter {
        adapter_id: String,
        result: ExternalDeliveryResult,
    }

    impl FailingDeliveryAdapter {
        fn new(adapter_id: impl Into<String>, result: ExternalDeliveryResult) -> Self {
            Self {
                adapter_id: adapter_id.into(),
                result,
            }
        }
    }

    impl ExternalDeliveryAdapter for FailingDeliveryAdapter {
        fn adapter_id(&self) -> &str {
            &self.adapter_id
        }

        fn deliver(
            &mut self,
            _candidate: &DeliveryCandidate,
            _attempt: &DeliveryAttemptRecord,
        ) -> ExternalDeliveryResult {
            self.result.clone()
        }
    }

    #[test]
    fn deliver_candidate_with_attempt_store_records_full_local_flow() {
        let mut store = InMemoryDeliveryAttemptStore::new();
        let mut adapter = TestCollectorDeliveryAdapter::new("test-collector", 1_020);

        let run = deliver_candidate_with_attempt_store(
            &mut store,
            &mut adapter,
            candidate("message"),
            1_000,
            1_010,
        );
        let identity = run.completed_attempt.external_identity();

        assert_eq!(run.result, ExternalDeliveryResult::delivered(1_020));
        assert_eq!(
            run.completed_attempt.status,
            DeliveryAttemptStatus::Delivered
        );
        assert_eq!(run.completed_attempt.scheduled_at, 1_000);
        assert_eq!(run.completed_attempt.started_at, Some(1_010));
        assert_eq!(run.completed_attempt.completed_at, Some(1_020));
        assert_eq!(
            store.latest_attempt(&identity),
            Some(&run.completed_attempt)
        );
        assert_eq!(adapter.collected().len(), 1);
        assert_eq!(
            adapter.collected()[0].attempt.status,
            DeliveryAttemptStatus::InFlight
        );
        assert_eq!(run.diagnostic, None);
    }

    #[test]
    fn deliver_candidate_with_attempt_store_increments_retry_attempts() {
        let mut store = InMemoryDeliveryAttemptStore::new();
        let mut adapter = TestCollectorDeliveryAdapter::new("test-collector", 1_020);
        let first = deliver_candidate_with_attempt_store(
            &mut store,
            &mut adapter,
            candidate("message"),
            1_000,
            1_010,
        );
        let second = deliver_candidate_with_attempt_store(
            &mut store,
            &mut adapter,
            candidate("message"),
            2_000,
            2_010,
        );

        assert_eq!(first.completed_attempt.attempt_number, 1);
        assert_eq!(second.completed_attempt.attempt_number, 2);
        assert_eq!(adapter.collected().len(), 2);
    }

    #[test]
    fn deliver_candidate_with_attempt_store_emits_redacted_host_diagnostic_for_failure() {
        let mut store = InMemoryDeliveryAttemptStore::new();
        let result = ExternalDeliveryResult::transient_failure(
            1_020,
            "webhookTransportTimeout",
            "Authorization: Bearer secret",
        )
        .with_provider_status_code("503");
        let mut adapter = FailingDeliveryAdapter::new("webhook-main", result);

        let run = deliver_candidate_with_attempt_store(
            &mut store,
            &mut adapter,
            candidate("message"),
            1_000,
            1_010,
        );
        let diagnostic = run.diagnostic.expect("failure emits host diagnostic");

        assert_eq!(
            run.completed_attempt.status,
            DeliveryAttemptStatus::TransientFailure
        );
        assert_eq!(diagnostic.severity, HostDeliveryDiagnosticSeverity::Warning);
        assert_eq!(diagnostic.code, "webhookTransportTimeout");
        assert_eq!(diagnostic.running_alert_id, "alert-1");
        assert_eq!(diagnostic.script_snapshot_id, "snapshot-1");
        assert_eq!(diagnostic.adapter_id, "webhook-main");
        assert_eq!(
            diagnostic.message,
            "external delivery transientFailure for adapter webhook-main attempt 1 with provider status class 5xx"
        );
        assert!(!diagnostic.message.contains("Bearer"));
        assert!(!diagnostic.message.contains("secret"));
    }

    #[test]
    fn strategy_order_fill_builder_renders_delivery_candidate() {
        let config = RunningAlertConfig::new_strategy_order_fills(
            "snapshot-1",
            "NYSE:IBM",
            "1",
            "Running: {{strategy.order.alert_message}}",
        );

        let candidate =
            strategy_order_fill_delivery_candidate("alert-1", &config, &alert("loss alert"))
                .expect("delivery candidate");

        assert_eq!(candidate.running_alert_id, "alert-1");
        assert_eq!(candidate.script_snapshot_id, "snapshot-1");
        assert_eq!(candidate.event_kind, DeliveryEventKind::StrategyOrderFill);
        assert_eq!(candidate.bar_index, 2);
        assert_eq!(candidate.time, 300);
        assert_eq!(candidate.event_id, "XL");
        assert_eq!(candidate.rendered_message, "Running: loss alert");
    }

    #[test]
    fn strategy_order_fill_builder_uses_candidate_dedupe_key() {
        let config = RunningAlertConfig::new_strategy_order_fills(
            "snapshot-1",
            "NYSE:IBM",
            "1",
            "{{strategy.order.alert_message}}",
        );
        let candidate =
            strategy_order_fill_delivery_candidate("alert-1", &config, &alert("loss alert"))
                .expect("delivery candidate");

        assert_eq!(
            candidate.dedupe_key(),
            DeliveryDedupeKey {
                running_alert_id: "alert-1".to_owned(),
                script_snapshot_id: "snapshot-1".to_owned(),
                event_kind: DeliveryEventKind::StrategyOrderFill,
                bar_index: 2,
                time: 300,
                event_id: "XL".to_owned(),
            }
        );
    }

    #[test]
    fn strategy_order_fill_builder_keeps_both_selection_design_only() {
        let mut config = RunningAlertConfig::new_strategy_order_fills(
            "snapshot-1",
            "NYSE:IBM",
            "1",
            "{{strategy.order.alert_message}}",
        );
        config.event_selection = RunningAlertEventSelection::Both;

        let error =
            strategy_order_fill_delivery_candidate("alert-1", &config, &alert("loss alert"))
                .expect_err("both should not build strategy-only candidate");

        assert_eq!(
            error,
            RunningAlertEvaluationError::UnsupportedEventSelection {
                selection: RunningAlertEventSelection::Both,
            }
        );
    }
}
