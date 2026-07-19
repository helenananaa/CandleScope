use crate::output::delivery::{
    DeliveryAttemptRecord, DeliveryCandidate, ExternalDeliveryAdapter, ExternalDeliveryResult,
};

use super::{
    WebhookAdapterConfig, WebhookAdapterConfigError, WebhookDeliveryFailure, WebhookPayloadError,
    WebhookRequest, WebhookRequestError, WebhookResolvedHeadersError, WebhookSecretResolver,
    build_webhook_request, classify_webhook_delivery_failure, classify_webhook_http_status,
};

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum WebhookTransportOutcome {
    HttpStatus {
        status_code: u16,
        completed_at: i64,
    },
    Failure {
        failure: WebhookDeliveryFailure,
        completed_at: i64,
    },
}

pub trait WebhookTransport {
    fn send_webhook_request(&mut self, request: &WebhookRequest) -> WebhookTransportOutcome;
}

pub struct WebhookDeliveryAdapter<R, T> {
    config: WebhookAdapterConfig,
    resolver: R,
    transport: T,
    request_failure_completed_at: i64,
}

impl<R, T> WebhookDeliveryAdapter<R, T> {
    pub fn new(
        config: WebhookAdapterConfig,
        resolver: R,
        transport: T,
        request_failure_completed_at: i64,
    ) -> Self {
        Self {
            config,
            resolver,
            transport,
            request_failure_completed_at,
        }
    }

    pub fn config(&self) -> &WebhookAdapterConfig {
        &self.config
    }

    pub fn transport(&self) -> &T {
        &self.transport
    }

    pub fn transport_mut(&mut self) -> &mut T {
        &mut self.transport
    }
}

impl<R, T> ExternalDeliveryAdapter for WebhookDeliveryAdapter<R, T>
where
    R: WebhookSecretResolver,
    T: WebhookTransport,
{
    fn adapter_id(&self) -> &str {
        &self.config.adapter_id
    }

    fn deliver(
        &mut self,
        candidate: &DeliveryCandidate,
        _attempt: &DeliveryAttemptRecord,
    ) -> ExternalDeliveryResult {
        let request = match build_webhook_request(&self.config, candidate, &self.resolver) {
            Ok(request) => request,
            Err(error) => {
                return classify_webhook_delivery_failure(
                    webhook_request_failure(&error),
                    self.request_failure_completed_at,
                );
            }
        };
        match self.transport.send_webhook_request(&request) {
            WebhookTransportOutcome::HttpStatus {
                status_code,
                completed_at,
            } => classify_webhook_http_status(status_code, completed_at),
            WebhookTransportOutcome::Failure {
                failure,
                completed_at,
            } => classify_webhook_delivery_failure(failure, completed_at),
        }
    }
}

fn webhook_request_failure(error: &WebhookRequestError) -> WebhookDeliveryFailure {
    match error {
        WebhookRequestError::Payload(WebhookPayloadError::InvalidConfig(error)) => {
            webhook_config_failure(error)
        }
        WebhookRequestError::Payload(WebhookPayloadError::JsonSerializationFailed(_)) => {
            WebhookDeliveryFailure::InvalidPayloadConstruction
        }
        WebhookRequestError::Headers(WebhookResolvedHeadersError::InvalidConfig(error)) => {
            webhook_config_failure(error)
        }
        WebhookRequestError::Headers(WebhookResolvedHeadersError::MissingSecretReference {
            ..
        }) => WebhookDeliveryFailure::MissingSecretReference,
        WebhookRequestError::Headers(WebhookResolvedHeadersError::UnauthorizedSecretLookup {
            ..
        }) => WebhookDeliveryFailure::UnauthorizedSecretLookup,
        WebhookRequestError::Headers(WebhookResolvedHeadersError::SecretResolverUnavailable {
            ..
        }) => WebhookDeliveryFailure::SecretResolverUnavailable,
    }
}

