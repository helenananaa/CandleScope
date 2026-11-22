import type { ExternalProviderConnection, StrategyRevisionRecord } from "../backtestApi.js";

/** An external model's connection scope, as the research workspace's external model panel uses it (ADR-BACKTEST-015 P5d). */
export function isExternalRevision(revision: StrategyRevisionRecord | undefined): boolean {
  return revision?.provider_kind === "EXTERNAL_PROVIDER";
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
