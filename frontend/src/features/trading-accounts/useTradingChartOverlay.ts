import { useEffect, useLayoutEffect, useMemo, useState, useSyncExternalStore } from "react";
import type { ExternalMarkerSource } from "../../chart-adapter/externalMarkerSource.js";
import {
  createPriceLineSource,
  type ExternalPriceLineSource,
} from "../../chart-adapter/externalPriceLineSource.js";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import { parseIntervalSeconds } from "../../utils/intervals.js";
import { floorIntervalTime } from "../../utils/intervalTimeline.js";
import type { SeriesWindowView } from "../market-data/window/seriesWindowView.js";
import { liveFillLegs, liveJournalEntries, positionPriceLines, MAX_LIVE_FILL_MARKERS, type PositionLineKind } from "./liveChartOverlay.js";
import { normalizeChartAccountOverlay, type ChartAccountOverlaySettings } from "../chart-workspace/chartAccountOverlaySettings.js";
import { tradingAccountDataPool, type TradingAccountDataState } from "./tradingAccountDataPool.js";
import { createReplayMarkerSource } from "./replayMarkerSource.js";
import { tradingAccountsStore } from "./tradingAccountsStore.js";
import { formatQty, tokenColor } from "./tradingFormat.js";

export interface TradingChartOverlayInput {
  enabled: boolean;
  settings?: ChartAccountOverlaySettings;
  exchange: string;
  marketType: string;
  symbol: string;
  interval: string;
  seriesStore: SeriesWindowView | null;
  upColor: string;
  downColor: string;
  /** Changes when the theme does, so token colors are read again. */
  themeKey: string;
}

export interface TradingChartOverlay {
  markerSource: ExternalMarkerSource;
  priceLineSource: ExternalPriceLineSource;
  error: string | null;
}

type LoadedRange = { firstSec: number; lastSec: number } | null;

/** First and last loaded bar; changes only when a bar is added or the window moves. */
function useLoadedRange(seriesStore: SeriesWindowView | null): LoadedRange {
  const [range, setRange] = useState<LoadedRange>(null);
  useEffect(() => {
    if (!seriesStore) {
      setRange(null);
      return undefined;
    }
    let firstSec: number | null = null;
    let lastSec: number | null = null;
    let axisRevision: number | null = null;
    const read = () => {
      const first = seriesStore.first();
      const last = seriesStore.last();
      const nextFirst = first ? Number(first.time) : null;
      const nextLast = last ? Number(last.time) : null;
      if (nextFirst === firstSec && nextLast === lastSec && seriesStore.axisRevision === axisRevision) return;
      axisRevision = seriesStore.axisRevision;
      firstSec = nextFirst;
      lastSec = nextLast;
      setRange(nextFirst !== null && nextLast !== null ? { firstSec: nextFirst, lastSec: nextLast } : null);
    };
    read();
    const unsubscribe = seriesStore.subscribe(read);
    return () => { unsubscribe(); };
  }, [seriesStore]);
  return range;
}

const LABEL_KEYS = {
  long: "trading.chart.long",
  short: "trading.chart.short",
  stopLoss: "trading.chart.stopLoss",
  takeProfit: "trading.chart.takeProfit",
} as const satisfies Record<PositionLineKind, string>;

const EMPTY_ACCOUNT: TradingAccountDataState = { accountId: "", summary: null, trades: [], entries: [], loading: false, error: null };
const noSubscribe = () => () => {};
const emptyAccount = () => EMPTY_ACCOUNT;

/**
 * Read-only overlay of the selected trading account on a live chart: its
 * fills on this instrument and the open position's entry, stop and target.
 * Data comes from the retained account owner and its committed state stream.
 */
export function useTradingChartOverlay(input: TradingChartOverlayInput): TradingChartOverlay {
  const { enabled, exchange, marketType, symbol, interval, seriesStore, upColor, downColor, themeKey } = input;
  const locale = useLocale();
  const settings = normalizeChartAccountOverlay(input.settings);
  const needsAccount = enabled && (settings.trades || settings.positions || settings.notes);
  const followsPanel = settings.accountId === null;
  const selected = useSyncExternalStore(tradingAccountsStore.subscribe, tradingAccountsStore.getSnapshot).selected;
  useEffect(() => (needsAccount && followsPanel ? tradingAccountsStore.retain() : undefined), [needsAccount, followsPanel]);
  const accountId = settings.accountId ?? selected?.id ?? null;
  const data = useMemo(() => needsAccount && accountId ? tradingAccountDataPool.account(accountId) : null, [accountId, needsAccount]);
  const { summary, trades, entries, error } = useSyncExternalStore(data?.subscribe ?? noSubscribe, data?.getSnapshot ?? emptyAccount);
  useEffect(() => data?.retain(), [data]);
  const loaded = useLoadedRange(enabled ? seriesStore : null);

  const markerSource = useMemo(() => createReplayMarkerSource({
    up: upColor,
    down: downColor,
    note: upColor,
  }, "trading-live"), [downColor, upColor]);
  const priceLineSource = useMemo(() => createPriceLineSource(), []);

  useLayoutEffect(() => {
    const intervalSec = parseIntervalSeconds(interval);
    const instrument = { exchange, marketType, symbol };
    const bucketTime = (time: number) => {
      const bucket = floorIntervalTime(interval, time);
      return bucket !== null && seriesStore?.hasTime(bucket) ? bucket : null;
    };
    const legs = enabled && settings.trades && intervalSec
      ? liveFillLegs(trades, instrument, loaded, intervalSec, MAX_LIVE_FILL_MARKERS, bucketTime) : [];
    const notes = enabled && settings.notes ? liveJournalEntries(entries, instrument, bucketTime) : [];
    markerSource.update({
      legs,
      notes,
      cursorSec: Number.POSITIVE_INFINITY,
      intervalSec: intervalSec ?? 60,
      bucketTime,
      lastVisibleSec: loaded?.lastSec ?? null,
      labels: { buy: t("trading.replay.buy"), sell: t("trading.replay.sell"), note: t("trading.note"), reviewNote: t("trading.journal.reviewNote") },
    });
  }, [enabled, entries, exchange, interval, loaded, locale, marketType, markerSource, seriesStore, settings.notes, settings.trades, symbol, trades]);

  useLayoutEffect(() => {
    if (!enabled || !settings.positions) {
      priceLineSource.setLines([]);
      return;
    }
    const colors = {
      entry: tokenColor("--accent-blue", "royalblue"),
      stopLoss: tokenColor("--color-danger", "crimson"),
      takeProfit: tokenColor("--color-success", "seagreen"),
    };
    priceLineSource.setLines(positionPriceLines(
      summary,
      { exchange, marketType, symbol },
      colors,
      (kind, qty) => t(LABEL_KEYS[kind], { qty: formatQty(qty) }),
    ));
  }, [enabled, exchange, locale, marketType, priceLineSource, settings.positions, summary, symbol, themeKey]);

  return useMemo(() => ({ markerSource, priceLineSource, error }), [markerSource, priceLineSource, error]);
}
