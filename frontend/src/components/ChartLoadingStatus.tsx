import type { ChartDataCommitMeta } from "../features/market-data/useChartDataRuntime.js";
import type { SeriesWindowView } from "../features/market-data/window/seriesWindowView.js";
import { hasCurrentDatasetOwnership } from "./singleChartPaneLifecycle.js";

export function ChartLoadingStatus({
  loading, text, datasetKey = null, dataMeta = null, seriesStore = null, paintedDatasetKey,
}: {
  loading: boolean;
  text: string;
  datasetKey?: string | null;
  dataMeta?: Pick<ChartDataCommitMeta, "optimistic" | "seriesKey"> | null;
  seriesStore?: Pick<SeriesWindowView, "seriesKey" | "barCount"> | null;
  paintedDatasetKey: string | null;
}) {
  if (!loading) return null;
  // A live tail may paint before initial history finishes. Keep that history
  // pending, but reveal only data already rendered for the current owner.
  const hasPaintedData = hasCurrentDatasetOwnership({ dataMeta, datasetKey, seriesStore })
    && paintedDatasetKey === datasetKey && (seriesStore?.barCount ?? 0) > 0;
  return (
    <div className={hasPaintedData ? "loading-overlay loading-overlay--partial" : "loading-overlay"} role="status">
      <div className="loading-spinner" aria-hidden="true" />
      <span className="loading-text">{text}</span>
    </div>
  );
}
