import { record } from "./accountApi.js";

/** Exchange amounts stay exact decimal strings; anything else is unknown. */
const DECIMAL = /^-?(?:0|[1-9][0-9]{0,35})(?:\.[0-9]{1,36})?$/;
const CURRENCY = /^[A-Z0-9]{1,20}$/;

export type MarginMode = "cross" | "isolated";

export interface PositionMargin {
  marginMode: MarginMode | null;
  /** Leverage multiple, e.g. "10". */
  leverage: string | null;
  /** Estimated liquidation price, in `priceCurrency`. */
  liquidationPrice: string | null;
  priceCurrency: string | null;
  /** Isolated: margin held by the position. Cross: initial margin it uses from the shared balance. */
  margin: string | null;
  marginCurrency: string | null;
  settleCurrency: string | null;
  /** The exchange's last update of this position. */
  updatedMs: number | null;
}

export interface BalanceMargin {
  currency: string | null;
  /** Equity in `currency` that cross positions settled in it can still use. */
  availableMargin: string | null;
  updatedMs: number | null;
}

function amount(value: unknown): string | null {
  return typeof value === "string" && DECIMAL.test(value) ? value : null;
}
function currency(value: unknown): string | null {
  return typeof value === "string" && CURRENCY.test(value) ? value : null;
}
function time(value: unknown): number | null {
  const ms = typeof value === "number" ? value : typeof value === "string" && /^[0-9]{1,16}$/.test(value) ? Number(value) : null;
  return ms !== null && Number.isSafeInteger(ms) && ms > 0 ? ms : null;
}

/** Margin and risk fields of one normalized position. Snapshots saved before
 * these fields existed read as unknown until the next sync replaces them. */
export function positionMargin(item: Record<string, unknown>): PositionMargin {
  const mode = item.marginMode === "cross" || item.marginMode === "isolated" ? item.marginMode : null;
  const leverage = amount(item.leverage);
  const liquidation = amount(item.liquidationPrice);
  return {
    marginMode: mode,
    leverage: leverage !== null && Number(leverage) > 0 ? leverage : null,
    liquidationPrice: liquidation !== null && Number(liquidation) > 0 ? liquidation : null,
    priceCurrency: currency(item.priceCurrency),
    margin: amount(item.margin),
    marginCurrency: currency(item.marginCurrency),
    settleCurrency: currency(item.settleCurrency),
    updatedMs: time(item.eventTimeMs),
  };
}

/** Available margin of one balance currency (the exchange's available equity). */
export function balanceMargin(detail: Record<string, unknown>): BalanceMargin {
  return { currency: currency(detail.ccy), availableMargin: amount(detail.availEq), updatedMs: time(detail.uTime) };
}

export function balanceDetails(snapshot: unknown): Record<string, unknown>[] {
  if (!Array.isArray(snapshot)) return [];
  return snapshot.filter(record).flatMap((account) => Array.isArray(account.details) ? account.details.filter(record) : []);
}
