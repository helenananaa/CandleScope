# Strategy External Alert Delivery Adapter Plan

Status: design gate closed on 2026-06-11.

This document defines the external delivery-adapter boundary for future
running-alert delivery. It does not implement webhook, email, push, SMS,
persistence, retry scheduling, UI, or network clients.

## Background

`docs/STRATEGY_REALTIME_ALERT_DELIVERY_PLAN.md` now defines a host-owned
realtime loop, a host-only `DeliveryCandidate`, and a host-provided
`DeliverySink`. The remaining missing design is the concrete adapter layer that
can turn a delivery candidate into an external side effect while keeping Pine
runtime behavior deterministic.

Official alert behavior keeps Pine execution and external delivery separate:

- Pine scripts and broker fills produce alert events.
- A running alert is created and managed by the host.
- Alert delivery, including webhook delivery, belongs to the host alert system.

Sources:

- TradingView Pine Script alerts documentation:
  <https://www.tradingview.com/pine-script-docs/concepts/alerts/>
- TradingView webhook alert configuration documentation:
  <https://www.tradingview.com/support/solutions/43000529348-how-to-configure-webhook-alerts/>

## Current Repository Boundary

Already supported:

- host-side `DeliveryCandidate` values with stable dedupe keys;
- an in-memory `DeliverySink` for tests;
- a strategy order-fill candidate builder over `RunningAlertConfig` and public
  `strategy.alerts` events;
- a design-only shared host event envelope for future `both` selection;
- pure host-side external delivery identity, attempt status, attempt record,
  result status, and result types without external delivery side effects;
- a host-side `DeliveryAttemptStore` trait plus in-memory implementation for
  tests, covering reserve, start, and complete flows;
- a pure test-collector delivery adapter and host helper that exercise the
  reserve, start, deliver, and complete flow without network delivery.
- pure webhook adapter configuration and validation types covering URL,
  headers, secret header references, body mode, and timeout without network
  delivery.
- pure webhook payload rendering for `renderedMessage` and `jsonEnvelope`
  modes without network delivery.
- pure webhook delivery failure classification for transport, configuration,
  payload, secret-reference, and provider-status failures, including redacted
  provider status classes.
- pure webhook retry decision calculation for transient failures with bounded
  deterministic backoff and attempt-budget checks.
- pure host delivery diagnostic records and redacted diagnostic construction
  from delivery attempts plus external delivery results.
- pure webhook secret-resolver interface and resolved-header construction for
  host transport code, without storing or serializing resolved secret values.
- pure webhook request construction from validated configuration, resolved
  headers, and rendered payloads, still without any HTTP client or network
  side effects.
- a pure webhook delivery adapter over a host-provided transport trait. The
  adapter connects request construction, fake/host transport outcomes,
  HTTP-status classification, and attempt-store flow without creating an HTTP
  client or performing network I/O. The transport receives only the already
  built `WebhookRequest`, not attempt-store or runtime state.
- pure host delivery diagnostic emission from the adapter run helper. Failed
  delivery runs now carry a redacted `HostDeliveryDiagnostic` next to the
  attempt/result pair without mutating runtime JSON or Pine diagnostics.
- pure in-memory attempt-store recording of host-planned `nextRetryAt`
  timestamps for completed attempts, without executing retry scheduling,
  jitter, dead-lettering, or durable restart recovery.
- pure webhook retry-plan recording that combines the bounded retry decision
  with existing attempt-store `nextRetryAt` metadata, without creating the next
  attempt, sleeping, scheduling jobs, adding jitter, or performing network I/O.

Still unsupported:

- concrete external delivery adapters;
- durable delivery store behavior across host restarts;
- executable retry scheduling, jitter, and dead-letter behavior;
- executable webhook HTTP transport, concrete authentication secret stores,
  secret lookup audit logging, TLS configuration, timeout execution, built-in
  network request execution, retry scheduling, and rate limiting;
- user-visible delivery failure reporting;
- live realtime strategy broker execution.

## Decision

External delivery must stay outside the interpreter and core runtime crates. The
runtime may produce public alert events, host helpers may build delivery
candidates, and a host-owned adapter may deliver those candidates. No adapter
may be required by default historical `run` output.

