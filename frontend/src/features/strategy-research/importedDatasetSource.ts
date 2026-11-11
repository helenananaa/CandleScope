import {
  ChartStrategyRunError,
  qualitySummaryFromImportedManifest,
  type ResearchRunSource,
} from "../backtest/chart-tester/chartStrategyRunRequest.js";
import type { ChartStrategyRunRequest } from "../backtest/chart-tester/chartStrategyTesterUiModel.js";
import { RESEARCH_SOURCE_SCHEMA } from "../research-data/researchDataTypes.js";
import type { ImportedDatasetSourceRefV1, ResearchSourceRefV1 } from "../research-data/researchDataTypes.js";
import type { LocalDatasetManifest } from "../local-data/localDataTypes.js";


type ImportedRangeSettings = Pick<ChartStrategyRunRequest["attachment"], "customRange" | "fidelityPreference">;

export function importedResearchRange(manifest: LocalDatasetManifest, attachment: ImportedRangeSettings) {
  const precise = attachment.fidelityPreference === "PRECISE";
  const trades = precise ? manifest.market_trade_input : undefined;
  if (precise && !trades) {
    throw new ChartStrategyRunError("FIDELITY_UNSUPPORTED", "Precise research requires imported market trades");
  }
  const first = trades?.coverage_start_ms ?? manifest.first_open_ms;
  const end = trades?.coverage_end_ms_exclusive ?? manifest.last_open_ms + 1;
  return { first, end, startMs: attachment.customRange?.startMs ?? first, endMs: attachment.customRange?.endMs ?? end };
}

export function importedResearchRunSource(
  manifest: LocalDatasetManifest,
  attachment: ImportedRangeSettings,
  interval = manifest.interval,
): Extract<ResearchRunSource, { kind: "IMPORTED_DATASET" }> {
  const { first, end, startMs: startTimeMs, endMs } = importedResearchRange(manifest, attachment);
  // Precise preview requests use an inclusive end. The editor and batch list
  // retain the declared exclusive boundary.
  const endTimeMs = endMs - (attachment.fidelityPreference === "PRECISE" ? 1 : 0);
  if (startTimeMs < first || endMs > end || startTimeMs >= endTimeMs) {
    throw new ChartStrategyRunError("DATA_COVERAGE_INCOMPLETE", "The selected dates exceed the imported data coverage",
      { next_step: "choose dates within the data coverage" });
  }
  return {
    kind: "IMPORTED_DATASET",
    datasetId: manifest.dataset_id,
    dataEpoch: manifest.data_epoch,
    interval,
    symbol: manifest.symbol,
    startTimeMs,
    endTimeMs,
    marketTradeInput: manifest.market_trade_input !== undefined,
    quality: qualitySummaryFromImportedManifest({
      rows: manifest.rows, excludedRangeCount: manifest.excluded_range_count, volumeAvailable: manifest.volume_available,
    }),
  };
}

export function importedDatasetSourceFromManifest(
  manifest: Pick<LocalDatasetManifest, "dataset_id" | "data_epoch" | "interval">,
  interval: string = manifest.interval,
): ImportedDatasetSourceRefV1 {
  return {
    schemaVersion: RESEARCH_SOURCE_SCHEMA,
    kind: "IMPORTED_DATASET",
    datasetId: manifest.dataset_id,
    dataEpoch: manifest.data_epoch,
    interval,
  };
}

export function importedChartDatasetKey(
  manifest: Pick<LocalDatasetManifest, "dataset_id" | "data_epoch">,
  interval: string,
): string {
  return `local:${manifest.dataset_id}:${manifest.data_epoch}:${interval}`;
}

export function importedDrawingKeyBase(
  manifest: Pick<LocalDatasetManifest, "dataset_id" | "data_epoch">,
): string {
  return `local:${manifest.dataset_id}:${manifest.data_epoch}`;
}

export function preferredLibrarySelectedId(
  source: ResearchSourceRefV1 | null,
  datasets: ReadonlyArray<Pick<LocalDatasetManifest, "dataset_id">>,
): string | null {
  if (source?.kind === "IMPORTED_DATASET") {
    const match = datasets.find((dataset) => dataset.dataset_id === source.datasetId);
    if (match !== undefined) return match.dataset_id;
  }
  return datasets[0]?.dataset_id ?? null;
}

export function importedManifestForSource(
  source: ResearchSourceRefV1 | null,
  selected: LocalDatasetManifest | null,
): LocalDatasetManifest | null {
  if (source?.kind !== "IMPORTED_DATASET" || selected === null) return null;
  if (selected.dataset_id !== source.datasetId || selected.data_epoch !== source.dataEpoch) {
    return null;
  }
  return selected;
}

export function researchSourceIdentity(source: ResearchSourceRefV1 | null): string {
  if (source?.kind === "IMPORTED_DATASET") {
    return `imported:${source.datasetId}:${source.dataEpoch}`;
  }
  if (source?.kind === "CURRENT_CHART") {
    return `chart:${source.workspaceId}:${source.cellId}:${source.exchange}:${source.marketType}:${source.symbol}:${source.interval}`;
  }
  if (source?.kind === "COMPLETED_RUN") {
    return `run:${source.runId}`;
  }
  return "";
}
