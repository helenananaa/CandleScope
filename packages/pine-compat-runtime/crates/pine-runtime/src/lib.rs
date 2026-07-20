//! Historical runtime scaffolding.

pub use pine_ir::ValueKind;
use pine_ir::{CallSiteId, HirExpr, PersistenceKind, SeriesId, SymbolId, VarSlotId};

mod algorithms;
mod bar;
mod builtins;
mod error;
mod input_metadata;
mod output;
mod profile;
mod request;
mod retention;
mod runtime;
mod series;
mod strategy;
mod value;

pub use bar::{Bar, BarUpdate, BarUpdateKind};
pub use error::RuntimeError;
pub use input_metadata::{InputCall, input_calls};
pub use output::alerts::AlertEvent;
pub use output::delivery::{
    DeliveryAdapterRun, DeliveryAttemptRecord, DeliveryAttemptStatus, DeliveryAttemptStore,
    DeliveryCandidate, DeliveryDedupeKey, DeliveryEventKind, DeliveryOutcome, DeliverySink,
    ExternalDeliveryAdapter, ExternalDeliveryIdentity, ExternalDeliveryResult,
    ExternalDeliveryStatus, HostDeliveryDiagnostic, HostDeliveryDiagnosticSeverity,
    InMemoryDeliveryAttemptStore, InMemoryDeliverySink, TestCollectorDeliveryAdapter,
    TestCollectorDeliveryRecord, WebhookAdapterConfig, WebhookAdapterConfigError, WebhookBodyMode,
    WebhookDeliveryAdapter, WebhookDeliveryFailure, WebhookPayload, WebhookPayloadError,
    WebhookRequest, WebhookRequestError, WebhookResolvedHeaders, WebhookResolvedHeadersError,
    WebhookRetryDecision, WebhookRetryPolicy, WebhookRetryPolicyError, WebhookRetryRecordError,
    WebhookSecretResolver, WebhookSecretResolverError, WebhookTransport, WebhookTransportOutcome,
    build_webhook_request, classify_webhook_delivery_failure, classify_webhook_http_status,
    deliver_candidate_with_attempt_store, host_delivery_diagnostic_from_result,
    plan_and_record_webhook_retry, plan_webhook_retry, render_webhook_payload,
    resolve_webhook_headers, strategy_order_fill_delivery_candidate,
};
pub use output::drawings::{
    BoxOutput, BoxSnapshot, LabelOutput, LabelSnapshot, LineFillOutput, LineFillSnapshot,
    LineOutput, LineSnapshot, PolylineOutput, PolylineSnapshot, TableCellSnapshot,
    TableMergedCellSnapshot, TableOutput, TableSnapshot,
};
pub use output::json::{public_runtime_profiled_result_json, public_runtime_result_json};
pub use output::model::{
    ColorSeries, FillOutput, HLineOutput, OutputMetadata, PUBLIC_MATRIX_SCHEMA_VERSION,
    PUBLIC_OUTPUT_SCHEMA_VERSION, PUBLIC_RENDER_METADATA_VERSION, PUBLIC_RUNTIME_SCHEMA_VERSION,
    PlotArrowSeries, PlotBarSeries, PlotCandleSeries, PlotCharSeries, PlotSeries, PlotShapeSeries,
    RuntimeDiagnostic, RuntimeResult,
};
pub use output::running_alerts::{
    RunningAlertConfig, RunningAlertEvaluationError, RunningAlertEventSelection,
    RunningAlertRealtimePolicy, render_strategy_order_fill_running_alert,
};
pub use output::strategy::{
    StrategyEquitySnapshot, StrategyOrderEvent, StrategyOrderFillAlertOutput,
    StrategyPositionSnapshot, StrategyResult, StrategyTrade,
};
pub use output::strategy_alert_templates::{
    STRATEGY_ORDER_ALERT_MESSAGE_PLACEHOLDER, StrategyOrderFillAlertTemplateError,
    render_strategy_order_fill_alert_template,
};
pub use profile::{RuntimeProfile, RuntimeProfiledResult};
pub(crate) use request::RequestCacheKey;
pub use request::{
    ChartContext, InMemoryRequestDataProvider, NoRequestDataProvider, RequestDataError,
    RequestDataProvider, RequestEnvironment, RequestKey, RequestTimeframe, RequestTimeframeError,
    validate_requested_bars,
};
pub use retention::HistoryRetentionMode;
pub use runtime::historical::{
    HistoricalRuntime, InputOverrides, run_historical, run_historical_profiled,
    run_historical_profiled_with_request_environment,
    run_historical_profiled_with_request_environment_and_input_overrides,
    run_historical_with_input_overrides, run_historical_with_request_environment,
    run_historical_with_request_environment_and_input_overrides,
};
pub use runtime::realtime::RealtimeRuntime;
pub use series::SeriesStore;
pub use strategy::BrokerState;
pub use value::{PineValue, encode_color_literal, encode_color_rgba, is_valid_public_color};

use algorithms::numeric::finite_float_or_na;
use algorithms::rolling_window::{
    RisingFallingMode, RollingWindowKey, RollingWindowState, WindowExtreme,
};
use builtins::args::output_id;
use builtins::arrays::{ArrayElementKind, ArrayPercentileMode, ArraySlice};
use builtins::maps::MapStorage;
use builtins::matrices::MatrixStorage;
use builtins::ta::{MacdState, PivotPointState, RsiState, VwapState};
use output::align::finalize_bar_aligned_outputs;
use output::collect::{finalize_plot_values, finalize_series_values};
use retention::SeriesRetention;
use runtime::expressions::values_equal;
use runtime::statements::StmtControl;

#[cfg(test)]
use builtins::colors::apply_transparency;
#[cfg(test)]
use builtins::ta::{PivotPointPeriod, pivot_na_levels, pivot_point_levels};

const MAX_WHILE_ITERATIONS: usize = 100_000;
const MAX_RUNTIME_EVAL_DEPTH: u32 = 256;
const MAX_ARRAY_ELEMENTS: usize = 100_000;
const MAX_STRING_CHARS: usize = 40_960;
const MAX_SERIES_HISTORY_VALUES: usize = 1_000_000;
const DEFAULT_MAX_LABELS: usize = 50;
const MAX_LABELS: usize = 500;
const DEFAULT_MAX_LINES: usize = 50;
const MAX_LINES: usize = 500;
const MAX_LINEFILLS: usize = 500;
const DEFAULT_MAX_POLYLINES: usize = 50;
const MAX_POLYLINES: usize = 100;
const DEFAULT_MAX_BOXES: usize = 50;
const MAX_BOXES: usize = 500;
const MAX_TABLES: usize = 50;
const MAX_TABLE_CELLS: i64 = 1_000;
const DEFAULT_CHART_TIMEFRAME: &str = "1";

#[cfg(test)]
mod tests;