The adapter layer should have this conceptual shape:

```text
DeliveryCandidate
  -> DeliveryAttemptStore.reserve(dedupeKey, adapterId)
  -> ExternalDeliveryAdapter.deliver(candidate, attempt)
  -> DeliveryAttemptStore.complete(attempt, result)
  -> HostDeliveryDiagnostics
```

The adapter is a side-effect boundary. It must be explicit in host APIs and
must never be triggered implicitly by a normal script analysis or historical
runtime run.

## Adapter Contract

A concrete adapter should be described by stable host metadata:

```text
ExternalDeliveryAdapter
  adapterId: string
  adapterKind: localLog | testCollector | webhook | future
  deliver(candidate, attempt) -> ExternalDeliveryResult
```

The result should be small and host-diagnostic oriented:

```text
ExternalDeliveryResult
  status: delivered | transientFailure | permanentFailure
  providerStatusCode: optional string
  failureCode: optional string
  failureMessage: optional string
  completedAt: host timestamp
```

`delivered` means the adapter accepted the side effect according to its own
contract. It does not prove that a remote human saw the alert or that a remote
system acted on it.

## Durable Attempt State

Any support claim for at-most-once or retryable delivery after host restart
requires durable host state. The first store contract should retain:

```text
DeliveryAttemptRecord
  dedupeKey: DeliveryDedupeKey
  adapterId: string
  attemptNumber: u32
  status: pending | inFlight | delivered | transientFailure | permanentFailure
  scheduledAt: host timestamp
  startedAt: optional host timestamp
  completedAt: optional host timestamp
  nextRetryAt: optional host timestamp
  failureCode: optional string
```

The persisted identity for external delivery should be:

```text
adapterId + DeliveryDedupeKey
```

If a host uses only the current in-memory sink, delivery is test-only and cannot
claim restart-safe dedupe or retry semantics.

## Retry Policy

Retry policy is host-owned and adapter-specific. A future implementation should
start with conservative rules:

- retry only `transientFailure` results;
- never retry `permanentFailure` results unless the user creates a new running
  alert or explicitly requeues the attempt;
- use bounded attempts with backoff and jitter;
- keep per-adapter timeout and rate-limit settings outside the runtime;
- record every attempt in the durable store before performing another external
  side effect.

The runtime should not know whether a delivery failed, retried, or reached a
dead-letter queue.

## Authentication And Secrets

Authentication belongs to the host adapter configuration. Runtime values,
runtime JSON, semantic diagnostics, and public snapshots must not contain
credential material.

The first adapter configuration should store secret references, not secret
values:

```text
WebhookAdapterConfig
  url: host-validated URL
  headers: static non-secret headers
  secretHeaderRefs: host secret references
  bodyMode: renderedMessage | jsonEnvelope
  timeoutMs: host-owned bounded duration
```

Host implementations are responsible for URL validation, TLS policy, header
redaction, secret lookup, audit logging, and preventing credentials from
appearing in diagnostics.

## Webhook Adapter Design Lock

Webhook delivery is a concrete host adapter, not a runtime feature. A future
implementation must keep HTTP clients, URL parsing, DNS, TLS, headers, secrets,
timeouts, and provider status handling outside the interpreter and core runtime
execution path.

The first webhook slice should introduce configuration and validation before any
network transport:

```text
WebhookAdapterConfig
  adapterId: string
  url: string
  headers: map string string
  secretHeaderRefs: map string secretRef
  bodyMode: renderedMessage | jsonEnvelope
  timeoutMs: u32
```

Validation rules:

- accept only host-approved HTTP(S) URL schemes and ports;
- reject empty URLs, relative URLs, local file paths, and URLs with embedded
  credentials;
- require a bounded positive timeout;
- reject duplicate header names after case normalization;
- reject static headers that contain credential-like material when a
  `secretHeaderRefs` entry should be used instead;
- keep URL allowlists, DNS policy, TLS roots, proxy policy, and rate limits
  host-owned.

Payload rules:

- `renderedMessage` sends only `DeliveryCandidate.renderedMessage`;
- `jsonEnvelope` sends a host-versioned object containing adapter metadata and
  candidate fields;
