import { nativeApi, nativeTimeframe } from "./nativeBacktestApi.js";
import { parsePineCurrencyRates } from "../../indicators/pineCurrencyModel.js";
import { workbenchAccountInputs, type WorkbenchAccountDraft, type WorkbenchAccountPayload } from "./workbenchAccountInputs.js";

type WorkbenchOptions = { language?: "pine" | "pyne"; account?: WorkbenchAccountDraft; accountData?: unknown; costSensitivityMode?: "AUTO" | "SKIP" };
function hostOptions(fidelity: string, callbacks: boolean, options: WorkbenchOptions = {}) {
  const fill = callbacks && (options.language !== "pyne" || fidelity !== "BAR_APPROX");
  const account = workbenchAccountInputs(options.account, options.accountData);
  if (Object.keys(account).length && (options.language === "pyne" || fidelity !== "BAR_APPROX" || !fill))
    throw new Error("V2 account/capacity requires Pine historical BAR fill callbacks");
  return { fill_recalculation: fill, ...account,
    ...(options.language !== "pyne" && options.costSensitivityMode ? { cost_sensitivity_mode: options.costSensitivityMode } : {}) };
}

export interface InputDataset {
  dataset_id: string; data_epoch: string; name: string; symbol: string; interval: string;
  first_open_ms: number; last_close_ms: number;
  exchange?: string; market_type?: string;
}
export interface ContextChoice { dataset: InputDataset; symbol: string; marketType?: string; priceTickSize?: string; currency?: string; quantityPrecision?: string }
export interface AdvancedInputs { contexts: ContextChoice[]; magnifier: InputDataset | null; libraries: string; priceTickSize?: string; currency?: string; currencyRates?: string; quantityPrecision?: string }
export const emptyAdvancedInputs = (): AdvancedInputs => ({ contexts: [], magnifier: null, libraries: "{}" });

export function restoreAdvancedInputs(value: unknown, strictContexts = false): AdvancedInputs {
  if (!value || typeof value !== "object" || Array.isArray(value)) return emptyAdvancedInputs();
  const raw = value as Record<string, unknown>;
  if (strictContexts && raw.contexts !== undefined && (!Array.isArray(raw.contexts) || raw.contexts.length > 16))
    throw new Error("NATIVE_INPUT_INVALID: requested contexts must be an array of at most 16 choices");
  const dataset = (item: unknown): item is InputDataset => {
    if (!item || typeof item !== "object" || Array.isArray(item)) return false;
    const row = item as Record<string, unknown>;
    return ["dataset_id", "data_epoch", "name", "symbol", "interval"].every((key) => typeof row[key] === "string")
      && typeof row.first_open_ms === "number" && Number.isSafeInteger(row.first_open_ms)
      && typeof row.last_close_ms === "number" && Number.isSafeInteger(row.last_close_ms);
  };
  const contexts: ContextChoice[] = [];
  for (const candidate of (Array.isArray(raw.contexts) ? raw.contexts : []) as unknown[]) {
    if (contexts.length >= 16) break;
    if (!candidate || typeof candidate !== "object" || Array.isArray(candidate)) continue;
    const item = candidate as Record<string, unknown>;
    if (typeof item.symbol === "string" && dataset(item.dataset))
      contexts.push({ symbol: item.symbol, dataset: { ...item.dataset },
        ...Object.fromEntries(["marketType", "priceTickSize", "currency", "quantityPrecision"]
          .filter((key) => typeof (item as Record<string, unknown>)[key] === "string")
          .map((key) => [key, (item as Record<string, unknown>)[key]])) });
  }
  if (strictContexts && Array.isArray(raw.contexts) && (contexts.length !== raw.contexts.length
      || raw.contexts.some((item: Record<string, unknown>) => ["marketType", "priceTickSize", "currency", "quantityPrecision"]
        .some((key) => item[key] !== undefined && typeof item[key] !== "string"))))
    throw new Error("NATIVE_INPUT_INVALID: malformed requested context selection");
  return { contexts, magnifier: dataset(raw.magnifier) ? { ...raw.magnifier } : null,
    libraries: typeof raw.libraries === "string" ? raw.libraries : "{}",
    ...(typeof raw.priceTickSize === "string" ? { priceTickSize: raw.priceTickSize } : {}),
    ...(typeof raw.currency === "string" ? { currency: raw.currency } : {}),
    ...(typeof raw.currencyRates === "string" ? { currencyRates: raw.currencyRates } : {}),
    ...(typeof raw.quantityPrecision === "string" ? { quantityPrecision: raw.quantityPrecision } : {}),
  };
}
export interface MainRange { start_time_ms: number; end_time_ms: number; exchange: string; market_type: string }

