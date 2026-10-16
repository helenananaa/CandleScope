import { useCallback, useMemo, useSyncExternalStore } from "react";
import { useLocale } from "../../i18n/useLocale.js";
import { replayIndicatorPresentation } from "./replayIndicatorPresentation.js";
import type { ActiveIndicatorPersistence } from "../indicators/activeIndicatorStore.js";
import type { IndicatorDefinition } from "../indicators/indicatorTypes.js";
import { clearProvidedBarsIndicatorRuntimeFields, useProvidedBarsIndicatorRuntime } from "../indicators/useProvidedBarsIndicatorRuntime.js";
import type { KlineBar } from "../market-data/marketDataTypes.js";
import type { SeriesWindowStore } from "../market-data/window/seriesWindowStore.js";
import { useReplayCanonicalIndicatorCompute } from "./useReplayCanonicalIndicatorCompute.js";
import type { ReplayCanonicalBinding } from "./replayCanonicalIndicators.js";
import { excludeIncompleteReplayHistory, selectRevealedIndicatorBars } from "./useReplaySharedIndicatorRuntime.js";

/** Review may reuse study definitions, never the current training's outputs or storage. */
export function reviewIndicatorPersistence(definitions: readonly IndicatorDefinition[]): ActiveIndicatorPersistence {
  const inputs = definitions.map(clearProvidedBarsIndicatorRuntimeFields);
  return { controlled: true, load: () => inputs, save: () => undefined };
}

export function reviewIndicatorBars(rows: readonly KlineBar[], requestedKey: string | null,
  loadedKey: string | null, cursorMs: number | null): KlineBar[] {
  if (requestedKey === null || loadedKey !== requestedKey || cursorMs === null) return [];
  // A bounded source window can start mid-bucket (7m, 90m, calendar periods).
  // Its incomplete historical bucket is a gap, not an unclosed live tail.
  // Do not invent its missing components or let it reject all later history.
  // selectRevealedIndicatorBars resets state across the resulting gap and
  // continues enforcing finality, ordering and the selected-event boundary.
  const completeHistory = excludeIncompleteReplayHistory(rows, cursorMs);
  return selectRevealedIndicatorBars(completeHistory, cursorMs);
}

export function useReplayReviewIndicators({ seriesStore, requestedKey, loadedKey, cursorMs,
  definitions, exchange, marketType, symbol, interval, sourceBinding }: {
  seriesStore: SeriesWindowStore;
  requestedKey: string | null;
  loadedKey: string | null;
  cursorMs: number | null;
  definitions: readonly IndicatorDefinition[];
  exchange: string;
  marketType: string;
  symbol: string;
  interval: string;
  sourceBinding: ReplayCanonicalBinding | null;
}) {
  const locale = useLocale();
  const subscribe = useCallback((listener: () => void) => seriesStore.subscribe(listener), [seriesStore]);
  const getRevision = useCallback(() => Number(seriesStore.version), [seriesStore]);
  const revision = useSyncExternalStore(subscribe, getRevision, getRevision);
  const ready = requestedKey !== null && loadedKey === requestedKey;
  const bars = useMemo(() => {
    void revision;
    return reviewIndicatorBars(seriesStore.snapshot(), requestedKey, loadedKey, cursorMs);
  }, [seriesStore, revision, requestedKey, loadedKey, cursorMs]);
  const persistence = useMemo(() => reviewIndicatorPersistence(ready ? definitions : []), [definitions, ready]);
  const canonical = useReplayCanonicalIndicatorCompute(requestedKey ?? "review-inactive", seriesStore,
    ready ? sourceBinding : null);
  const computeBatch = canonical.compute;
  const meta = useMemo(() => ({ version: revision, status: "ready", committedAt: null,
    source: "replay-indicator-revealed-prefix" }), [revision]);
  const outputBarTimes = useMemo(() => bars.map(bar => bar.time), [bars]);
  const runtime = useProvidedBarsIndicatorRuntime({ bars, outputBarTimes, computeBatch, chartDataMeta: meta, persistence,
    datasetKey: `${requestedKey ?? "review-inactive"}|${canonical.sourceKey}`,
    sourceScopeKey: `${requestedKey ?? "review-inactive"}|${canonical.sourceKey}`,
    sourceOrdinal: cursorMs ?? -1, visibleThroughSeconds: cursorMs === null ? null : cursorMs / 1_000,
    seriesReady: revision, exchange, marketType, symbol, interval });
  const presentation = useMemo(() => {
    void locale;
    return replayIndicatorPresentation(runtime.view, canonical.preparation, runtime.status.computing);
  }, [runtime.view, runtime.status.computing, canonical.preparation, locale]);
  return { ...runtime, view: presentation.view, status: { ...runtime.status,
    computing: runtime.status.computing || canonical.preparation.active > 0, preparationText: presentation.statusText } };
}