- webhook payload schemas must be versioned separately from `RuntimeResult`;
- secrets must never be copied into payload bodies, stored attempts, public
  snapshots, runtime JSON, or semantic diagnostics.

Content-type rules are adapter-owned. The host may choose `application/json`
when the payload is valid JSON and a plain text content type otherwise, but that
choice must not affect Pine evaluation.

Failure classification:

- transport timeout, connection reset, DNS failure, rate limiting, and
  temporary server failures map to `transientFailure`;
- invalid configuration, rejected URL, missing secret reference, unauthorized
  secret lookup, and invalid payload construction map to `permanentFailure`;
- a successful HTTP exchange maps to `delivered` only when the adapter contract
  says the provider accepted the request;
- provider status codes and failure messages must be redacted before becoming
  host diagnostics.

The first executable webhook work should therefore be a pure configuration and
validation slice. It must not send network requests until URL validation, secret
reference handling, timeout behavior, payload selection, failure
classification, and diagnostic redaction are fixture-backed.

## Payload Boundary

The adapter receives a `DeliveryCandidate`; it does not receive interpreter
state, broker internals, or mutable script state.

The first webhook-capable implementation should choose one payload mode at a
time:

- `renderedMessage`: send the already rendered delivery message;
- `jsonEnvelope`: send a host-defined JSON envelope containing the candidate
  fields and adapter metadata.

`jsonEnvelope` must be a host delivery schema, not an expansion of
`RuntimeResult`. It should be versioned separately from runtime JSON.

## Failure Reporting

Delivery failures are host diagnostics. They must not become Pine semantic
diagnostics and must not mutate runtime output.

A future host API should expose delivery diagnostics separately:

```text
HostDeliveryDiagnostic
  runningAlertId: string
  scriptSnapshotId: string
  adapterId: string
  dedupeKey: DeliveryDedupeKey
  severity: info | warning | error
  code: string
  message: string
```

Diagnostics should be redacted by default. They may mention adapter kind,
attempt count, and failure class, but not secret values or full sensitive
headers.

## Concrete HTTP Transport Gate

The first concrete webhook HTTP transport is now allowed to start only after
this gate remains true in the implementation slice:

- HTTP client dependency must be explicit in `Cargo.toml` and reviewed as a
  host transport dependency, not an interpreter dependency.
- The transport must live behind the existing `WebhookTransport` trait and be
  constructed explicitly by host code.
- The transport must accept only an already built `WebhookRequest`; it must not
  receive runtime state, broker state, `RuntimeResult`, or script internals.
- The transport must enforce `WebhookRequest.timeout_ms()` as the request
  timeout and map timeout failures to `WebhookDeliveryFailure::TransportTimeout`.
- Provider HTTP status handling must continue to flow through
  `classify_webhook_http_status`, preserving redacted status classes.
- Network, TLS roots, proxy settings, DNS behavior, and rate limits must remain
  host transport concerns. The runtime cannot infer or expose them.
- Unit tests must use a local fake/server or transport shim. They must not call
  internet endpoints.
- Default CLI, Python, WASM, and runtime outputs must remain unchanged. A host
  must opt in before any network side effect can occur.
- Secret values must not appear in debug output, payloads, attempt records,
  diagnostics, release notes, or snapshots.

If any of these choices require a dependency or policy decision that cannot be
made from the repository alone, stop and make the decision explicit before
adding network I/O.

## Non-Goals

- Do not implement network delivery in this design slice.
- Do not add default webhook, email, push, SMS, or broker side effects.
- Do not add running-alert UI or user account storage.
- Do not change `RuntimeResult`, `alerts[]`, `strategy.alerts[]`, CLI JSON,
  Python dictionaries, or WASM runtime JSON.
- Do not claim live strategy alert delivery before realtime strategy execution
  itself is fixture-backed.
- Do not claim restart-safe delivery until durable attempt-store behavior is
  implemented and tested.

## Implementation Slices

1. Closed on 2026-06-11: this design gate for adapter ownership, durable state,
   retry, authentication, payload, and failure-reporting boundaries.
2. Closed on 2026-06-11: add pure host-side attempt/result types and tests
   without external delivery.
