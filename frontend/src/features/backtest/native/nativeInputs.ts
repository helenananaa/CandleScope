import { nativeApi, nativeTimeframe } from "./nativeBacktestApi.js";

export interface InputDataset {
  dataset_id: string; data_epoch: string; name: string; symbol: string; interval: string;
  first_open_ms: number; last_close_ms: number;
}
export interface ContextChoice { dataset: InputDataset; symbol: string }
export interface AdvancedInputs { contexts: ContextChoice[]; magnifier: InputDataset | null; libraries: string }
export const emptyAdvancedInputs = (): AdvancedInputs => ({ contexts: [], magnifier: null, libraries: "{}" });
export interface MainRange { start_time_ms: number; end_time_ms: number; exchange: string; market_type: string }

export function executionInputs(mode: "NATIVE" | "CANDLESCOPE", hostSettings: Record<string, number>, fidelity: string, fillRecalculation: boolean, executionData: unknown) {
  return mode === "NATIVE" ? {} : { host_settings: hostSettings, execution_fidelity: fidelity,
    fill_recalculation: fidelity !== "BAR_APPROX" && fillRecalculation,
    execution_data: fidelity === "BAR_APPROX" ? null : executionData };
}

export async function freezeAdvancedInputs(selection: AdvancedInputs, language: "pine" | "pyne", main: MainRange, api = nativeApi) {
  const libraries: unknown = JSON.parse(selection.libraries);
  if (!libraries || typeof libraries !== "object" || Array.isArray(libraries)
      || Object.values(libraries).some((source) => typeof source !== "string")) {
    throw new Error("NATIVE_LIBRARIES_INVALID: expected an object mapping import paths to source text");
  }
  if (language !== "pine" && (selection.magnifier || Object.keys(libraries).length)) {
    throw new Error("NATIVE_INPUT_UNSUPPORTED: libraries and magnifier require Pine");
  }
  const keys = selection.contexts.map(({ dataset, symbol }) => `${symbol.trim()}@${nativeTimeframe(dataset.interval)}`);
  if (new Set(keys).size !== keys.length || selection.contexts.some(({ symbol }) => !symbol.trim())) {
    throw new Error("NATIVE_INPUT_INVALID: empty or duplicate requested context");
  }
  if (!selection.contexts.length && !selection.magnifier) return { contexts: [], magnifier: null, libraries };
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
    Promise.all(selection.contexts.map(async ({ dataset, symbol }) => ({ ...await freeze(dataset),
      symbol: symbol.trim(), timeframe: nativeTimeframe(dataset.interval) }))),
    selection.magnifier ? freeze(selection.magnifier, true) : Promise.resolve(null),
  ]);
  return { contexts, magnifier, libraries };
}
