import { useEffect, useMemo, useState, useSyncExternalStore } from "react";
import type { ExternalMarkerSource } from "../../chart-adapter/externalMarkerSource.js";
import {
  createPriceLineSource,
  type ExternalPriceLineSource,
} from "../../chart-adapter/externalPriceLineSource.js";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import { parseIntervalSeconds } from "../../utils/intervals.js";
import type { SeriesWindowStore } from "../market-data/window/seriesWindowStore.js";
import { liveFillLegs, positionPriceLines, type PositionLineKind } from "./liveChartOverlay.js";
import { createReplayMarkerSource } from "./replayMarkerSource.js";
import { tradingAccountsStore } from "./tradingAccountsStore.js";
import { formatQty, tokenColor } from "./tradingFormat.js";

export interface TradingChartOverlayInput {
  enabled: boolean;
  exchange: string;
  marketType: string;
  symbol: string;
  interval: string;
  seriesStore: SeriesWindowStore | null;
  upColor: string;
  downColor: string;
  /** Changes when the theme does, so token colors are read again. */
  themeKey: string;
}

export interface TradingChartOverlay {
  markerSource: ExternalMarkerSource;
  priceLineSource: ExternalPriceLineSource;
}

type LoadedRange = { firstSec: number; lastSec: number } | null;

/** First and last loaded bar; changes only when a bar is added or the window moves. */
function useLoadedRange(seriesStore: SeriesWindowStore | null): LoadedRange {
  const [range, setRange] = useState<LoadedRange>(null);
  useEffect(() => {
    if (!seriesStore) {
      setRange(null);
      return undefined;
    }
    let firstSec: number | null = null;
    let lastSec: number | null = null;
    const read = () => {
      const first = seriesStore.first();
      const last = seriesStore.last();
      const nextFirst = first ? Number(first.time) : null;
      const nextLast = last ? Number(last.time) : null;
      if (nextFirst === firstSec && nextLast === lastSec) return;
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

/**
 * Read-only overlay of the selected trading account on a live chart: its
 * fills on this instrument and the open position's entry, stop and target.
 * Data comes from the shared account store and refreshes with its polling.
 */
export function useTradingChartOverlay(input: TradingChartOverlayInput): TradingChartOverlay {
  const { enabled, exchange, marketType, symbol, interval, seriesStore, upColor, downColor, themeKey } = input;
  const locale = useLocale();
  const { summary, trades } = useSyncExternalStore(tradingAccountsStore.subscribe, tradingAccountsStore.getSnapshot);
  useEffect(() => (enabled ? tradingAccountsStore.retain() : undefined), [enabled]);
  const loaded = useLoadedRange(enabled ? seriesStore : null);

  const markerSource = useMemo(() => createReplayMarkerSource({
    up: upColor,
    down: downColor,
    note: upColor,
  }, "trading-live"), [downColor, upColor]);
  const priceLineSource = useMemo(() => createPriceLineSource(), []);

  useEffect(() => {
    const intervalSec = parseIntervalSeconds(interval);
    const instrument = { exchange, marketType, symbol };
    const legs = enabled && intervalSec ? liveFillLegs(trades, instrument, loaded, intervalSec) : [];
    markerSource.update({
      legs,
      notes: [],
      cursorSec: Number.POSITIVE_INFINITY,
      intervalSec: intervalSec ?? 60,
      lastVisibleSec: loaded?.lastSec ?? null,
      labels: { buy: t("trading.replay.buy"), sell: t("trading.replay.sell"), note: "" },
    });
  }, [enabled, exchange, interval, loaded, locale, marketType, markerSource, symbol, trades]);

  useEffect(() => {
    if (!enabled) {
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
  }, [enabled, exchange, locale, marketType, priceLineSource, summary, symbol, themeKey]);

  return useMemo(() => ({ markerSource, priceLineSource }), [markerSource, priceLineSource]);
}
