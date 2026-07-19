use std::collections::{BTreeMap, BTreeSet};

use serde::{Deserialize, Serialize};

use super::{
    DeliveryAdapterRun, DeliveryAttemptRecord, DeliveryAttemptStore, DeliveryCandidate,
    ExternalDeliveryResult,
};

mod request;
mod transport;

pub use request::{
    WebhookRequest, WebhookRequestError, WebhookResolvedHeaders, WebhookResolvedHeadersError,
    WebhookSecretResolver, WebhookSecretResolverError, build_webhook_request,
    resolve_webhook_headers,
};
pub use transport::{WebhookDeliveryAdapter, WebhookTransport, WebhookTransportOutcome};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum WebhookBodyMode {
    RenderedMessage,
    JsonEnvelope,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct WebhookAdapterConfig {
    pub adapter_id: String,
    pub url: String,
    pub headers: BTreeMap<String, String>,
    pub secret_header_refs: BTreeMap<String, String>,
    pub body_mode: WebhookBodyMode,
    pub timeout_ms: u32,
}

impl WebhookAdapterConfig {
    pub fn new(
        adapter_id: impl Into<String>,
        url: impl Into<String>,
        body_mode: WebhookBodyMode,
        timeout_ms: u32,
    ) -> Self {
        Self {
            adapter_id: adapter_id.into(),
            url: url.into(),
            headers: BTreeMap::new(),
            secret_header_refs: BTreeMap::new(),
            body_mode,
            timeout_ms,
        }
    }

    pub fn with_header(mut self, name: impl Into<String>, value: impl Into<String>) -> Self {
        self.headers.insert(name.into(), value.into());
        self
    }

    pub fn with_secret_header_ref(
        mut self,
        name: impl Into<String>,
        secret_ref: impl Into<String>,
    ) -> Self {
        self.secret_header_refs
            .insert(name.into(), secret_ref.into());
        self
    }

    pub fn validate(&self) -> Result<(), WebhookAdapterConfigError> {
        if self.adapter_id.trim().is_empty() {
            return Err(WebhookAdapterConfigError::EmptyAdapterId);
        }
        validate_webhook_url(&self.url)?;
        if self.timeout_ms == 0 || self.timeout_ms > MAX_WEBHOOK_TIMEOUT_MS {
            return Err(WebhookAdapterConfigError::InvalidTimeout {
                timeout_ms: self.timeout_ms,
            });
        }
        validate_webhook_headers(self)
    }
}

const MAX_WEBHOOK_TIMEOUT_MS: u32 = 30_000;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum WebhookAdapterConfigError {
    EmptyAdapterId,
    EmptyUrl,
    UnsupportedUrlScheme,
    MissingUrlHost,
    UrlContainsCredentials,
    InvalidUrlPort { port: String },
    UnsupportedUrlPort { port: u16 },
    InvalidTimeout { timeout_ms: u32 },
    EmptyHeaderName,
    DuplicateHeaderName { header_name: String },
    StaticHeaderMayContainSecret { header_name: String },
    EmptySecretReference { header_name: String },
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct WebhookPayload {
    pub content_type: String,
    pub body: String,
}

impl WebhookPayload {
    pub fn new(content_type: impl Into<String>, body: impl Into<String>) -> Self {
        Self {
            content_type: content_type.into(),
            body: body.into(),
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum WebhookPayloadError {
    InvalidConfig(WebhookAdapterConfigError),
    JsonSerializationFailed(String),
}

impl From<WebhookAdapterConfigError> for WebhookPayloadError {
    fn from(error: WebhookAdapterConfigError) -> Self {
        Self::InvalidConfig(error)
    }
}

pub fn render_webhook_payload(
    config: &WebhookAdapterConfig,
    candidate: &DeliveryCandidate,
) -> Result<WebhookPayload, WebhookPayloadError> {
    config.validate()?;
    match config.body_mode {
        WebhookBodyMode::RenderedMessage => Ok(WebhookPayload::new(
            "text/plain; charset=utf-8",
            candidate.rendered_message.clone(),
        )),
        WebhookBodyMode::JsonEnvelope => render_webhook_json_envelope(config, candidate),
    }
}

fn render_webhook_json_envelope(
    config: &WebhookAdapterConfig,
    candidate: &DeliveryCandidate,
) -> Result<WebhookPayload, WebhookPayloadError> {
    let value = serde_json::json!({
        "schemaVersion": 1,
        "adapterId": config.adapter_id,
        "bodyMode": config.body_mode,
        "candidate": candidate,
    });
    let body = serde_json::to_string(&value)
        .map_err(|error| WebhookPayloadError::JsonSerializationFailed(error.to_string()))?;
    Ok(WebhookPayload::new("application/json", body))
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WebhookDeliveryFailure {
    TransportTimeout,
    ConnectionReset,
    DnsFailure,
    RateLimited,
    TemporaryServerFailure,
    InvalidConfiguration,
    RejectedUrl,
    MissingSecretReference,
    UnauthorizedSecretLookup,
    SecretResolverUnavailable,
    InvalidPayloadConstruction,
    ProviderRejected,
}

impl WebhookDeliveryFailure {
    fn is_retryable(self) -> bool {
        matches!(
            self,
            Self::TransportTimeout
                | Self::ConnectionReset
                | Self::DnsFailure
                | Self::RateLimited
                | Self::TemporaryServerFailure
                | Self::SecretResolverUnavailable
        )
    }

    fn failure_code(self) -> &'static str {
        match self {
            Self::TransportTimeout => "webhookTransportTimeout",
            Self::ConnectionReset => "webhookConnectionReset",
            Self::DnsFailure => "webhookDnsFailure",
            Self::RateLimited => "webhookRateLimited",
            Self::TemporaryServerFailure => "webhookTemporaryServerFailure",
            Self::InvalidConfiguration => "webhookInvalidConfiguration",
            Self::RejectedUrl => "webhookRejectedUrl",
            Self::MissingSecretReference => "webhookMissingSecretReference",
            Self::UnauthorizedSecretLookup => "webhookUnauthorizedSecretLookup",
            Self::SecretResolverUnavailable => "webhookSecretResolverUnavailable",
            Self::InvalidPayloadConstruction => "webhookInvalidPayloadConstruction",
            Self::ProviderRejected => "webhookProviderRejected",
        }
    }

    fn redacted_message(self) -> &'static str {
        match self {
            Self::TransportTimeout => "webhook delivery timed out before provider acceptance",
            Self::ConnectionReset => "webhook delivery connection reset before provider acceptance",
            Self::DnsFailure => "webhook delivery host resolution failed",
            Self::RateLimited => "webhook delivery was rate limited by the provider",
            Self::TemporaryServerFailure => {
                "webhook delivery failed with a temporary provider error"
            }
            Self::InvalidConfiguration => "webhook delivery configuration is invalid",
            Self::RejectedUrl => "webhook delivery URL was rejected by host policy",
            Self::MissingSecretReference => {
                "webhook delivery secret reference could not be resolved"
            }
            Self::UnauthorizedSecretLookup => "webhook delivery secret lookup was not authorized",
            Self::SecretResolverUnavailable => "webhook delivery secret resolver was unavailable",
            Self::InvalidPayloadConstruction => "webhook delivery payload could not be built",
            Self::ProviderRejected => "webhook delivery was rejected by the provider",
        }
    }
}

pub fn classify_webhook_delivery_failure(
    failure: WebhookDeliveryFailure,
    completed_at: i64,
) -> ExternalDeliveryResult {
    if failure.is_retryable() {
        ExternalDeliveryResult::transient_failure(
            completed_at,
            failure.failure_code(),
            failure.redacted_message(),
        )
    } else {
        ExternalDeliveryResult::permanent_failure(
            completed_at,
            failure.failure_code(),
            failure.redacted_message(),
        )
    }
}

pub fn classify_webhook_http_status(status_code: u16, completed_at: i64) -> ExternalDeliveryResult {
    let redacted_status_class = redact_http_status_code(status_code);
    let mut result = if (200..=299).contains(&status_code) {
        ExternalDeliveryResult::delivered(completed_at)
    } else if is_retryable_http_status(status_code) {
        classify_webhook_delivery_failure(
            WebhookDeliveryFailure::TemporaryServerFailure,
            completed_at,
        )
    } else {
        classify_webhook_delivery_failure(WebhookDeliveryFailure::ProviderRejected, completed_at)
    };
    result.provider_status_code = Some(redacted_status_class.to_owned());
    result
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct WebhookRetryPolicy {
    pub max_attempts: u32,
    pub initial_delay_ms: i64,
    pub max_delay_ms: i64,
}

impl WebhookRetryPolicy {
    pub fn new(max_attempts: u32, initial_delay_ms: i64, max_delay_ms: i64) -> Self {
        Self {
            max_attempts,
            initial_delay_ms,
            max_delay_ms,
        }
    }

    pub fn validate(&self) -> Result<(), WebhookRetryPolicyError> {
        if self.max_attempts == 0 {
            return Err(WebhookRetryPolicyError::EmptyAttemptBudget);
        }
        if self.initial_delay_ms <= 0 {
            return Err(WebhookRetryPolicyError::InvalidInitialDelay {
                initial_delay_ms: self.initial_delay_ms,
            });
        }
        if self.max_delay_ms < self.initial_delay_ms {
            return Err(WebhookRetryPolicyError::InvalidMaxDelay {
                initial_delay_ms: self.initial_delay_ms,
                max_delay_ms: self.max_delay_ms,
            });
        }
        Ok(())
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum WebhookRetryPolicyError {
    EmptyAttemptBudget,
    InvalidInitialDelay {
        initial_delay_ms: i64,
    },
    InvalidMaxDelay {
        initial_delay_ms: i64,
        max_delay_ms: i64,
    },
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum WebhookRetryRecordError {
    Policy(WebhookRetryPolicyError),
    MissingAttempt,
}

impl From<WebhookRetryPolicyError> for WebhookRetryRecordError {
    fn from(error: WebhookRetryPolicyError) -> Self {
        Self::Policy(error)
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum WebhookRetryDecision {
    NotRetryable,
    AttemptsExhausted,
    RetryAt {
        next_attempt_number: u32,
        delay_ms: i64,
        next_retry_at: i64,
    },
}

pub fn plan_webhook_retry(
    policy: &WebhookRetryPolicy,
    attempt: &DeliveryAttemptRecord,
    result: &ExternalDeliveryResult,
) -> Result<WebhookRetryDecision, WebhookRetryPolicyError> {
    policy.validate()?;
    if !result.status.is_retryable_failure() {
        return Ok(WebhookRetryDecision::NotRetryable);
    }
    if attempt.attempt_number >= policy.max_attempts {
        return Ok(WebhookRetryDecision::AttemptsExhausted);
    }
    let delay_ms = webhook_retry_delay_ms(policy, attempt.attempt_number);
    Ok(WebhookRetryDecision::RetryAt {
        next_attempt_number: attempt.attempt_number.saturating_add(1),
        delay_ms,
        next_retry_at: result.completed_at.saturating_add(delay_ms),
    })
}

pub fn plan_and_record_webhook_retry<S>(
    policy: &WebhookRetryPolicy,
    store: &mut S,
    run: &DeliveryAdapterRun,
) -> Result<WebhookRetryDecision, WebhookRetryRecordError>
where
    S: DeliveryAttemptStore,
{
    let decision = plan_webhook_retry(policy, &run.completed_attempt, &run.result)?;
    if let WebhookRetryDecision::RetryAt { next_retry_at, .. } = decision {
        let identity = run.completed_attempt.external_identity();
        store
            .schedule_retry(
                &identity,
                run.completed_attempt.attempt_number,
                next_retry_at,
            )
            .ok_or(WebhookRetryRecordError::MissingAttempt)?;
    }
    Ok(decision)
}

fn webhook_retry_delay_ms(policy: &WebhookRetryPolicy, attempt_number: u32) -> i64 {
    let completed_retry_count = attempt_number.saturating_sub(1);
    let shift = completed_retry_count.min(62);
    let multiplier = 1_i64.checked_shl(shift).unwrap_or(i64::MAX);
    policy
        .initial_delay_ms
        .saturating_mul(multiplier)
        .min(policy.max_delay_ms)
}

fn is_retryable_http_status(status_code: u16) -> bool {
    matches!(status_code, 408 | 409 | 425 | 429) || (500..=599).contains(&status_code)
}

fn redact_http_status_code(status_code: u16) -> &'static str {
    match status_code {
        100..=199 => "1xx",
        200..=299 => "2xx",
        300..=399 => "3xx",
        400..=499 => "4xx",
        500..=599 => "5xx",
        _ => "unknown",
    }
}

fn validate_webhook_url(url: &str) -> Result<(), WebhookAdapterConfigError> {
    let trimmed = url.trim();
    if trimmed.is_empty() {
        return Err(WebhookAdapterConfigError::EmptyUrl);
    }
    let Some((scheme, rest)) = trimmed.split_once("://") else {
        return Err(WebhookAdapterConfigError::UnsupportedUrlScheme);
    };
    let scheme = scheme.to_ascii_lowercase();
    if scheme != "http" && scheme != "https" {
        return Err(WebhookAdapterConfigError::UnsupportedUrlScheme);
    }
    let authority = rest
        .split(['/', '?', '#'])
        .next()
        .expect("split always yields first segment");
    if authority.is_empty() {
        return Err(WebhookAdapterConfigError::MissingUrlHost);
    }
    if authority.contains('@') {
        return Err(WebhookAdapterConfigError::UrlContainsCredentials);
    }
    let host_port = authority.rsplit_once(':');
    if let Some((host, port_text)) = host_port {
        if host.is_empty() {
            return Err(WebhookAdapterConfigError::MissingUrlHost);
        }
        let Ok(port) = port_text.parse::<u16>() else {
            return Err(WebhookAdapterConfigError::InvalidUrlPort {
                port: port_text.to_owned(),
            });
        };
        if port != 80 && port != 443 {
            return Err(WebhookAdapterConfigError::UnsupportedUrlPort { port });
        }
    }
    Ok(())
}

fn validate_webhook_headers(
    config: &WebhookAdapterConfig,
) -> Result<(), WebhookAdapterConfigError> {
    let mut normalized_names = BTreeSet::new();
    for (name, value) in &config.headers {
        let normalized = normalize_header_name(name)?;
        if !normalized_names.insert(normalized.clone()) {
            return Err(WebhookAdapterConfigError::DuplicateHeaderName {
                header_name: name.clone(),
            });
        }
        if header_name_looks_secret(&normalized) || header_value_looks_secret(value) {
            return Err(WebhookAdapterConfigError::StaticHeaderMayContainSecret {
                header_name: name.clone(),
            });
        }
    }
    for (name, secret_ref) in &config.secret_header_refs {
        let normalized = normalize_header_name(name)?;
        if !normalized_names.insert(normalized) {
            return Err(WebhookAdapterConfigError::DuplicateHeaderName {
                header_name: name.clone(),
            });
        }
        if secret_ref.trim().is_empty() {
            return Err(WebhookAdapterConfigError::EmptySecretReference {
                header_name: name.clone(),
            });
        }
    }
    Ok(())
}

fn normalize_header_name(name: &str) -> Result<String, WebhookAdapterConfigError> {
    let trimmed = name.trim();
    if trimmed.is_empty() {
        return Err(WebhookAdapterConfigError::EmptyHeaderName);
    }
    Ok(trimmed.to_ascii_lowercase())
}

fn header_name_looks_secret(normalized_name: &str) -> bool {
    normalized_name == "authorization"
        || normalized_name.contains("api-key")
        || normalized_name.contains("token")
        || normalized_name.contains("secret")
        || normalized_name.contains("password")
}

fn header_value_looks_secret(value: &str) -> bool {
    let normalized = value.trim().to_ascii_lowercase();
    normalized.starts_with("bearer ") || normalized.contains("password=")
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::output::delivery::{
        DeliveryAdapterRun, DeliveryEventKind, ExternalDeliveryStatus, InMemoryDeliveryAttemptStore,
    };

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

    fn attempt(attempt_number: u32) -> DeliveryAttemptRecord {
        DeliveryAttemptRecord::new(
            candidate("message").dedupe_key(),
            "webhook-main",
            attempt_number,
            1_000,
        )
    }

    #[test]
    fn webhook_adapter_config_accepts_host_owned_safe_shape() {
        let config = WebhookAdapterConfig::new(
            "webhook-main",
            "https://example.com/tradingview",
            WebhookBodyMode::JsonEnvelope,
            5_000,
        )
        .with_header("Content-Type", "application/json")
        .with_secret_header_ref("X-Webhook-Signature", "secret://alerts/webhook-signature");

        assert_eq!(config.validate(), Ok(()));
    }

    #[test]
    fn webhook_adapter_config_serializes_camel_case_shape() {
        let config = WebhookAdapterConfig::new(
            "webhook-main",
            "https://example.com/hook",
            WebhookBodyMode::RenderedMessage,
            5_000,
        )
        .with_header("Content-Type", "text/plain")
        .with_secret_header_ref("X-Token", "secret://token");

        let value = serde_json::to_value(config).expect("webhook config serializes");

        assert_eq!(
            value,
            serde_json::json!({
                "adapterId": "webhook-main",
                "url": "https://example.com/hook",
                "headers": {
                    "Content-Type": "text/plain",
                },
                "secretHeaderRefs": {
                    "X-Token": "secret://token",
                },
                "bodyMode": "renderedMessage",
                "timeoutMs": 5000,
            })
        );
    }

    #[test]
    fn webhook_adapter_config_rejects_unsafe_urls() {
        let cases = [
            ("", WebhookAdapterConfigError::EmptyUrl),
            ("/relative", WebhookAdapterConfigError::UnsupportedUrlScheme),
            (
                "file:///tmp/hook",
                WebhookAdapterConfigError::UnsupportedUrlScheme,
            ),
            ("https:///hook", WebhookAdapterConfigError::MissingUrlHost),
            (
                "https://user:pass@example.com/hook",
                WebhookAdapterConfigError::UrlContainsCredentials,
            ),
            (
                "https://example.com:abc/hook",
                WebhookAdapterConfigError::InvalidUrlPort {
                    port: "abc".to_owned(),
                },
            ),
            (
                "https://example.com:8080/hook",
                WebhookAdapterConfigError::UnsupportedUrlPort { port: 8080 },
            ),
        ];

        for (url, expected) in cases {
            let config =
                WebhookAdapterConfig::new("webhook-main", url, WebhookBodyMode::RenderedMessage, 1);
            assert_eq!(config.validate(), Err(expected));
        }
    }

    #[test]
    fn webhook_adapter_config_rejects_invalid_timeout() {
        let zero = WebhookAdapterConfig::new(
            "webhook-main",
            "https://example.com/hook",
            WebhookBodyMode::RenderedMessage,
            0,
        );
        let too_large = WebhookAdapterConfig::new(
            "webhook-main",
            "https://example.com/hook",
            WebhookBodyMode::RenderedMessage,
            30_001,
        );

        assert_eq!(
            zero.validate(),
            Err(WebhookAdapterConfigError::InvalidTimeout { timeout_ms: 0 })
        );
        assert_eq!(
            too_large.validate(),
            Err(WebhookAdapterConfigError::InvalidTimeout { timeout_ms: 30_001 })
        );
    }

    #[test]
    fn webhook_adapter_config_rejects_duplicate_header_names() {
        let config = WebhookAdapterConfig::new(
            "webhook-main",
            "https://example.com/hook",
            WebhookBodyMode::RenderedMessage,
            1_000,
        )
        .with_header("X-Trace", "public")
        .with_secret_header_ref("x-trace", "secret://trace");

        assert_eq!(
            config.validate(),
            Err(WebhookAdapterConfigError::DuplicateHeaderName {
                header_name: "x-trace".to_owned(),
            })
        );
    }

    #[test]
    fn webhook_adapter_config_rejects_static_secret_headers() {
        let config = WebhookAdapterConfig::new(
            "webhook-main",
            "https://example.com/hook",
            WebhookBodyMode::RenderedMessage,
            1_000,
        )
        .with_header("Authorization", "Bearer abc123");

        assert_eq!(
            config.validate(),
            Err(WebhookAdapterConfigError::StaticHeaderMayContainSecret {
                header_name: "Authorization".to_owned(),
            })
        );
    }

    #[test]
    fn webhook_adapter_config_rejects_empty_secret_refs() {
        let config = WebhookAdapterConfig::new(
            "webhook-main",
            "https://example.com/hook",
            WebhookBodyMode::RenderedMessage,
            1_000,
        )
        .with_secret_header_ref("X-Signature", " ");

        assert_eq!(
            config.validate(),
            Err(WebhookAdapterConfigError::EmptySecretReference {
                header_name: "X-Signature".to_owned(),
            })
        );
    }

    #[test]
    fn webhook_payload_renders_message_body_without_json_wrapping() {
        let config = WebhookAdapterConfig::new(
            "webhook-main",
            "https://example.com/hook",
            WebhookBodyMode::RenderedMessage,
            1_000,
        );

        let payload =
            render_webhook_payload(&config, &candidate("Price crossed")).expect("payload renders");

        assert_eq!(payload.content_type, "text/plain; charset=utf-8");
        assert_eq!(payload.body, "Price crossed");
    }

    #[test]
    fn webhook_payload_renders_host_versioned_json_envelope() {
        let config = WebhookAdapterConfig::new(
            "webhook-main",
            "https://example.com/hook",
            WebhookBodyMode::JsonEnvelope,
            1_000,
        )
        .with_header("Content-Type", "application/json")
        .with_secret_header_ref("X-Signature", "secret://signature");

        let payload =
            render_webhook_payload(&config, &candidate("Price crossed")).expect("payload renders");
        let value: serde_json::Value =
            serde_json::from_str(&payload.body).expect("payload body is json");

        assert_eq!(payload.content_type, "application/json");
        assert_eq!(
            value,
            serde_json::json!({
                "schemaVersion": 1,
                "adapterId": "webhook-main",
                "bodyMode": "jsonEnvelope",
                "candidate": {
                    "runningAlertId": "alert-1",
                    "scriptSnapshotId": "snapshot-1",
                    "eventKind": "strategyOrderFill",
                    "barIndex": 2,
                    "time": 300,
                    "eventId": "XL",
                    "renderedMessage": "Price crossed",
                },
            })
        );
    }

    #[test]
    fn webhook_payload_does_not_include_url_headers_or_secret_refs() {
        let config = WebhookAdapterConfig::new(
            "webhook-main",
            "https://example.com/hook",
            WebhookBodyMode::JsonEnvelope,
            1_000,
        )
        .with_header("Content-Type", "application/json")
        .with_secret_header_ref("X-Signature", "secret://signature");

        let payload =
            render_webhook_payload(&config, &candidate("Price crossed")).expect("payload renders");

        assert!(!payload.body.contains("example.com"));
        assert!(!payload.body.contains("headers"));
        assert!(!payload.body.contains("secret"));
        assert!(!payload.body.contains("X-Signature"));
    }

    #[test]
    fn webhook_payload_reuses_config_validation() {
        let config = WebhookAdapterConfig::new(
            "webhook-main",
            "file:///tmp/hook",
            WebhookBodyMode::RenderedMessage,
            1_000,
        );

        assert_eq!(
            render_webhook_payload(&config, &candidate("message")),
            Err(WebhookPayloadError::InvalidConfig(
                WebhookAdapterConfigError::UnsupportedUrlScheme
            ))
        );
    }

    #[test]
    fn webhook_failure_classifier_maps_transport_failures_to_retryable_results() {
        let result =
            classify_webhook_delivery_failure(WebhookDeliveryFailure::TransportTimeout, 1_000);

        assert_eq!(result.status, ExternalDeliveryStatus::TransientFailure);
        assert!(result.status.is_retryable_failure());
        assert_eq!(
            result.failure_code,
            Some("webhookTransportTimeout".to_owned())
        );
        assert_eq!(
            result.failure_message,
            Some("webhook delivery timed out before provider acceptance".to_owned())
        );
    }

    #[test]
    fn webhook_failure_classifier_maps_configuration_failures_to_permanent_results() {
        let result = classify_webhook_delivery_failure(
            WebhookDeliveryFailure::MissingSecretReference,
            1_000,
        );

        assert_eq!(result.status, ExternalDeliveryStatus::PermanentFailure);
        assert!(!result.status.is_retryable_failure());
        assert_eq!(
            result.failure_code,
            Some("webhookMissingSecretReference".to_owned())
        );
        assert_eq!(
            result.failure_message,
            Some("webhook delivery secret reference could not be resolved".to_owned())
        );
    }

    #[test]
    fn webhook_http_status_classifier_marks_accepted_status_as_delivered() {
        let result = classify_webhook_http_status(202, 1_000);

        assert_eq!(result.status, ExternalDeliveryStatus::Delivered);
        assert_eq!(result.provider_status_code, Some("2xx".to_owned()));
        assert_eq!(result.failure_code, None);
        assert_eq!(result.failure_message, None);
    }

    #[test]
    fn webhook_http_status_classifier_redacts_retryable_provider_status() {
        let result = classify_webhook_http_status(503, 1_000);

        assert_eq!(result.status, ExternalDeliveryStatus::TransientFailure);
        assert_eq!(result.provider_status_code, Some("5xx".to_owned()));
        assert_eq!(
            result.failure_code,
            Some("webhookTemporaryServerFailure".to_owned())
        );
        assert!(
            !result
                .failure_message
                .as_deref()
                .expect("failure message")
                .contains("503")
        );
    }

    #[test]
    fn webhook_http_status_classifier_redacts_permanent_provider_status() {
        let result = classify_webhook_http_status(401, 1_000);

        assert_eq!(result.status, ExternalDeliveryStatus::PermanentFailure);
        assert_eq!(result.provider_status_code, Some("4xx".to_owned()));
        assert_eq!(
            result.failure_code,
            Some("webhookProviderRejected".to_owned())
        );
        assert!(
            !result
                .failure_message
                .as_deref()
                .expect("failure message")
                .contains("401")
        );
    }

    #[test]
    fn webhook_retry_policy_schedules_transient_failures_with_first_backoff() {
        let policy = WebhookRetryPolicy::new(3, 1_000, 8_000);
        let result =
            classify_webhook_delivery_failure(WebhookDeliveryFailure::TransportTimeout, 10_000);

        assert_eq!(
            plan_webhook_retry(&policy, &attempt(1), &result),
            Ok(WebhookRetryDecision::RetryAt {
                next_attempt_number: 2,
                delay_ms: 1_000,
                next_retry_at: 11_000,
            })
        );
    }

    #[test]
    fn webhook_retry_plan_records_next_retry_timestamp_on_existing_attempt() {
        let mut store = InMemoryDeliveryAttemptStore::new();
        let reserved = store.reserve(
            candidate("message").dedupe_key(),
            "webhook-main".to_owned(),
            1_000,
        );
        let identity = reserved.external_identity();
        let result =
            classify_webhook_delivery_failure(WebhookDeliveryFailure::TransportTimeout, 10_000);
        let completed = store
            .complete(&identity, reserved.attempt_number, &result)
            .expect("attempt completes");
        let run = DeliveryAdapterRun {
            result,
            completed_attempt: completed,
            diagnostic: None,
        };

        assert_eq!(
            plan_and_record_webhook_retry(
                &WebhookRetryPolicy::new(3, 1_000, 8_000),
                &mut store,
                &run,
            ),
            Ok(WebhookRetryDecision::RetryAt {
                next_attempt_number: 2,
                delay_ms: 1_000,
                next_retry_at: 11_000,
            })
        );

        assert_eq!(
            store
                .latest_attempt(&identity)
                .and_then(|attempt| attempt.next_retry_at),
            Some(11_000)
        );
    }

    #[test]
    fn webhook_retry_plan_leaves_not_retryable_attempt_without_next_retry() {
        let mut store = InMemoryDeliveryAttemptStore::new();
        let reserved = store.reserve(
            candidate("message").dedupe_key(),
            "webhook-main".to_owned(),
            1_000,
        );
        let identity = reserved.external_identity();
        let result = ExternalDeliveryResult::delivered(10_000);
        let completed = store
            .complete(&identity, reserved.attempt_number, &result)
            .expect("attempt completes");
        let run = DeliveryAdapterRun {
            result,
            completed_attempt: completed,
            diagnostic: None,
        };

        assert_eq!(
            plan_and_record_webhook_retry(
                &WebhookRetryPolicy::new(3, 1_000, 8_000),
                &mut store,
                &run,
            ),
            Ok(WebhookRetryDecision::NotRetryable)
        );

        assert_eq!(
            store
                .latest_attempt(&identity)
                .and_then(|attempt| attempt.next_retry_at),
            None
        );
    }

    #[test]
    fn webhook_retry_plan_reports_missing_attempt_without_creating_retry_state() {
        let mut store = InMemoryDeliveryAttemptStore::new();
        let result =
            classify_webhook_delivery_failure(WebhookDeliveryFailure::TransportTimeout, 10_000);
        let run = DeliveryAdapterRun {
            result,
            completed_attempt: attempt(1).complete(&ExternalDeliveryResult::transient_failure(
                10_000,
                "webhookTransportTimeout",
                "timeout",
            )),
            diagnostic: None,
        };

        assert_eq!(
            plan_and_record_webhook_retry(
                &WebhookRetryPolicy::new(3, 1_000, 8_000),
                &mut store,
                &run,
            ),
            Err(WebhookRetryRecordError::MissingAttempt)
        );
        assert_eq!(store.identity_count(), 0);
    }

    #[test]
    fn webhook_retry_policy_caps_exponential_backoff() {
        let policy = WebhookRetryPolicy::new(5, 1_000, 2_500);
        let result =
            classify_webhook_delivery_failure(WebhookDeliveryFailure::ConnectionReset, 10_000);

        assert_eq!(
            plan_webhook_retry(&policy, &attempt(4), &result),
            Ok(WebhookRetryDecision::RetryAt {
                next_attempt_number: 5,
                delay_ms: 2_500,
                next_retry_at: 12_500,
            })
        );
    }

    #[test]
    fn webhook_retry_policy_does_not_retry_terminal_or_delivered_results() {
        let policy = WebhookRetryPolicy::new(3, 1_000, 8_000);
        let delivered = ExternalDeliveryResult::delivered(10_000);
        let permanent =
            classify_webhook_delivery_failure(WebhookDeliveryFailure::ProviderRejected, 10_000);

        assert_eq!(
            plan_webhook_retry(&policy, &attempt(1), &delivered),
            Ok(WebhookRetryDecision::NotRetryable)
        );
        assert_eq!(
            plan_webhook_retry(&policy, &attempt(1), &permanent),
            Ok(WebhookRetryDecision::NotRetryable)
        );
    }

    #[test]
    fn webhook_retry_policy_stops_at_attempt_budget() {
        let policy = WebhookRetryPolicy::new(3, 1_000, 8_000);
        let result = classify_webhook_delivery_failure(WebhookDeliveryFailure::RateLimited, 10_000);

        assert_eq!(
            plan_webhook_retry(&policy, &attempt(3), &result),
            Ok(WebhookRetryDecision::AttemptsExhausted)
        );
    }

    #[test]
    fn webhook_retry_policy_rejects_invalid_bounds() {
        let result = classify_webhook_delivery_failure(WebhookDeliveryFailure::DnsFailure, 10_000);

        assert_eq!(
            plan_webhook_retry(
                &WebhookRetryPolicy::new(0, 1_000, 8_000),
                &attempt(1),
                &result
            ),
            Err(WebhookRetryPolicyError::EmptyAttemptBudget)
        );
        assert_eq!(
            plan_webhook_retry(&WebhookRetryPolicy::new(3, 0, 8_000), &attempt(1), &result),
            Err(WebhookRetryPolicyError::InvalidInitialDelay {
                initial_delay_ms: 0,
            })
        );
        assert_eq!(
            plan_webhook_retry(
                &WebhookRetryPolicy::new(3, 9_000, 8_000),
                &attempt(1),
                &result
            ),
            Err(WebhookRetryPolicyError::InvalidMaxDelay {
                initial_delay_ms: 9_000,
                max_delay_ms: 8_000,
            })
        );
    }
}
