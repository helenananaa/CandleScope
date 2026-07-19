use std::collections::BTreeMap;
use std::fmt;

use crate::output::delivery::DeliveryCandidate;

use super::{
    WebhookAdapterConfig, WebhookAdapterConfigError, WebhookPayloadError, render_webhook_payload,
};

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WebhookSecretResolverError {
    Unauthorized,
    Unavailable,
}

pub trait WebhookSecretResolver {
    fn resolve_webhook_secret(
        &self,
        secret_ref: &str,
    ) -> Result<Option<String>, WebhookSecretResolverError>;
}

#[derive(Clone, PartialEq, Eq)]
pub struct WebhookResolvedHeaders {
    headers: BTreeMap<String, String>,
}

impl WebhookResolvedHeaders {
    pub fn headers(&self) -> &BTreeMap<String, String> {
        &self.headers
    }
}

impl fmt::Debug for WebhookResolvedHeaders {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("WebhookResolvedHeaders")
            .field("header_count", &self.headers.len())
            .field("values", &"<redacted>")
            .finish()
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum WebhookResolvedHeadersError {
    InvalidConfig(WebhookAdapterConfigError),
    MissingSecretReference { header_name: String },
    UnauthorizedSecretLookup { header_name: String },
    SecretResolverUnavailable { header_name: String },
}

impl From<WebhookAdapterConfigError> for WebhookResolvedHeadersError {
    fn from(error: WebhookAdapterConfigError) -> Self {
        Self::InvalidConfig(error)
    }
}

pub fn resolve_webhook_headers<R>(
    config: &WebhookAdapterConfig,
    resolver: &R,
) -> Result<WebhookResolvedHeaders, WebhookResolvedHeadersError>
where
    R: WebhookSecretResolver,
{
    config.validate()?;
    let mut headers = config.headers.clone();
    for (header_name, secret_ref) in &config.secret_header_refs {
        let value = resolver
            .resolve_webhook_secret(secret_ref)
            .map_err(|error| match error {
                WebhookSecretResolverError::Unauthorized => {
                    WebhookResolvedHeadersError::UnauthorizedSecretLookup {
                        header_name: header_name.clone(),
                    }
                }
                WebhookSecretResolverError::Unavailable => {
                    WebhookResolvedHeadersError::SecretResolverUnavailable {
                        header_name: header_name.clone(),
                    }
                }
            })?
            .filter(|value| !value.trim().is_empty())
            .ok_or_else(|| WebhookResolvedHeadersError::MissingSecretReference {
                header_name: header_name.clone(),
            })?;
        headers.insert(header_name.clone(), value);
    }
    Ok(WebhookResolvedHeaders { headers })
}

#[derive(Clone, PartialEq, Eq)]
pub struct WebhookRequest {
    url: String,
    timeout_ms: u32,
    headers: WebhookResolvedHeaders,
    content_type: String,
    body: String,
}

impl WebhookRequest {
    pub fn url(&self) -> &str {
        &self.url
    }

    pub fn timeout_ms(&self) -> u32 {
        self.timeout_ms
    }

    pub fn headers(&self) -> &BTreeMap<String, String> {
        self.headers.headers()
    }

    pub fn content_type(&self) -> &str {
        &self.content_type
    }

    pub fn body(&self) -> &str {
        &self.body
    }
}

impl fmt::Debug for WebhookRequest {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("WebhookRequest")
            .field("url", &self.url)
            .field("timeout_ms", &self.timeout_ms)
            .field("headers", &self.headers)
            .field("content_type", &self.content_type)
            .field("body_len", &self.body.len())
            .finish()
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum WebhookRequestError {
    Payload(WebhookPayloadError),
    Headers(WebhookResolvedHeadersError),
}

impl From<WebhookPayloadError> for WebhookRequestError {
    fn from(error: WebhookPayloadError) -> Self {
        Self::Payload(error)
    }
}

impl From<WebhookResolvedHeadersError> for WebhookRequestError {
    fn from(error: WebhookResolvedHeadersError) -> Self {
        Self::Headers(error)
    }
}

pub fn build_webhook_request<R>(
    config: &WebhookAdapterConfig,
    candidate: &DeliveryCandidate,
    resolver: &R,
) -> Result<WebhookRequest, WebhookRequestError>
where
    R: WebhookSecretResolver,
{
    let payload = render_webhook_payload(config, candidate)?;
    let headers = resolve_webhook_headers(config, resolver)?;
    Ok(WebhookRequest {
        url: config.url.clone(),
        timeout_ms: config.timeout_ms,
        headers,
        content_type: payload.content_type,
        body: payload.body,
    })
}

#[cfg(test)]
mod tests {
    use super::super::WebhookBodyMode;
    use super::*;
    use crate::output::delivery::DeliveryEventKind;

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