fn webhook_config_failure(error: &WebhookAdapterConfigError) -> WebhookDeliveryFailure {
    match error {
        WebhookAdapterConfigError::EmptyUrl
        | WebhookAdapterConfigError::UnsupportedUrlScheme
        | WebhookAdapterConfigError::MissingUrlHost
        | WebhookAdapterConfigError::UrlContainsCredentials
        | WebhookAdapterConfigError::InvalidUrlPort { .. }
        | WebhookAdapterConfigError::UnsupportedUrlPort { .. } => {
            WebhookDeliveryFailure::RejectedUrl
        }
        WebhookAdapterConfigError::EmptyAdapterId
        | WebhookAdapterConfigError::InvalidTimeout { .. }
        | WebhookAdapterConfigError::EmptyHeaderName
        | WebhookAdapterConfigError::DuplicateHeaderName { .. }
        | WebhookAdapterConfigError::StaticHeaderMayContainSecret { .. }
        | WebhookAdapterConfigError::EmptySecretReference { .. } => {
            WebhookDeliveryFailure::InvalidConfiguration
        }
    }
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;

    use super::*;
    use crate::output::delivery::webhook::{WebhookBodyMode, WebhookSecretResolverError};
    use crate::output::delivery::{
        DeliveryAttemptStatus, DeliveryEventKind, ExternalDeliveryStatus,
        InMemoryDeliveryAttemptStore, deliver_candidate_with_attempt_store,
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

    fn attempt() -> DeliveryAttemptRecord {
        DeliveryAttemptRecord::new(candidate("message").dedupe_key(), "webhook-main", 1, 1_000)
            .start(1_010)
    }

    #[derive(Default)]
    struct TestSecretResolver {
        secrets: BTreeMap<String, Result<Option<String>, WebhookSecretResolverError>>,
    }

    impl TestSecretResolver {
        fn with_secret(mut self, secret_ref: &str, value: &str) -> Self {
            self.secrets
                .insert(secret_ref.to_owned(), Ok(Some(value.to_owned())));
            self
        }

        fn with_error(mut self, secret_ref: &str, error: WebhookSecretResolverError) -> Self {
            self.secrets.insert(secret_ref.to_owned(), Err(error));
            self
        }
    }

    impl WebhookSecretResolver for TestSecretResolver {
        fn resolve_webhook_secret(
            &self,
            secret_ref: &str,
        ) -> Result<Option<String>, WebhookSecretResolverError> {
            self.secrets.get(secret_ref).cloned().unwrap_or(Ok(None))
        }
    }

    #[derive(Debug, Clone)]
    struct TestTransport {
        outcome: WebhookTransportOutcome,
        sent: Vec<WebhookRequest>,
    }

    impl TestTransport {
        fn new(outcome: WebhookTransportOutcome) -> Self {
            Self {
                outcome,
                sent: Vec::new(),
            }
        }

        fn sent(&self) -> &[WebhookRequest] {
            &self.sent
        }
    }

    impl WebhookTransport for TestTransport {
        fn send_webhook_request(&mut self, request: &WebhookRequest) -> WebhookTransportOutcome {
            self.sent.push(request.clone());
            self.outcome.clone()
        }
    }

    #[test]
    fn webhook_delivery_adapter_builds_request_and_classifies_accepted_status() {
        let config = WebhookAdapterConfig::new(
            "webhook-main",
            "https://example.com/hook",
            WebhookBodyMode::RenderedMessage,
            1_000,
        )
        .with_secret_header_ref("X-Signature", "secret://signature");
        let resolver = TestSecretResolver::default()
            .with_secret("secret://signature", "resolved-secret-value");
        let transport = TestTransport::new(WebhookTransportOutcome::HttpStatus {
            status_code: 202,
            completed_at: 1_020,
        });
        let mut adapter = WebhookDeliveryAdapter::new(config, resolver, transport, 1_015);

        let result = adapter.deliver(&candidate("Price crossed"), &attempt());

        assert_eq!(result.status, ExternalDeliveryStatus::Delivered);
        assert_eq!(result.provider_status_code, Some("2xx".to_owned()));
        assert_eq!(adapter.transport().sent().len(), 1);
        assert_eq!(
            adapter.transport().sent()[0].headers().get("X-Signature"),
            Some(&"resolved-secret-value".to_owned())
        );
        assert_eq!(adapter.transport().sent()[0].body(), "Price crossed");
        assert_eq!(adapter.transport().sent()[0].timeout_ms(), 1_000);
    }

    #[test]
    fn webhook_delivery_adapter_maps_request_errors_without_sending() {
        let config = WebhookAdapterConfig::new(
            "webhook-main",
            "https://example.com/hook",
            WebhookBodyMode::RenderedMessage,
            1_000,
        )
        .with_secret_header_ref("X-Signature", "secret://missing");
        let transport = TestTransport::new(WebhookTransportOutcome::HttpStatus {
            status_code: 200,
            completed_at: 1_020,
        });
        let mut adapter =
            WebhookDeliveryAdapter::new(config, TestSecretResolver::default(), transport, 1_015);

        let result = adapter.deliver(&candidate("Price crossed"), &attempt());

        assert_eq!(result.status, ExternalDeliveryStatus::PermanentFailure);
        assert_eq!(
            result.failure_code,
            Some("webhookMissingSecretReference".to_owned())
        );
        assert_eq!(result.completed_at, 1_015);
        assert!(adapter.transport().sent().is_empty());
    }

    #[test]
    fn webhook_delivery_adapter_maps_secret_resolver_unavailable_as_retryable() {
        let config = WebhookAdapterConfig::new(
            "webhook-main",
            "https://example.com/hook",
            WebhookBodyMode::RenderedMessage,
            1_000,
        )
        .with_secret_header_ref("X-Signature", "secret://signature");
        let resolver = TestSecretResolver::default().with_error(
            "secret://signature",
            WebhookSecretResolverError::Unavailable,
        );
        let transport = TestTransport::new(WebhookTransportOutcome::HttpStatus {
            status_code: 200,
            completed_at: 1_020,
        });
        let mut adapter = WebhookDeliveryAdapter::new(config, resolver, transport, 1_015);

        let result = adapter.deliver(&candidate("Price crossed"), &attempt());

        assert_eq!(result.status, ExternalDeliveryStatus::TransientFailure);
        assert_eq!(
            result.failure_code,
            Some("webhookSecretResolverUnavailable".to_owned())
        );
        assert!(adapter.transport().sent().is_empty());
    }

    #[test]
    fn webhook_delivery_adapter_maps_transport_failures() {
        let config = WebhookAdapterConfig::new(
            "webhook-main",
            "https://example.com/hook",
            WebhookBodyMode::RenderedMessage,
            1_000,
        );
        let transport = TestTransport::new(WebhookTransportOutcome::Failure {
            failure: WebhookDeliveryFailure::TransportTimeout,
            completed_at: 1_020,
        });
        let mut adapter =
            WebhookDeliveryAdapter::new(config, TestSecretResolver::default(), transport, 1_015);

        let result = adapter.deliver(&candidate("Price crossed"), &attempt());

        assert_eq!(result.status, ExternalDeliveryStatus::TransientFailure);
        assert_eq!(
            result.failure_code,
            Some("webhookTransportTimeout".to_owned())
        );
        assert_eq!(adapter.transport().sent().len(), 1);
    }

    #[test]
    fn webhook_delivery_adapter_integrates_with_attempt_store_flow() {
        let config = WebhookAdapterConfig::new(
            "webhook-main",
            "https://example.com/hook",
            WebhookBodyMode::JsonEnvelope,
            1_000,
        );
        let transport = TestTransport::new(WebhookTransportOutcome::HttpStatus {
            status_code: 200,
            completed_at: 1_020,
        });
        let mut adapter =
            WebhookDeliveryAdapter::new(config, TestSecretResolver::default(), transport, 1_015);
        let mut store = InMemoryDeliveryAttemptStore::new();

        let run = deliver_candidate_with_attempt_store(
            &mut store,
            &mut adapter,
            candidate("Price crossed"),
            1_000,
            1_010,
        );

        assert_eq!(run.result.status, ExternalDeliveryStatus::Delivered);
        assert_eq!(
            run.completed_attempt.status,
            DeliveryAttemptStatus::Delivered
        );
        assert_eq!(adapter.transport().sent().len(), 1);
        assert!(
            adapter.transport().sent()[0]
                .body()
                .contains("\"renderedMessage\":\"Price crossed\"")
        );
    }
}
