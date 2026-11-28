import { record, type AccountStatus } from "./accountApi.js";

/** Cost rates: a positive rate is a fee, a negative one a rebate. */
export interface FeeRatePair { maker: string | null; taker: string | null }
export type FeeSettlement = "usdtMargined" | "coinMargined";

export interface FeeRateEstimate {
  tier: string | null;
  settlements: { settlement: FeeSettlement; rates: FeeRatePair }[];
  exchangeTimeMs: number | null;
  receivedMs: number | null;
  /** Why the latest read failed; the rates shown are then from an earlier read. */
  error: string | null;
}

const RATE = /^-?(?:0|[1-9][0-9]{0,35})(?:\.[0-9]{1,36})?$/;
const SETTLEMENTS: readonly FeeSettlement[] = ["usdtMargined", "coinMargined"];

function rate(value: unknown): string | null {
  return typeof value === "string" && RATE.test(value) ? value : null;
}

/** The fee-rate estimate in an account state, or null if it was never read. */
export function feeRateEstimate(snapshots: AccountStatus["snapshots"]): FeeRateEstimate | null {
  const saved = snapshots.fee_rates;
  const state = snapshots.fee_rates_state?.data;
  const error = record(state) && typeof state.error === "string" ? state.error : null;
  const rates = record(saved?.data) && record(saved.data.rates) ? saved.data.rates : null;
  if (!rates && !error) return null;
  return {
    tier: typeof rates?.tier === "string" ? rates.tier : null,
    settlements: SETTLEMENTS.flatMap((settlement) => {
      const pair = rates?.[settlement];
      return record(pair) ? [{ settlement, rates: { maker: rate(pair.maker), taker: rate(pair.taker) } }] : [];
    }),
    exchangeTimeMs: typeof rates?.exchangeTimeMs === "number" && Number.isSafeInteger(rates.exchangeTimeMs) ? rates.exchangeTimeMs : null,
    receivedMs: rates ? saved?.receivedMs ?? null : null,
    error,
  };
}

/** "0.045%"; a rebate is returned as its positive size with `rebate` set. */
export function formatFeeRate(value: string, locale: string): { text: string; rebate: boolean } {
  const number = Number(value);
  const text = new Intl.NumberFormat(locale, { style: "percent", minimumFractionDigits: 3, maximumFractionDigits: 4 })
    .format(Math.abs(number));
  return { text, rebate: number < 0 };
}
