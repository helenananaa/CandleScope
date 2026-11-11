/** A local dataset ID is an immutable source namespace, not an online venue. */
export function sharesReplayMarketScope(
  config: { exchange: string; market_type: string; source_kind: string },
  identity: { exchange: string; market_type: string },
): boolean {
  if (identity.market_type !== config.market_type) return false;
  if (identity.exchange === config.exchange) return true;
  return (config.source_kind === "bar" || config.source_kind === "agg_trade") && config.market_type === "local_bar"
    && /^local-[0-9a-f]{32}$/.test(config.exchange) && /^local-[0-9a-f]{32}$/.test(identity.exchange);
}
