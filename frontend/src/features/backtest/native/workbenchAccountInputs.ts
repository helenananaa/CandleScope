import { t } from "../../../i18n/index.js";

export interface WorkbenchAccountDraft {
  accountModel: string; leverage: number; fundingMode: string;
  participationEnabled: boolean; participationRate: number; uploaded: boolean;
}
export type AccountInputState = "ready" | "loading" | "invalid" | "missing";
export const defaultWorkbenchAccount = (): WorkbenchAccountDraft => ({
  accountModel: "AUTO", leverage: 10, fundingMode: "OFF", participationEnabled: false, participationRate: .1, uploaded: false,
});
export function restoreWorkbenchAccount(value: unknown): WorkbenchAccountDraft {
  const defaults = defaultWorkbenchAccount();
  if (!value || typeof value !== "object" || Array.isArray(value)) return { ...defaults, accountModel: "INVALID" };
  const row = value as Record<string, unknown>;
  return { accountModel: typeof row.accountModel === "string" ? row.accountModel : "INVALID",
    leverage: typeof row.leverage === "number" && Number.isFinite(row.leverage) ? row.leverage : 0,
    fundingMode: typeof row.fundingMode === "string" ? row.fundingMode : "INVALID",
    participationEnabled: row.participationEnabled === true,
    participationRate: typeof row.participationRate === "number" && Number.isFinite(row.participationRate) ? row.participationRate : 0,
    uploaded: row.uploaded === true };
}
export interface FrozenAccountData {
  symbol: string; events: { time_ms: number; role: string; payload: Record<string, unknown> }[];
  provenance?: Record<string, unknown>;
}
const object = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
export function parseAccountData(text: string): FrozenAccountData {
  const value: unknown = JSON.parse(text);
  if (!object(value) || typeof value.symbol !== "string" || !value.symbol.trim()
    || !Array.isArray(value.events) || !value.events.length || value.events.length > 500000
    || (value.provenance !== undefined && !object(value.provenance))) throw new Error(t("native.account.invalidData"));
  let previous = -Infinity;
  for (const row of value.events) {
    if (!object(row) || !Number.isSafeInteger(row.time_ms) || (row.time_ms as number) < previous
      || !["INSTRUMENT_RULES", "MARK_INDEX", "FUNDING"].includes(String(row.role)) || !object(row.payload))
      throw new Error(t("native.account.invalidData"));
    previous = row.time_ms as number;
  }
  return value as unknown as FrozenAccountData;
}
export interface WorkbenchAccountPayload {
  account_model?: string; leverage?: number; funding_mode?: string; account_data?: unknown;
  execution_model_revision?: string; participation_rate?: number; bar_path_scenario?: string;
}
export function workbenchAccountInputs(draft?: WorkbenchAccountDraft, data?: unknown, fidelity = "BAR_APPROX"): WorkbenchAccountPayload {
  if (!draft) return {};
  if (!["AUTO", "LINEAR_PERP_ONE_WAY_V2"].includes(draft.accountModel)) throw new Error(t("native.account.invalidSettings"));
  const result: WorkbenchAccountPayload = {};
  if (draft.accountModel === "LINEAR_PERP_ONE_WAY_V2") {
    if (!Number.isFinite(draft.leverage) || draft.leverage <= 0 || draft.leverage > 1000
      || !["OFF", "HISTORICAL_REQUIRED"].includes(draft.fundingMode)) throw new Error(t("native.account.invalidSettings"));
    if (!data) throw new Error(t("native.account.dataRequired"));
    Object.assign(result, { account_model: draft.accountModel, leverage: draft.leverage,
      funding_mode: draft.fundingMode, account_data: data });
  }
  if (draft.participationEnabled) {
    if (!Number.isFinite(draft.participationRate) || draft.participationRate <= 0 || draft.participationRate > 1)
      throw new Error(t("native.account.invalidSettings"));
    Object.assign(result, { execution_model_revision: "EXECUTION_REALISM_V2", participation_rate: draft.participationRate,
      ...(fidelity === "BAR_APPROX" ? { bar_path_scenario: "OHLC_NEAREST_EXTREME_PATH_V2" } : {}) });
  }
  if (Object.keys(result).length && fidelity !== "BAR_APPROX") {
    if (result.account_model !== "LINEAR_PERP_ONE_WAY_V2" || !["TRADE_TAPE", "BOOK_ASSISTED", "BOOK_DEPTH", "BOOK_SAMPLED"].includes(fidelity))
      throw new Error(t("native.account.barRequired"));
    if (draft.participationEnabled && fidelity !== "TRADE_TAPE")
      throw new Error(t("native.account.bookCapacity"));
  }
  return result;
}
export function workbenchAccountError(draft: WorkbenchAccountDraft, data: unknown, state: AccountInputState,
  language: string, fidelity: string, callbacks: boolean, marketType?: string): string {
  try {
    if (draft.accountModel === "LINEAR_PERP_ONE_WAY_V2" && state !== "ready")
      return t(state === "missing" ? "native.account.uploadMissing" : state === "loading" ? "native.account.loading" : "native.account.invalidData");
    const inputs = workbenchAccountInputs(draft, data, fidelity);
    if (Object.keys(inputs).length && (language !== "pine" || (fidelity === "BAR_APPROX" && !callbacks)))
      return t("native.account.barRequired");
    if (draft.accountModel === "LINEAR_PERP_ONE_WAY_V2") {
      if (marketType === "spot") return t("native.account.perpRequired");
    }
    return "";
  } catch (error) { return error instanceof Error ? error.message : String(error); }
}
