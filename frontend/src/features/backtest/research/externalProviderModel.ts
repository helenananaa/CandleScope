import type { BacktestSnapshot, ExternalProviderConnection, StrategyRevisionRecord } from "../backtestApi.js";
import type { BacktestReport, BacktestRunRecord } from "../backtestTypes.js";
import { researchSnapshotSymbol } from "./backtestResearchModel.js";

export function isExternalRevision(revision: StrategyRevisionRecord | undefined): boolean {
  return revision?.provider_kind === "EXTERNAL_PROVIDER";
}

export function editableResearchRunConfig(config: Record<string, unknown>): Record<string, unknown> {
  const editable = { ...config };
  if (config.pine_runtime_identity) delete editable.strategy_source;
  for (const field of ["strategy_execution_revision", "external_scope_hash", "external_provider_identity"]) delete editable[field];
  for (const field of ["chart_book_data_hash", "pine_runtime_identity", "pine_local_data_root", "pine_order_runtime_identity",
    "pine_fill_callbacks", "pine_process_on_close", "pine_risk_windows", "pine_bar_path_contract", "pine_v2_bar_contract",
    "pine_history_ticks", "pine_realtime_ticks", "host_policy_revision", "risk_policy", "fill_policy", "tif_supported",
    "equity_curve_event_interval", "report_schema", "equity_sampling", "equity_curve_mode", "annualization_days", "benchmark_model"])
    delete editable[field];
  return editable;
}

export function externalRunDraft(config: Record<string, unknown>, revision: StrategyRevisionRecord): Record<string, unknown> {
  const draft = editableResearchRunConfig(config);
  const sameRevision = draft.strategy_revision_id === revision.revision_id;
  if (!sameRevision) {
    delete draft.external_connection_id;
    draft.parameters = {};
  }
  for (const field of ["strategy_source", "python_runtime_mode", "python_trusted_confirmed", "python_execution_protocol"]) delete draft[field];
  const requiredWarmup = Number(revision.warmup_requirement.bars ?? 0);
  return {
    ...draft,
    strategy_revision_id: revision.revision_id,
    output_mode: revision.output_modes.includes(String(draft.output_mode)) ? draft.output_mode : revision.output_modes[0],
    warmup_bars: Math.max(Number(draft.warmup_bars ?? 0), requiredWarmup),
  };
}

export function externalSnapshotRequest(config: Record<string, unknown>): Record<string, unknown> {
  const fields = ["strategy_revision_id", "dataset_id", "data_epoch", "snapshot_hash", "start_time_ms", "end_time_ms",
    "interval", "fidelity_mode", "exchange", "market_type", "contract_data_mode", "account_model", "funding_mode"];
  return Object.fromEntries(fields.filter((field) => config[field] !== undefined).map((field) => [field, config[field]]));
}

export function matchingExternalConnections(connections: readonly ExternalProviderConnection[], config: Record<string, unknown>,
  revision: StrategyRevisionRecord | undefined): ExternalProviderConnection[] {
  if (!isExternalRevision(revision)) return [];
  return connections.filter(({ scope }) => scope.strategy_revision_id === revision?.revision_id
    && scope.manifest_hash === revision.external_provider?.manifest_hash
    && scope.dataset_id === config.dataset_id && scope.data_epoch === config.data_epoch && scope.snapshot_hash === config.snapshot_hash);
}

function canonical(value: unknown): string {
  return JSON.stringify(value, (_key, nested: unknown) => nested && typeof nested === "object" && !Array.isArray(nested)
    ? Object.fromEntries(Object.entries(nested).sort(([a], [b]) => a.localeCompare(b))) : nested);
}

export function externalReportIsStale(input: {
  report: BacktestReport | null; run: BacktestRunRecord | null; revisionId: string; datasetId: string;
  snapshot: Pick<BacktestSnapshot, "data_epoch" | "snapshot_hash" | "catalog_dataset_id" | "identity"> | null; draftText: string;
  request?: Record<string, unknown> | null | undefined;
  externalSelected?: boolean;
}): boolean {
  if (!input.report || (!input.report.strategy?.external_provider && !input.externalSelected)) return false;
  const identity = input.report.identity;
  if ((input.revisionId && identity?.strategy_revision_id !== input.revisionId)
      || (input.datasetId && identity?.dataset_id !== input.datasetId)
      || (input.snapshot && (identity?.data_epoch !== input.snapshot.data_epoch || identity?.snapshot_hash !== input.snapshot.snapshot_hash))) return true;
  try {
    const frozen = JSON.parse(input.run?.config_json ?? "{}") as Record<string, unknown>;
    const canonicalFrozen: Record<string, unknown> = { ...frozen,
      source_event_kind: frozen.source_event_kind ?? input.run?.source_event_kind,
      symbol: frozen.symbol ?? researchSnapshotSymbol(input.snapshot, input.run) };
    if (input.request === null) return true;
    const draft = input.request ?? JSON.parse(input.draftText) as Record<string, unknown>;
    // Compare the normalized request actually submitted, including account,
    // costs, sizing, clocks and risk. Connection ownership is not report truth.
    const metadata = new Set(["external_connection_id", "external_scope_hash", "external_provider_identity", "strategy_execution_revision"]);
    return Object.entries(draft).some(([field, value]) => !metadata.has(field)
      && !(field === "snapshot_hash" && value === "")
      && canonical(canonicalFrozen[field] ?? null) !== canonical(value ?? null));
  } catch { return true; }
}