3. Closed on 2026-06-11: add a delivery-attempt-store trait plus an in-memory
   implementation for tests. The in-memory store does not claim restart-safe
   durability.
4. Closed on 2026-06-11: add a test-collector adapter that exercises attempt
   recording without network delivery.
5. Closed on 2026-06-11: lock the webhook adapter design boundary for URL
   validation, secret references, payload mode, timeout behavior, failure
   classification, and diagnostic redaction without network delivery.
6. Closed on 2026-06-11: add pure webhook adapter configuration and validation
   types with tests for URL, header, secret-reference, body-mode, and timeout
   boundaries, still without network delivery.
7. Closed on 2026-06-11: add webhook payload rendering for `renderedMessage`
   and `jsonEnvelope`, still without network delivery.
8. Closed on 2026-06-11: add pure webhook delivery failure classification and
   redacted HTTP status classes, still without network delivery, retry
   scheduling, secret lookup, or host diagnostic emission.
9. Closed on 2026-06-11: add pure webhook retry decision and bounded backoff
   calculation for transient failures, still without executable retry
   scheduling, durable restart recovery, jitter, dead-lettering, or network
   delivery.
10. Closed on 2026-06-11: add pure host delivery diagnostic records and
    redacted diagnostic construction from attempt/result pairs, still without
    runtime JSON changes, Pine semantic diagnostics, user-visible reporting, or
    network delivery.
11. Closed on 2026-06-11: add a pure webhook secret-resolver interface and
    resolved-header construction for host transport code, still without
    concrete secret stores, audit logging, user-visible reporting, or network
    delivery.
12. Closed on 2026-06-11: add pure webhook request construction from validated
    config, resolved headers, and payloads, still without HTTP clients,
    request execution, retry scheduling, or network delivery.
13. Closed on 2026-06-11: add a pure webhook delivery adapter over a
    host-provided transport trait. The adapter maps request construction errors,
    fake transport failures, and HTTP status outcomes into
    `ExternalDeliveryResult` and integrates with the attempt-store helper,
    still without an HTTP client, built-in network I/O, executable retry
    scheduling, or user-visible reporting.
14. Closed on 2026-06-11: emit redacted host delivery diagnostics from the
    adapter run helper for failed delivery attempts. Delivered attempts carry
    no diagnostic; transient and permanent failures carry host-only diagnostics
    without Pine semantic diagnostics, public runtime JSON changes, or
    user-visible reporting.
15. Closed on 2026-06-11: add pure in-memory attempt-store recording for
    host-planned `nextRetryAt` timestamps on existing attempts. This records
    retry metadata only and does not create a scheduler, jitter, dead-letter
    queue, durable restart recovery, network I/O, or user-visible reporting.
16. Closed on 2026-06-11: add pure webhook retry-plan recording over completed
    adapter runs. The helper writes `nextRetryAt` only when the bounded retry
    policy returns `RetryAt`, leaves delivered/permanent attempts unchanged,
    reports missing attempts, and still does not create a scheduler, jitter,
    dead-letter queue, durable restart recovery, network I/O, or user-visible
    reporting.
17. Closed on 2026-06-11: lock the concrete HTTP transport implementation gate.
    The gate requires an explicit host transport dependency, opt-in
    construction, `WebhookTransport` isolation, request timeout enforcement,
    local-only tests, redacted diagnostics, unchanged runtime JSON, and no
    internet endpoint tests.
18. Closed on 2026-06-11: tighten the `WebhookTransport` trait so concrete
    host transports receive only an already built `WebhookRequest`. The
    adapter still owns attempt-store flow, while future transport code cannot
    inspect attempt records, runtime state, broker state, `RuntimeResult`, or
    script internals.
19. Add a concrete webhook HTTP transport only after URL validation, secret
    handling, timeout behavior, retry classification, diagnostic redaction, and
    host transport execution boundaries are fixture-backed.

## Completion Gate

This design gate is closed when:

- concrete external delivery remains host-owned;
- adapter, attempt, retry, authentication, payload, and failure-reporting
  boundaries are explicit;
- durable state is required before restart-safe delivery claims;
- public runtime JSON remains unchanged;
- network delivery remains unimplemented until a later fixture-backed slice.