        fn with_missing(mut self, secret_ref: &str) -> Self {
            self.secrets.insert(secret_ref.to_owned(), Ok(None));
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

    #[test]
    fn webhook_headers_resolve_static_and_secret_headers_for_host_transport() {
        let config = WebhookAdapterConfig::new(
            "webhook-main",
            "https://example.com/hook",
            WebhookBodyMode::RenderedMessage,
            1_000,
        )
        .with_header("Content-Type", "text/plain")
        .with_secret_header_ref("X-Signature", "secret://signature");
        let resolver = TestSecretResolver::default()
            .with_secret("secret://signature", "resolved-secret-value");

        let resolved = resolve_webhook_headers(&config, &resolver).expect("headers resolve");

        assert_eq!(
            resolved.headers().get("Content-Type"),
            Some(&"text/plain".to_owned())
        );
        assert_eq!(
            resolved.headers().get("X-Signature"),
            Some(&"resolved-secret-value".to_owned())
        );
    }

    #[test]
    fn webhook_resolved_headers_debug_redacts_secret_values() {
        let config = WebhookAdapterConfig::new(
            "webhook-main",
            "https://example.com/hook",
            WebhookBodyMode::RenderedMessage,
            1_000,
        )
        .with_secret_header_ref("X-Signature", "secret://signature");
        let resolver = TestSecretResolver::default()
            .with_secret("secret://signature", "resolved-secret-value");

        let resolved = resolve_webhook_headers(&config, &resolver).expect("headers resolve");
        let debug = format!("{resolved:?}");

        assert!(debug.contains("<redacted>"));
        assert!(!debug.contains("resolved-secret-value"));
        assert!(!debug.contains("secret://signature"));
    }

    #[test]
    fn webhook_headers_report_missing_secret_refs_without_secret_values() {
        let config = WebhookAdapterConfig::new(
            "webhook-main",
            "https://example.com/hook",
            WebhookBodyMode::RenderedMessage,
            1_000,
        )
        .with_secret_header_ref("X-Signature", "secret://missing");
        let resolver = TestSecretResolver::default().with_missing("secret://missing");

        assert_eq!(
            resolve_webhook_headers(&config, &resolver),
            Err(WebhookResolvedHeadersError::MissingSecretReference {
                header_name: "X-Signature".to_owned(),
            })
        );
    }

    #[test]
    fn webhook_headers_report_unauthorized_secret_lookup_by_header_name() {
        let config = WebhookAdapterConfig::new(
            "webhook-main",
            "https://example.com/hook",
            WebhookBodyMode::RenderedMessage,
            1_000,
        )
        .with_secret_header_ref("X-Signature", "secret://signature");
        let resolver = TestSecretResolver::default().with_error(
            "secret://signature",
            WebhookSecretResolverError::Unauthorized,
        );

        assert_eq!(
            resolve_webhook_headers(&config, &resolver),
            Err(WebhookResolvedHeadersError::UnauthorizedSecretLookup {
                header_name: "X-Signature".to_owned(),
            })
        );
    }

    #[test]
    fn webhook_headers_reuse_config_validation() {
        let config = WebhookAdapterConfig::new(
            "webhook-main",
            "https://example.com/hook",
            WebhookBodyMode::RenderedMessage,
            1_000,
        )
        .with_header("Authorization", "Bearer abc123");
        let resolver = TestSecretResolver::default();

        assert_eq!(
            resolve_webhook_headers(&config, &resolver),
            Err(WebhookResolvedHeadersError::InvalidConfig(
                WebhookAdapterConfigError::StaticHeaderMayContainSecret {
                    header_name: "Authorization".to_owned(),
                }
            ))
        );
    }

    #[test]
    fn webhook_request_builder_combines_validated_config_headers_and_payload() {
        let config = WebhookAdapterConfig::new(
            "webhook-main",
            "https://example.com/hook",
            WebhookBodyMode::RenderedMessage,
            1_000,
        )
        .with_header("X-Trace", "public")
        .with_secret_header_ref("X-Signature", "secret://signature");
        let resolver = TestSecretResolver::default()
            .with_secret("secret://signature", "resolved-secret-value");

        let request = build_webhook_request(&config, &candidate("Price crossed"), &resolver)
            .expect("request");

        assert_eq!(request.url(), "https://example.com/hook");
        assert_eq!(request.timeout_ms(), 1_000);
        assert_eq!(request.content_type(), "text/plain; charset=utf-8");
        assert_eq!(request.body(), "Price crossed");
        assert_eq!(request.headers().get("X-Trace"), Some(&"public".to_owned()));
        assert_eq!(
            request.headers().get("X-Signature"),
            Some(&"resolved-secret-value".to_owned())
        );
    }

    #[test]
    fn webhook_request_debug_redacts_headers_and_body() {
        let config = WebhookAdapterConfig::new(
            "webhook-main",
            "https://example.com/hook",
            WebhookBodyMode::RenderedMessage,
            1_000,
        )
        .with_secret_header_ref("X-Signature", "secret://signature");
        let resolver = TestSecretResolver::default()
            .with_secret("secret://signature", "resolved-secret-value");

        let request = build_webhook_request(&config, &candidate("Sensitive message"), &resolver)
            .expect("request");
        let debug = format!("{request:?}");

        assert!(debug.contains("body_len"));
        assert!(!debug.contains("resolved-secret-value"));
        assert!(!debug.contains("secret://signature"));
        assert!(!debug.contains("Sensitive message"));
    }

    #[test]
    fn webhook_request_builder_reports_header_resolution_errors() {
        let config = WebhookAdapterConfig::new(
            "webhook-main",
            "https://example.com/hook",
            WebhookBodyMode::RenderedMessage,
            1_000,
        )
        .with_secret_header_ref("X-Signature", "secret://missing");
        let resolver = TestSecretResolver::default().with_missing("secret://missing");

        assert_eq!(
            build_webhook_request(&config, &candidate("message"), &resolver),
            Err(WebhookRequestError::Headers(
                WebhookResolvedHeadersError::MissingSecretReference {
                    header_name: "X-Signature".to_owned(),
                }
            ))
        );
    }

    #[test]
    fn webhook_request_builder_reports_payload_config_errors() {
        let config = WebhookAdapterConfig::new(
            "webhook-main",
            "file:///tmp/hook",
            WebhookBodyMode::RenderedMessage,
            1_000,
        );
        let resolver = TestSecretResolver::default();

        assert_eq!(
            build_webhook_request(&config, &candidate("message"), &resolver),
            Err(WebhookRequestError::Payload(
                WebhookPayloadError::InvalidConfig(WebhookAdapterConfigError::UnsupportedUrlScheme)
            ))
        );
    }
}