async function freezeContextChoices(choices: ContextChoice[], main: Pick<MainRange, "exchange" | "market_type">,
  datasets: InputDataset[], api: typeof nativeApi, signal?: AbortSignal) {
  const keys = choices.map(({ dataset, symbol }) => `${symbol.trim()}@${nativeTimeframe(dataset.interval)}`);
  if (choices.length > 16 || new Set(keys).size !== keys.length || choices.some(({ symbol }) => !symbol.trim()))
    throw new Error("NATIVE_INPUT_INVALID: empty or duplicate requested context");
  return Promise.all(choices.map(async (choice) => {
    const current = datasets.find((item) => item.dataset_id === choice.dataset.dataset_id && item.data_epoch === choice.dataset.data_epoch);
    if (!current) throw new Error("DATA_SNAPSHOT_MISMATCH: selected additional dataset changed; select its revision again");
    const symbol = choice.symbol.trim();
    const exchange = symbol.includes(":") ? symbol.split(":")[0]!.toLowerCase() : current.exchange ?? main.exchange;
    const marketType = choice.marketType || current.market_type || main.market_type;
    if ((current.exchange && current.exchange.toLowerCase() !== exchange)
        || (current.market_type && current.market_type !== marketType))
      throw new Error("DATA_SNAPSHOT_MISMATCH: requested market differs from dataset provenance");
    const reference = { dataset_id: current.dataset_id, data_epoch: current.data_epoch, interval: current.interval,
      exchange, market_type: marketType, start_time_ms: current.first_open_ms, end_time_ms: current.last_close_ms };
    if ((choice.currency || choice.quantityPrecision) && !choice.priceTickSize)
      throw new Error("NATIVE_INPUT_INVALID: requested symbol metadata requires its actual price tick");
    if (choice.currency && !/^[A-Z]{1,20}$/.test(choice.currency))
      throw new Error("NATIVE_INPUT_INVALID: requested quote currency must be an uppercase code");
    if (choice.quantityPrecision && !/^[0-9]$/.test(choice.quantityPrecision))
      throw new Error("NATIVE_INPUT_INVALID: quantity precision must be 0..9");
    if (choice.priceTickSize && (!Number.isFinite(Number(choice.priceTickSize)) || Number(choice.priceTickSize) <= 0))
      throw new Error("NATIVE_INPUT_INVALID: requested price tick must be positive and finite");
    const metadata = choice.priceTickSize ? { priceTickSize: choice.priceTickSize,
      ...(choice.currency ? { currency: choice.currency } : {}),
      ...(choice.quantityPrecision ? { quantityPrecision: Number(choice.quantityPrecision) } : {}) } : undefined;
    const snapshot = await api<{ snapshot_hash: string }>("/datasets/snapshot", reference, undefined, signal);
    return { ...reference, snapshot_hash: snapshot.snapshot_hash, symbol, timeframe: nativeTimeframe(current.interval),
      ...(metadata ? { metadata } : {}) };
  }));
}

export async function freezePineChartContexts(choices: ContextChoice[], main: Pick<MainRange, "exchange" | "market_type">, api = nativeApi, signal?: AbortSignal) {
  if (!choices.length) return [];
  const { datasets } = await api<{ datasets: InputDataset[] }>("/datasets", undefined, undefined, signal);
  return freezeContextChoices(choices, main, datasets, api, signal);
}

export function automaticHostExecution(mode: "NATIVE" | "CANDLESCOPE", hostSettings: Record<string, number>, fidelity: string, fillRecalculation: boolean, executionData: unknown, options?: WorkbenchOptions) {
  if (mode === "NATIVE") return null;
  if ((fidelity !== "BAR_APPROX" && executionData !== null) || (fidelity !== "BAR_APPROX" && fidelity !== "TRADE_TAPE")) return undefined;
  try { return { execution_fidelity: fidelity, host_settings: hostSettings,
    ...hostOptions(fidelity, fillRecalculation, options) }; } catch { return undefined; }
}

