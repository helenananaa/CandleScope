import { snapshotDeliveryLabel } from "./orderBookDelivery.js";
import React, {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { t, getDateTimeLocale } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import type {
  FullOutputLimit,
  OrderBookConnectionStatus,
  OrderBookRuntime,
  OrderBookUpdateIntervalMs,
  PartialDepthLevel,
  PriceGrouping,
} from "./orderBookTypes.js";
import {
  groupingPriceStep,
  orderBookPresentation,
} from "./orderBookAggregation.js";
import { buildOrderBookRows } from "./orderBookRows.js";
import type { DisplayOrderBookLevel } from "./orderBookRows.js";
import { fixedRowWindow } from "./orderBookVirtualization.js";
import { Button } from "../../components/ui/Button.js";
import { EmptyState as SharedEmptyState } from "../../components/ui/EmptyState.js";
import { Icon } from "../../components/icons/Icon.js";
import {
  FULL_OUTPUT_LIMITS,
  FULL_PRICE_GROUPINGS,
  PARTIAL_DEPTH_LEVELS,
  PARTIAL_PRICE_GROUPINGS,
} from "./orderBookTypes.js";

export interface OrderBookDockProps {
  runtime: OrderBookRuntime;
  height: number;
  /** Collapses this rail accordion view. */
  onRequestClose?(): void;
}

const ORDER_BOOK_STATUS_KEYS = {
  idle: "orderBook.status.idle",
  unsupported: "orderBook.status.unsupported",
  connecting: "orderBook.status.connecting",
  reconnecting: "orderBook.status.reconnecting",
  live: "orderBook.status.live",
  stale: "orderBook.status.stale",
  error: "orderBook.status.error",
} as const satisfies Record<OrderBookConnectionStatus, string>;

function orderBookStatusLabel(status: OrderBookConnectionStatus): string {
  return t(ORDER_BOOK_STATUS_KEYS[status]);
}


function orderBookStatusDetail(
  status: OrderBookConnectionStatus,
  hostMessage: string | null = null,
): string {
  if (hostMessage?.trim()) return hostMessage;
  if (status === "unsupported" || status === "idle") {
    return hostMessage || t("orderBook.waitingBook");
  }
  if (status === "stale") return t("orderBook.rt.staleSnapshot");
  if (status === "reconnecting") return t("orderBook.rt.disconnected");
  if (status === "error") return t("orderBook.rt.unavailable");
  return t("orderBook.waitingBook");
}

function trimZeros(value: string): string {
  return value.includes(".") ? value.replace(/\.?0+$/, "") : value;
}

function formatPrice(value: number | null): string {
  if (value === null || !Number.isFinite(value)) return "—";
  const decimals = value >= 1_000 ? 2 : value >= 1 ? 4 : value >= 0.01 ? 6 : 8;
  return trimZeros(value.toFixed(decimals));
}

function formatQuantity(value: number): string {
  if (value >= 1_000_000) return `${trimZeros((value / 1_000_000).toFixed(2))}M`;
  if (value >= 1_000) return `${trimZeros((value / 1_000).toFixed(2))}K`;
  if (value >= 1) return trimZeros(value.toFixed(4));
  return trimZeros(value.toFixed(6));
}

function formatSpread(value: number | null, bps: number | null): string {
  if (value === null) return t("orderBook.waitingSpread");
  return `${formatPrice(value)}${bps === null ? "" : `  ·  ${trimZeros(bps.toFixed(2))} bps`}`;
}

function groupingLabel(
  grouping: PriceGrouping,
  runtimeMode: "partial" | "full",
  book: Parameters<typeof groupingPriceStep>[0],
): string {
  const step = groupingPriceStep(book, runtimeMode, grouping);
  if (grouping === "auto") {
    return step === null ? t("orderBook.grouping.auto") : t("orderBook.grouping.autoStep", { step: formatPrice(step) });
  }
  if (grouping === "raw") {
    return step === null ? t("orderBook.grouping.raw") : t("orderBook.grouping.rawStep", { step: formatPrice(step) });
  }
  return step === null ? `${grouping}×` : formatPrice(step);
}

const ORDER_BOOK_ROW_HEIGHT = 22;
const ORDER_BOOK_ROW_OVERSCAN = 4;

const BookRow = React.memo(function BookRow({
  row,
  side,
  maxCumulative,
  offsetPx,
}: {
  row: DisplayOrderBookLevel;
  side: "ask" | "bid";
  maxCumulative: number;
  offsetPx: number;
}) {
  useLocale();
  const width = maxCumulative > 0 ? Math.min(100, row.cumulative / maxCumulative * 100) : 0;
  return (
    <div className={`ob-level-row ob-${side}`} style={{ transform: `translateY(${offsetPx}px)` }}>
      <span className={`ob-depth-bar${row.cumulativeIncomplete ? " ob-depth-bar-partial" : ""}`} style={{ width: `${width}%` }} aria-hidden="true" />
      <span className="ob-price" title={row.interval ? t(
        side === "bid" ? "orderBook.bidPriceRange" : "orderBook.askPriceRange",
        { min: formatPrice(row.interval[0]), max: formatPrice(row.interval[1]) },
      ) : undefined}>
        {formatPrice(row.price)}
      </span>
      <span title={row.incomplete ? t("orderBook.partialAmount") : undefined}>{row.incomplete ? "≥ " : ""}{formatQuantity(row.quantity)}</span>
      <span title={row.cumulativeIncomplete ? t("orderBook.partialAmount") : undefined}>{row.cumulativeIncomplete ? "≥ " : ""}{formatQuantity(row.cumulative)}</span>
    </div>
  );
}, (previous, next) => (
  previous.side === next.side
  && previous.offsetPx === next.offsetPx
  && previous.maxCumulative === next.maxCumulative
  && previous.row.price === next.row.price
  && previous.row.quantity === next.row.quantity
  && previous.row.cumulative === next.row.cumulative
  && previous.row.interval?.[0] === next.row.interval?.[0]
  && previous.row.interval?.[1] === next.row.interval?.[1]
  && previous.row.incomplete === next.row.incomplete
  && previous.row.cumulativeIncomplete === next.row.cumulativeIncomplete
));

function BookLevels({
  rows,
  side,
  maxCumulative,
  onViewport,
}: {
  onViewport(side: "ask" | "bid", rows: number, browsing: boolean): void;
  rows: readonly DisplayOrderBookLevel[];
  side: "ask" | "bid";
  maxCumulative: number;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const frameRef = useRef<number | null>(null);
  const stickToEdgeRef = useRef(side === "ask");
  const [viewport, setViewport] = useState({ height: 0, scrollTop: 0 });
  const displayRows = useMemo(
    () => side === "ask" ? [...rows].reverse() : rows,
    [rows, side],
  );
  const requestedScrollTop = side === "ask" && viewport.height === 0
    ? Number.POSITIVE_INFINITY
    : viewport.scrollTop;
  const window = fixedRowWindow({
    rowCount: displayRows.length,
    rowHeight: ORDER_BOOK_ROW_HEIGHT,
    viewportHeight: viewport.height,
    scrollTop: requestedScrollTop,
    overscan: ORDER_BOOK_ROW_OVERSCAN,
  });

  const publishViewport = useCallback((element: HTMLDivElement) => {
    const height = element.clientHeight;
    const scrollTop = element.scrollTop;
    const distance = side === "ask" ? element.scrollHeight - height - scrollTop : scrollTop;
    onViewport(side, Math.max(2, Math.floor(height / ORDER_BOOK_ROW_HEIGHT)), distance > ORDER_BOOK_ROW_HEIGHT * 2);
    setViewport((previous) => previous.height === height && previous.scrollTop === scrollTop
      ? previous
      : { height, scrollTop });
  }, [onViewport, side]);

  useLayoutEffect(() => {
    const element = containerRef.current;
    if (!element) return undefined;
    publishViewport(element);
    const observer = typeof ResizeObserver === "function"
      ? new ResizeObserver(() => publishViewport(element))
      : null;
    observer?.observe(element);
    return () => observer?.disconnect();
  }, [publishViewport]);

  useLayoutEffect(() => {
    const element = containerRef.current;
    if (!element || side !== "ask" || !stickToEdgeRef.current) return;
    element.scrollTop = Math.max(0, element.scrollHeight - element.clientHeight);
    publishViewport(element);
  }, [displayRows.length, publishViewport, side, viewport.height]);

  useLayoutEffect(() => () => {
    if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
  }, []);

  const handleScroll = useCallback(() => {
    const element = containerRef.current;
    if (!element) return;
    if (side === "ask") {
      stickToEdgeRef.current = element.scrollHeight - element.clientHeight - element.scrollTop
        <= ORDER_BOOK_ROW_HEIGHT * 2;
    }
    if (frameRef.current !== null) return;
    frameRef.current = requestAnimationFrame(() => {
      frameRef.current = null;
      const current = containerRef.current;
      if (current) publishViewport(current);
    });
  }, [publishViewport, side]);

  return (
    <div
      ref={containerRef}
      className={`ob-levels ob-${side === "ask" ? "asks" : "bids"}`}
      onScroll={handleScroll}
    >
      <div className="ob-levels-window" style={{ height: window.totalHeight }}>
        {displayRows.slice(window.start, window.end).map((row, localIndex) => {
          const index = window.start + localIndex;
          return (
            <BookRow
              key={`${side}-slot-${row.slot}`}
              row={row}
              side={side}
              maxCumulative={maxCumulative}
              offsetPx={index * ORDER_BOOK_ROW_HEIGHT}
            />
          );
        })}
      </div>
    </div>
  );
}

function EmptyState({
  status,
  message,
  onRetry,
}: {
  status: OrderBookConnectionStatus;
  message: string | null;
  onRetry(): void;
}) {
  const canRetry = status === "error" || status === "reconnecting" || status === "stale";
  return (
    <SharedEmptyState
      compact
      className={`ob-empty-state ob-empty-${status}`}
      tone={status === "error" || status === "stale" ? "warning" : "accent"}
      icon={status === "stale" || status === "reconnecting"
        ? <Icon name="refresh" size={16} />
        : status === "unsupported" ? <Icon name="ban" size={16} /> : <Icon name="more" size={16} />}
      title={orderBookStatusLabel(status)}
      description={orderBookStatusDetail(status, message)}
      action={canRetry ? <Button size="sm" onClick={onRetry}>{t("orderBook.retry")}</Button> : null}
    />
  );
}

function OrderBookDock({ runtime, height, onRequestClose }: OrderBookDockProps) {
  useLocale();
  const { view, actions } = runtime;
  const snapshot = useSyncExternalStore(
    view.store.subscribe,
    view.store.getSnapshot,
    view.store.getServerSnapshot,
  );
  const [rangeBps, setRangeBps] = useState(0);
  const [display, setDisplay] = useState(() => ({ ask: Math.max(2, Math.floor((height - 170) / 44)), bid: Math.max(2, Math.floor((height - 170) / 44)), askBrowsing: false, bidBrowsing: false }));
  const onViewport = useCallback((side: "ask" | "bid", count: number, browsing: boolean) => {
    setDisplay((previous) => {
      const browsingKey = side === "ask" ? "askBrowsing" : "bidBrowsing";
      return previous[side] === count && previous[browsingKey] === browsing ? previous
        : { ...previous, [side]: count, [browsingKey]: browsing };
    });
  }, []);
  const autoFrozen = display.askBrowsing || display.bidBrowsing;
  const outputLimit = view.preferences.mode === "full" ? view.preferences.fullOutputLimit : view.preferences.partialDepth;
  useEffect(() => {
    actions.setDisplayOptions?.({
      targetRows: Math.max(2, Math.min(100, outputLimit, display.ask, display.bid)),
      rangeBps, autoFrozen,
    });
  }, [actions, autoFrozen, display.ask, display.bid, outputLimit, rangeBps]);
  const activeGrouping = view.preferences.mode === "partial"
    ? view.preferences.partialPriceGrouping
    : view.preferences.fullPriceGrouping;
  const presentation = useMemo(() => (
    snapshot.book ? orderBookPresentation(snapshot.book, activeGrouping, rangeBps) : null
  ), [activeGrouping, snapshot.book, rangeBps]);
  const rows = useMemo(() => (
    presentation ? buildOrderBookRows(presentation.bids, presentation.asks, presentation.aggregationApplied ? presentation.priceStep : null, presentation.incompleteBidPrices, presentation.incompleteAskPrices, { bidMin: presentation.coverageBidMin, askMax: presentation.coverageAskMax }) : null
  ), [presentation]);
  const groupingOptions = view.preferences.mode === "partial"
    ? PARTIAL_PRICE_GROUPINGS
    : FULL_PRICE_GROUPINGS;
  // Percentages must not imply coverage out to a wide bucket's synthetic edge.
  const coveredBid = presentation?.coverageBidMin == null ? null
    : Math.max(presentation.coverageBidMin, presentation.bids.at(-1)?.[0] ?? presentation.coverageBidMin);
  const coveredAsk = presentation?.coverageAskMax == null ? null
    : Math.min(presentation.coverageAskMax, presentation.asks.at(-1)?.[0] ?? presentation.coverageAskMax);
  const coverageIncomplete = Boolean(
    rows?.bids.some((row) => row.cumulativeIncomplete) || rows?.asks.some((row) => row.cumulativeIncomplete),
  );
  const coverageNote = presentation
    ? [
        presentation.coverageBidMin !== null && presentation.coverageAskMax !== null
          ? t("orderBook.knownRange", { min: formatPrice(presentation.coverageBidMin), max: formatPrice(presentation.coverageAskMax) })
          : t("orderBook.unknownRange"),
        coverageIncomplete ? t("orderBook.partialAmount") : null,
      ].filter(Boolean).join("\n")
    : "";
  const symbol = view.identity.symbol.replace(/USDT$|USDC$/, "");
  const deliveryLabel = snapshotDeliveryLabel(view.preferences.mode, view.snapshotMode, snapshot.book?.source);

  return (
    <section
      className="order-book-dock"
      style={{ height }}
      aria-label={t("orderBook.aria")}
    >
      <header className="ob-header">
        {onRequestClose && (
          <button
            type="button"
            className="ob-collapse-button"
            onClick={onRequestClose}
            title={t("orderBook.collapse")}
            aria-label={t("orderBook.collapse")}
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round">
              <polyline points="9 18 15 12 9 6" />
            </svg>
          </button>
        )}
        <span className="ob-title">{t("orderBook.title")}</span>
        <span className="ob-symbol">{symbol || view.identity.symbol}</span>
        <span className="ob-delivery-mode" title={t("orderBook.delivery.title")}>
          {deliveryLabel}
        </span>
        <span
          className={`ob-status ob-status-${snapshot.status}`}
          title={[
            orderBookStatusDetail(snapshot.status, snapshot.message || snapshot.error || view.supportMessage),
            snapshot.lastReceivedAtMs === null
              ? null
              : `${t("orderBook.lastReceived")} ${new Date(snapshot.lastReceivedAtMs).toLocaleString(getDateTimeLocale(), { hour12: false })}`,
          ].filter(Boolean).join("\n")}
        >
          <span className="ob-status-dot" aria-hidden="true" />
          {orderBookStatusLabel(snapshot.status)}
        </span>
      </header>

      <>
          <div className="ob-controls">
            <div className="ob-mode-switch" role="group" aria-label={t("orderBook.mode")}>
              <button
                type="button"
                className={view.preferences.mode === "partial" ? "active" : ""}
                onClick={() => actions.setMode("partial")}
                title={view.snapshotMode === "polling_snapshot"
                  ? t("orderBook.snapshotPollingTitle")
                  : t("orderBook.snapshotTitle")}
              >
                {t("orderBook.snapshot")}
              </button>
              <button
                type="button"
                className={view.preferences.mode === "full" ? "active" : ""}
                onClick={() => actions.setMode("full")}
                disabled={!view.fullModeSupported}
                title={view.fullModeSupported
                  ? t("orderBook.continuousTitle")
                  : t("orderBook.continuousUnsupported")}
              >
                {t("orderBook.continuous")}
              </button>
            </div>
            <label>
              <span className="sr-only">{t("orderBook.levels")}</span>
              {view.preferences.mode === "partial" ? (
                <select
                  aria-label={t("orderBook.snapshotLevels")}
                  value={view.preferences.partialDepth}
                  onChange={(event) => actions.setPartialDepth(Number(event.target.value) as PartialDepthLevel)}
                >
                  {PARTIAL_DEPTH_LEVELS.map((depth) => <option key={depth} value={depth}>{t("orderBook.levelsOption", { n: depth })}</option>)}
                </select>
              ) : (
                <select
                  aria-label={t("orderBook.fullLevels")}
                  value={view.preferences.fullOutputLimit}
                  onChange={(event) => actions.setFullOutputLimit(Number(event.target.value) as FullOutputLimit)}
                >
                  {FULL_OUTPUT_LIMITS.map((limit) => <option key={limit} value={limit}>{t("orderBook.levelsOption", { n: limit })}</option>)}
                </select>
              )}
            </label>
            <label title={view.preferences.mode === "partial"
              ? t("orderBook.groupingPartial")
              : t("orderBook.groupingFull")}
            >
              <span className="sr-only">{t("orderBook.grouping")}</span>
              <select
                aria-label={t("orderBook.groupingAria")}
                value={activeGrouping}
                onChange={(event) => actions.setPriceGrouping(
                  view.preferences.mode,
                  event.target.value as PriceGrouping,
                )}
              >
                {groupingOptions.map((grouping) => (
                  <option
                    key={grouping}
                    value={grouping}
                    disabled={grouping !== "auto" && grouping !== "raw" && !snapshot.book?.priceTickSize}
                  >
                    {groupingLabel(grouping, view.preferences.mode, snapshot.book)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span className="sr-only">{t("orderBook.frequency")}</span>
              <select
                aria-label={t("orderBook.frequency")}
                value={view.updateIntervalMs}
                onChange={(event) => actions.setUpdateIntervalMs(Number(event.target.value) as OrderBookUpdateIntervalMs)}
              >
                {view.updateIntervalsMs.map((interval) => <option key={interval} value={interval}>{interval} ms</option>)}
              </select>
            </label>
          </div>

          <div className="ob-range-controls">
            <label>
              {t("orderBook.range")}
              <select aria-label={t("orderBook.range")} value={rangeBps}
                onChange={(event) => setRangeBps(Number(event.target.value))}>
                {[0, 5, 10, 25, 50, 100].map((bps) => (
                  <option key={bps} value={bps}>{bps ? `${bps / 100}%` : t("orderBook.rangeAll")}</option>
                ))}
              </select>
            </label>
            {snapshot.book?.midPrice && coveredBid !== null && coveredAsk !== null && (
              <span>
                −{(((snapshot.book.midPrice - coveredBid) / snapshot.book.midPrice) * 100).toFixed(3)}%
                {" / "}
                +{(((coveredAsk - snapshot.book.midPrice) / snapshot.book.midPrice) * 100).toFixed(3)}%
              </span>
            )}
            {activeGrouping === "auto" && autoFrozen && <span>{t("orderBook.autoFrozen")}</span>}
          </div>

          <div className="ob-column-header">
            <span>
              {t("orderBook.price")}{presentation?.priceStep ? ` · ${formatPrice(presentation.priceStep)}` : ""}
              {coverageNote && (
                <span
                  className={`ob-coverage-info${coverageIncomplete ? " is-partial" : ""}`}
                  role="img"
                  tabIndex={0}
                  title={coverageNote}
                  aria-label={coverageNote}
                >
                  <Icon name="info" size={12} />
                </span>
              )}
            </span>
            <span>{t("orderBook.qty")}</span>
            <span>{t("orderBook.cumulative")}</span>
          </div>

          {snapshot.book && presentation && rows && snapshot.status === "stale" && (
            <div className="ob-stale-bar" role="status">
              <span>{snapshot.message || t("orderBook.rt.staleSnapshot")}</span>
              <button type="button" onClick={actions.retry}>{t("orderBook.retry")}</button>
            </div>
          )}
          {snapshot.book && presentation && rows ? (
            <div className={`ob-book-scroll${snapshot.status === "stale" ? " is-stale" : ""}`}>
              <BookLevels key={`${view.identity.exchange}:${view.identity.marketType}:${view.identity.symbol}:${view.preferences.mode}:asks`} onViewport={onViewport} rows={rows.asks} side="ask" maxCumulative={rows.maxCumulative} />
              <div className="ob-spread-row">
                <span className="ob-mid-price">{formatPrice(snapshot.book.midPrice)}</span>
                <span>{formatSpread(snapshot.book.spread, snapshot.book.spreadBps)}</span>
                {snapshot.book.mode === "partial" && snapshot.book.notionalImbalance !== null && (
                  <span title={t("orderBook.imbalance")}>
                    {t("orderBook.skew")} {snapshot.book.notionalImbalance >= 0 ? "+" : ""}
                    {trimZeros((snapshot.book.notionalImbalance * 100).toFixed(1))}%
                  </span>
                )}
                {snapshot.book.mode === "full" && presentation.aggregationApplied && (
                  <span>{t("orderBook.aggregated", { step: formatPrice(presentation.priceStep) })}</span>
                )}
              </div>
              <BookLevels key={`${view.identity.exchange}:${view.identity.marketType}:${view.identity.symbol}:${view.preferences.mode}:bids`} onViewport={onViewport} rows={rows.bids} side="bid" maxCumulative={rows.maxCumulative} />
            </div>
          ) : (
            <EmptyState
              status={snapshot.status}
              message={snapshot.message || snapshot.error || view.supportMessage}
              onRetry={actions.retry}
            />
          )}
      </>
    </section>
  );
}

export default React.memo(OrderBookDock);
