import { restoreWorkbenchAccount, workbenchAccountInputs, type WorkbenchAccountDraft } from "./workbenchAccountInputs.js";

export type NativeHostSettings = {
  initial_balance: number; slippage_bps: number; taker_fee_bps: number; price_tick: number;
};
export interface NativeExecutionDraft {
  hostSettings: NativeHostSettings; fidelity: string; fillRecalculation: boolean; uploaded: boolean;
  account?: WorkbenchAccountDraft;
  costSensitivityMode?: "AUTO" | "SKIP";
}
const fidelities = new Set(["BAR_APPROX", "TRADE_TAPE", "BOOK_ASSISTED", "BOOK_DEPTH", "BOOK_SAMPLED"]);
export function defaultExecutionDraft(): NativeExecutionDraft {
  return { hostSettings: { initial_balance: 10000, slippage_bps: 1, taker_fee_bps: 0, price_tick: 0.01 },
    fidelity: "BAR_APPROX", fillRecalculation: false, uploaded: false };
}
export function restoreExecutionDraft(serialized?: string): NativeExecutionDraft {
  const defaults = defaultExecutionDraft();
  try {
    const value: unknown = JSON.parse(serialized ?? "null");
    if (!value || typeof value !== "object") return defaults;
    const draft = value as Record<string, unknown>;
    const settings = draft.hostSettings && typeof draft.hostSettings === "object" ? draft.hostSettings as Record<string, unknown> : {};
    for (const field of Object.keys(defaults.hostSettings) as Array<keyof NativeHostSettings>) {
      const candidate = settings[field];
      // Keep finite unfinished inputs (including zero). Validation must reject
      // them explicitly, not silently replace the user's amount on restart.
      if (typeof candidate === "number" && Number.isFinite(candidate)) defaults.hostSettings[field] = candidate;
    }
    if (typeof draft.fidelity === "string" && fidelities.has(draft.fidelity)) defaults.fidelity = draft.fidelity;
    defaults.fillRecalculation = draft.fillRecalculation === true;
    if (draft.costSensitivityMode === "AUTO" || draft.costSensitivityMode === "SKIP") defaults.costSensitivityMode = draft.costSensitivityMode;
    defaults.uploaded = draft.uploaded === true;
    if (draft.account !== undefined) defaults.account = restoreWorkbenchAccount(draft.account);
    return defaults;
  } catch { return defaults; }
}

/** Compare JSON values without serializing large event tapes on every render. */
export function sameExecutionData(left: unknown, right: unknown): boolean {
  const normalize = (value: unknown) => value && typeof value === "object" && "events" in value
    ? { provenance: {}, ...value } : value;
  return sameJson(normalize(left), normalize(right));
}
function sameJson(left: unknown, right: unknown, depth = 0): boolean {
  if (left === right || (left == null && right == null)) return true;
  if (depth > 64) return false;
  if (!left || !right || typeof left !== "object" || typeof right !== "object") return false;
  if (Array.isArray(left) || Array.isArray(right)) {
    return Array.isArray(left) && Array.isArray(right) && left.length === right.length
      && left.every((item, index) => sameJson(item, right[index], depth + 1));
  }
  const a = left as Record<string, unknown>, b = right as Record<string, unknown>;
  const keys = Object.keys(a);
  return keys.length === Object.keys(b).length
    && keys.every((key) => Object.hasOwn(b, key) && sameJson(a[key], b[key], depth + 1));
}
export type FrozenExecutionSettings = {
  cost_sensitivity_mode?: "AUTO" | "SKIP";
  dataset_id?: string;
  data_epoch?: string;
  execution_fidelity?: string;
  host_settings?: Record<string, number | null>;
  fill_recalculation?: boolean;
  execution_data?: unknown;
  account_model?: string | null; leverage?: number; funding_mode?: string;
  execution_model_revision?: string | null; participation_rate?: number | null; bar_path_scenario?: string | null;
  account_data?: unknown;
};
export function datasetIdentityChanged(
  config: Pick<FrozenExecutionSettings, "dataset_id" | "data_epoch"> | undefined,
  current: { datasetId: string; dataEpoch: string } | undefined,
): boolean {
  return current !== undefined
    && (config?.dataset_id !== current.datasetId || config?.data_epoch !== current.dataEpoch);
}
export function executionSettingsChanged(config: FrozenExecutionSettings, current: NativeExecutionDraft, dataMatches: boolean, accountMatches = true): boolean {
  if ((config.cost_sensitivity_mode ?? "AUTO") !== (current.costSensitivityMode ?? "AUTO")) return true;
  if ((config.execution_fidelity ?? "BAR_APPROX") !== current.fidelity) return true;
  const settings = config.host_settings;
  if (!settings || (Object.keys(current.hostSettings) as Array<keyof NativeHostSettings>)
    .some((field) => settings[field] !== current.hostSettings[field])) return true;
  if ((config.fill_recalculation ?? false) !== current.fillRecalculation) return true;
  try {
    const desired = workbenchAccountInputs(current.account, current.account?.accountModel === "LINEAR_PERP_ONE_WAY_V2" ? {} : undefined, current.fidelity);
    for (const key of ["account_model", "execution_model_revision", "participation_rate", "bar_path_scenario"] as const) {
      const actual = key === "account_model" && config[key] !== "LINEAR_PERP_ONE_WAY_V2" ? undefined : config[key] ?? undefined;
      if (actual !== desired[key]) return true;
    }
    if ((config.leverage ?? 1) !== (desired.leverage ?? 1) || (config.funding_mode ?? "OFF") !== (desired.funding_mode ?? "OFF")) return true;
    if (desired.account_model && !accountMatches) return true;
  } catch { return true; }
  return current.fidelity !== "BAR_APPROX" && !dataMatches;
}