export function executionInputs(mode: "NATIVE" | "CANDLESCOPE", hostSettings: Record<string, number>, fidelity: string, fillRecalculation: boolean, executionData: unknown, options?: WorkbenchOptions): WorkbenchAccountPayload & {
  host_settings?: Record<string, number>; execution_fidelity?: string; fill_recalculation?: boolean; execution_data?: unknown;
  cost_sensitivity_mode?: "AUTO" | "SKIP";
} {
  return mode === "NATIVE" ? {} : { host_settings: hostSettings, execution_fidelity: fidelity,
    ...hostOptions(fidelity, fillRecalculation, options),
    execution_data: fidelity === "BAR_APPROX" ? null : executionData };
}

export async function freezeAdvancedInputs(selection: AdvancedInputs, language: "pine" | "pyne", main: MainRange, api = nativeApi) {
  const rates = parsePineCurrencyRates(selection.currencyRates ?? "");
  if (selection.currency && (!/^[A-Z]{1,20}$/.test(selection.currency) || !selection.priceTickSize))
    throw new Error("NATIVE_INPUT_INVALID: quote currency requires an uppercase code and the actual price tick");
  if (selection.quantityPrecision && (!/^[0-9]$/.test(selection.quantityPrecision) || !selection.priceTickSize))
    throw new Error("NATIVE_INPUT_INVALID: quantity precision requires 0..9 and the actual price tick");
  if (language !== "pine" && selection.contexts.some((item) => item.priceTickSize || item.currency || item.quantityPrecision))
    throw new Error("NATIVE_INPUT_UNSUPPORTED: requested instrument metadata requires Pine");
  const currencyInputs = rates ? { currency_rates: rates } : {};
  const libraries: unknown = JSON.parse(selection.libraries);
  if (!libraries || typeof libraries !== "object" || Array.isArray(libraries)
      || Object.values(libraries).some((source) => typeof source !== "string")) {
    throw new Error("NATIVE_LIBRARIES_INVALID: expected an object mapping import paths to source text");
  }
  if (language !== "pine" && (selection.magnifier || Object.keys(libraries).length || rates || selection.currency)) {
    throw new Error("NATIVE_INPUT_UNSUPPORTED: libraries and magnifier require Pine");
  }
  const keys = selection.contexts.map(({ dataset, symbol }) => `${symbol.trim()}@${nativeTimeframe(dataset.interval)}`);
  if (new Set(keys).size !== keys.length || selection.contexts.some(({ symbol }) => !symbol.trim())) {
    throw new Error("NATIVE_INPUT_INVALID: empty or duplicate requested context");
  }
  if (!selection.contexts.length && !selection.magnifier) return { contexts: [], magnifier: null, libraries, ...currencyInputs };
  const { datasets } = await api<{ datasets: InputDataset[] }>("/datasets");
  const freeze = async (selected: InputDataset, magnifier = false) => {
    const current = datasets.find((item) => item.dataset_id === selected.dataset_id && item.data_epoch === selected.data_epoch);
    if (!current) throw new Error("DATA_SNAPSHOT_MISMATCH: selected additional dataset changed; select its revision again");
    const reference = { dataset_id: current.dataset_id, data_epoch: current.data_epoch, interval: current.interval,
      exchange: main.exchange, market_type: main.market_type,
      start_time_ms: magnifier ? main.start_time_ms : current.first_open_ms,
      end_time_ms: magnifier ? main.end_time_ms : current.last_close_ms };
    const snapshot = await api<{ snapshot_hash: string }>("/datasets/snapshot", reference);
    return { ...reference, snapshot_hash: snapshot.snapshot_hash };
  };
  const [contexts, magnifier] = await Promise.all([
    freezeContextChoices(selection.contexts, main, datasets, api),
    selection.magnifier ? freeze(selection.magnifier, true) : Promise.resolve(null),
  ]);
  return { contexts, magnifier, libraries, ...currencyInputs };
}
