import type { ExchangeCapabilityPayload } from "../../services/apiPayloadParsers.js";

/**
 * Named data roles a venue declares (ADR-DATA-002 D3), mirroring the backend
 * `app/exchanges/roles.py`. Features ask for a role and its contract, never for
 * an exchange name.
 */
export const TRADES_HISTORY_ARCHIVE = "trades.history.archive";
export const BINANCE_USDM_AGG_TRADES_ARCHIVE = "binance.public-data.um-agg-trades.daily/1";
export const HEDGE_PUBLIC_HISTORY = "hedge.public_history";
/** Futures contract rules continuous runs simulate: base-unit quantity, linear. */
export const CONTRACT_RULES = "contract_rules";
export const BINANCE_USDM_LINEAR_BASE_QUANTITY = "BINANCE_USDM_LINEAR_BASE_QUANTITY";

/** A venue's capability document; `undefined` while the exchange catalog is unknown. */
export type RoleSource = Pick<ExchangeCapabilityPayload, "roles"> | null | undefined;

/** The contract that supplies `role` for this market, or null when the venue declares none. */
export function capabilityRoleContract(capability: RoleSource, marketType: string, role: string): string | null {
  const market = marketType.trim().toLowerCase();
  const found = capability?.roles?.find((item) => (
    item.role === role && item.market_types.some((value) => value.toLowerCase() === market)
  ));
  return found?.contract ?? null;
}

/**
 * Continuous runs simulate spot cash or base-quantity linear futures. While the
 * venue's roles are unknown the backend decides when the run is created.
 */
export function continuousMarketSupported(venue: RoleSource, marketType: string): boolean {
  if (marketType === "spot") return true;
  if (marketType !== "futures") return false;
  return venue === undefined
    || capabilityRoleContract(venue, marketType, CONTRACT_RULES) === BINANCE_USDM_LINEAR_BASE_QUANTITY;
}
