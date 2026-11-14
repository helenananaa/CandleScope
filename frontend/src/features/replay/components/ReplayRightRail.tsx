import { useReplayOperations } from "../useReplayOperations.js";
import { describeError } from "../../../i18n/serverErrors.js";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { Badge, Button, Checkbox, Disclosure, EmptyState, Field, InlineAlert, Input, SegmentedControl, Select, Stat, TabPanel, Tabs, Textarea } from "../../../components/ui/index.js";
import type { ReactNode } from "react";
import { getNumberLocale, t } from "../../../i18n/index.js";
import { useLocale } from "../../../i18n/useLocale.js";

import {
  formatReplayPublicTime,
  recentReplayActivity,
  REPLAY_ACTIVITY_VIEW_LIMIT,
  replayOwnsController,
} from "../replayUiModel.js";
import { ReplayV2ApiError } from "../replayV2Api.js";
import {
  rebaseReplayMaxQuantity,
  replayOrderContextSide,
  replayOrderSizingAvailability,
  replayReduceOnlyUnavailableMessage,
  replayBoundClosingCapacity,
  replayOrderSideCapacity,
  replayQuantityForShare,
  replayQuantityForStep as quantityForStep,
  replayOrderIsolatedAllocation,
} from "../replayOrderSizing.js";
import { replayOrderCtaState } from "../replayOrderCtaState.js";
import { createReplayOrderAdvisoryScheduler } from "../replayOrderAdvisoryScheduler.js";
import {
  replayMarkFidelityLabel,
  replayPositiveModelPrice,
} from "../replayPositionHlines.js";
import type { ReplayClosedTrade } from "../replayTypes.js";
import type {
  ReplayOrderPreview,
  ReplayOrderCapacity,
  ReplayOrderCapacityContext,
  ReplayOrderRequest,
  ReplayTradePlanDraft,
  ReplayAccountOrderScope,
  ReplayAccountRecordType,
  ReplayTrainingContractPortfolio,
  ReplayV2Json,
} from "../replayV2Types.js";
import type { ReplayRuntime } from "../useReplayRuntime.js";
import { useReplayTradeFlow } from "../useReplayTradeFlow.js";
import type { ReplayViewerRuntime } from "../useReplayViewerRuntime.js";
import ReplayLiquidationTimeline from "./ReplayLiquidationTimeline.js";

const TERMINAL_ORDER_STATES = new Set(["FILLED", "CANCELED", "REJECTED", "EXPIRED"]);
const REPLAY_ORDER_VALIDATION_TIMEOUT_MS = 15_000;
const WORKBENCH_TAB_IDS = [
  "positions",
  "open-orders",
  "order-history",
  "fills",
  "assets",
  "risk",
] as const;
const MARKET_TAB_IDS = [
  "book",
  "flow",
  "indicators",
] as const;

type WorkbenchTab = typeof WORKBENCH_TAB_IDS[number];
type MarketTab = typeof MARKET_TAB_IDS[number];

function workbenchTabLabel(id: WorkbenchTab): string {
  switch (id) {
    case "positions": return t("replay.wb.positions");
    case "open-orders": return t("replay.wb.openOrders");
    case "order-history": return t("replay.wb.orderHistory");
    case "fills": return t("replay.wb.fills");
    case "assets": return t("replay.wb.assets");
    case "risk": return t("replay.wb.risk");
  }
}

function marketTabLabel(id: MarketTab): string {
  switch (id) {
    case "book": return t("replay.dock.book");
    case "flow": return t("replay.dock.flow");
    case "indicators": return t("replay.dock.indicators");
  }
}
type JsonRecord = Readonly<Record<string, ReplayV2Json>>;
type TradeType =
  | "place_order"
  | "replace_order"
  | "cancel_order"
  | "cancel_orders"
  | "close_position"
  | "execute_position_intent"
  | "set_position_protection"
  | "set_position_leverage";
type TradeNotice = Readonly<{
  tone: "pending" | "success" | "error";
  message: string;
}> | null;

interface AccountRecordPageState {
  readonly key: string;
  readonly items: readonly JsonRecord[];
  readonly totalCount: number;
  readonly nextCursor: string | null;
  readonly loading: boolean;
  readonly loadingMore: boolean;
  readonly error: string | null;
}

function useAccountRecordPages({
  runId,
  recordType,
  orderScope,
  enabled,
  revision,
}: {
  readonly runId: string | null;
  readonly recordType: ReplayAccountRecordType;
  readonly orderScope: ReplayAccountOrderScope;
  readonly enabled: boolean;
  readonly revision: number;
}) {
  const { api } = useReplayOperations(runId, "rail");
  const key = `${runId ?? "none"}:${recordType}:${orderScope}:${revision}`;
  const [state, setState] = useState<AccountRecordPageState>({
    key,
    items: [],
    totalCount: 0,
    nextCursor: null,
    loading: false,
    loadingMore: false,
    error: null,
  });
  useEffect(() => {
    if (!enabled || runId === null) return undefined;
    const controller = new AbortController();
    setState({
      key,
      items: [],
      totalCount: 0,
      nextCursor: null,
      loading: true,
      loadingMore: false,
      error: null,
    });
    void api.accountRecordsRun(runId, {
      recordType,
      orderScope,
      limit: 50,
    }, controller.signal).then((page) => {
      if (controller.signal.aborted) return;
      setState({
        key,
        items: page.items,
        totalCount: page.total_count,
        nextCursor: page.next_cursor,
        loading: false,
        loadingMore: false,
        error: null,
      });
    }).catch((error: unknown) => {
      if (controller.signal.aborted) return;
      setState({
        key,
        items: [],
        totalCount: 0,
        nextCursor: null,
        loading: false,
        loadingMore: false,
        error: commandErrorMessage(error),
      });
    });
    return () => controller.abort();
  }, [api, enabled, key, orderScope, recordType, runId]);
  const loadMore = useCallback(async (): Promise<void> => {
    if (runId === null || state.key !== key || state.nextCursor === null
      || state.loading || state.loadingMore) return;
    const cursor = state.nextCursor;
    setState((current) => current.key === key
      ? { ...current, loadingMore: true, error: null }
      : current);
    try {
      const page = await api.accountRecordsRun(runId, {
        recordType,
        orderScope,
        cursor,
        limit: 50,
      });
      setState((current) => current.key === key && current.nextCursor === cursor
        ? {
            ...current,
            items: [...current.items, ...page.items],
            totalCount: page.total_count,
            nextCursor: page.next_cursor,
            loadingMore: false,
          }
        : current);
    } catch (error) {
      setState((current) => current.key === key
        ? { ...current, loadingMore: false, error: commandErrorMessage(error) }
        : current);
    }
  }, [api, key, orderScope, recordType, runId, state.key, state.loading, state.loadingMore, state.nextCursor]);
  const visible = state.key === key ? state : {
    key,
    items: [],
    totalCount: 0,
    nextCursor: null,
    loading: enabled && runId !== null,
    loadingMore: false,
    error: null,
  };
  return { ...visible, loadMore };
}

function orderTypeLabel(value: string): string {
  switch (value) {
    case "MARKET": return t("replay.paper.typeMarket");
    case "LIMIT": return t("replay.paper.typeLimit");
    case "STOP_MARKET": return t("replay.paper.stopMkt");
    case "TAKE_PROFIT_MARKET": return t("replay.paper.tpMkt");
    default: return value;
  }
}

function orderStatusLabel(value: string): string {
  switch (value) {
    case "OPEN": return t("replay.paper.statusOpen");
    case "ACCEPTED": return t("replay.paper.statusAccepted");
    case "PARTIALLY_FILLED": return t("replay.paper.statusPartial");
    case "FILLED": return t("replay.paper.statusFilled");
    case "CANCELED": return t("replay.paper.statusCanceled");
    case "REJECTED": return t("replay.paper.statusRejected");
    case "EXPIRED": return t("replay.paper.statusExpired");
    default: return value;
  }
}

function orderClientId(): string {
  return `ticket-${globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.trunc(Math.random() * 1_000_000)}`}`;
}

function jsonRecord(value: ReplayV2Json | undefined): JsonRecord | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as JsonRecord
    : null;
}

function recordText(record: JsonRecord, key: string, fallback = "--"): string {
  const value = record[key];
  return typeof value === "string" || typeof value === "number" ? String(value) : fallback;
}

function recordBoolean(record: JsonRecord, key: string): boolean {
  return record[key] === true;
}

function recordNumber(record: JsonRecord, key: string): number | null {
  const value = record[key];
  return typeof value === "number" && Number.isSafeInteger(value) ? value : null;
}

function contractPortfolio(value: unknown): ReplayTrainingContractPortfolio | null {
  if (typeof value !== "object" || value === null) return null;
  const candidate = value as { readonly schema_version?: unknown };
  return candidate.schema_version === "replay.training.portfolio.v2"
    ? value as ReplayTrainingContractPortfolio
    : null;
}

function finiteNumber(value: unknown): number | null {
  const parsed = typeof value === "number" ? value : Number(String(value ?? ""));
  return Number.isFinite(parsed) ? parsed : null;
}

const decimalFormatters = new Map<string, Intl.NumberFormat>();

function formatDecimal(value: unknown, maximumFractionDigits = 8): string {
  if (value === null || value === undefined || value === "") return "--";
  const parsed = finiteNumber(value);
  if (parsed === null) return String(value);
  const locale = getNumberLocale();
  const key = `${locale}:${maximumFractionDigits}`;
  let formatter = decimalFormatters.get(key);
  if (formatter === undefined) {
    formatter = new Intl.NumberFormat(locale, {
      maximumFractionDigits,
      minimumFractionDigits: 0,
      useGrouping: true,
    });
    if (decimalFormatters.size >= 32) {
      const oldest = decimalFormatters.keys().next().value;
      if (oldest !== undefined) decimalFormatters.delete(oldest);
    }
    decimalFormatters.set(key, formatter);
  }
  return formatter.format(parsed);
}

function sideLabel(value: string): string {
  return value === "BUY" ? t("replay.paper.buy") : value === "SELL" ? t("replay.paper.sell") : value;
}

function baseAsset(symbol: string, settlementAsset: string): string {
  return settlementAsset && symbol.endsWith(settlementAsset)
    ? symbol.slice(0, -settlementAsset.length)
    : symbol;
}

function selectedRule(
  contract: ReplayTrainingContractPortfolio | null,
  trackId: string,
): JsonRecord | null {
  const entry = contract?.instrument_rules.find((item) => recordText(item, "track_id") === trackId);
  return entry === undefined ? null : jsonRecord(entry.rule);
}

function orderPrice(order: JsonRecord): string {
  return recordText(
    order,
    "average_fill_price",
    recordText(order, "limit_price", recordText(order, "stop_price", t("replay.paper.typeMarket"))),
  );
}

function eventTime(record: JsonRecord): number | null {
  return recordNumber(record, "event_time_ms") ?? recordNumber(record, "created_time_ms");
}

function commandErrorMessage(error: unknown): string {
  if (error instanceof ReplayV2ApiError) {
    if (error.code === "RUN_ACCOUNT_MARGIN_EXCEEDED") {
      const available = finiteNumber(error.details.available_equity);
      return available === null
        ? t("replay.paper.marginExceeded")
        : t("replay.paper.marginAvail", { available: formatDecimal(available, 4) });
    }
    if (error.code === "RISK_LIMIT_EXCEEDED") return t("replay.paper.riskLimit", { message: error.message });
    if (error.code === "ORDER_REJECTED") return t("replay.paper.rejected", { message: error.message });
  }
  return error instanceof Error ? describeError(error, error.message) : t("replay.paper.submitFailed");
}

function useTradeNoticeAutoDismiss(
  notice: TradeNotice,
  setNotice: (value: TradeNotice) => void,
) {
  useEffect(() => {
    if (notice === null || notice.tone === "pending") return undefined;
    const timer = globalThis.setTimeout(() => setNotice(null), 4_000);
    return () => globalThis.clearTimeout(timer);
  }, [notice, setNotice]);
}

export interface ReplayRightRailProps {
  readonly runtime: ReplayRuntime;
  readonly viewer: ReplayViewerRuntime;
  readonly indicatorStatus: {
    readonly mode: string;
    readonly sourceBarCount: number;
    readonly disabledCapabilities: readonly string[];
  };
  readonly formatTime?: (valueMs: number) => string;
}

export function ReplayPaperTradingDock({ runtime, viewer }: Pick<ReplayRightRailProps, "runtime" | "viewer">) {
  useLocale();
  const orderTypeTabsId = useId();
  const sizeUnitId = useId();
  type SizeMode = "QUANTITY" | "MARGIN" | "NOTIONAL";
  const [side, setSide] = useState<"BUY" | "SELL">("BUY");
  const [orderType, setOrderType] = useState<"MARKET" | "LIMIT" | "STOP_MARKET" | "TAKE_PROFIT_MARKET">("MARKET");
  const [sizeMode, setSizeMode] = useState<SizeMode>("QUANTITY");
  const [sizeInput, setSizeInput] = useState("0.001");
  const [price, setPrice] = useState("");
  const [reduceOnly, setReduceOnly] = useState(false);
  const [sliderDragging, setSliderDragging] = useState(false);
  const [sliderPct, setSliderPct] = useState(0);
  const [sizeShareIntent, setSizeShareIntent] = useState<number | null>(null);
  const [tradePlanEnabled, setTradePlanEnabled] = useState(false);
  const [riskSizingMode, setRiskSizingMode] = useState<"RISK_AMOUNT" | "ACCOUNT_RISK_PERCENT">(
    "ACCOUNT_RISK_PERCENT",
  );
  const [riskValue, setRiskValue] = useState("1");
  const [invalidationPrice, setInvalidationPrice] = useState("");
  const [targetPrice, setTargetPrice] = useState("");
  const [tradeReason, setTradeReason] = useState("");
  const [clientOrderId, setClientOrderId] = useState(orderClientId);
  const [previewState, setPreviewState] = useState<Readonly<{
    key: string;
    status: "pending" | "ready" | "error";
    result: ReplayOrderPreview | null;
    error: string | null;
  }> | null>(null);
  const [capacityState, setCapacityState] = useState<Readonly<{
    key: string;
    status: "pending" | "ready" | "error";
    result: ReplayOrderCapacity | null;
    error: string | null;
  }> | null>(null);
  const [maxQuantitySnapshot, setMaxQuantitySnapshot] = useState<Readonly<{
    key: string;
    sizingKey: string;
    value: string;
    referencePrice: number | null;
    availableEquity: number | null;
    leverage: number;
  }> | null>(null);
  const [notice, setNotice] = useState<TradeNotice>(null);
  const [tradeValidationSide, setTradeValidationSide] = useState<"BUY" | "SELL" | null>(null);
  const tradeValidationControllerRef = useRef<AbortController | null>(null);
  const tradeValidationMountedRef = useRef(true);
  const capacityAdvisoryControllerRef = useRef<AbortController | null>(null);
  const previewAdvisoryControllerRef = useRef<AbortController | null>(null);
  const capacityScheduler = useMemo(createReplayOrderAdvisoryScheduler, []);
  const previewScheduler = useMemo(createReplayOrderAdvisoryScheduler, []);
  useEffect(() => {
    tradeValidationMountedRef.current = true;
    return () => {
      tradeValidationMountedRef.current = false;
      capacityScheduler.cancel();
      previewScheduler.cancel();
      capacityAdvisoryControllerRef.current?.abort();
      previewAdvisoryControllerRef.current?.abort();
      tradeValidationControllerRef.current?.abort();
      capacityAdvisoryControllerRef.current = null;
      previewAdvisoryControllerRef.current = null;
      tradeValidationControllerRef.current = null;
    };
  }, [capacityScheduler, previewScheduler]);
  useTradeNoticeAutoDismiss(notice, setNotice);
  const store = runtime.store;
  const viewerReady = viewer.viewerState !== null && !viewer.viewerPending;
  const config = store.sessionConfig;
  const ownsController = replayOwnsController(store, runtime.clientInstanceId);
  const commandAvailable = ownsController
    && store.connectionState === "connected"
    && store.state !== "ENDED";
  const commandReady = commandAvailable
    && runtime.pendingCommand === null
    && !viewer.viewerPending;
  const portfolio = viewer.marketTracks?.portfolio ?? null;
  const contract = contractPortfolio(portfolio);
  const selectedTrackId = viewer.viewerState?.selected_track_id ?? "track-1";
  const selectedTrack = viewer.marketTracks?.tracks.find((item) => item.track_id === selectedTrackId) ?? null;
  const settlementAsset = selectedTrack?.settlement_asset ?? store.account?.quote_asset ?? "";
  const symbol = selectedTrack?.symbol ?? config?.symbol ?? "--";
  const quantityAsset = baseAsset(symbol, settlementAsset);
  const rule = selectedRule(contract, selectedTrackId);
  const positionMode = portfolio?.position_mode ?? "ONE_WAY";
  const activePositionSide: "LONG" | "SHORT" = reduceOnly
    ? side === "BUY" ? "SHORT" : "LONG"
    : side === "BUY" ? "LONG" : "SHORT";
  const isolatedAllocation = replayOrderIsolatedAllocation({
    marginMode: contract?.margin_mode,
    positionMode,
    allocations: positionMode === "HEDGE" ? contract?.isolated_wallets : contract?.isolated_allocations,
    trackId: selectedTrackId,
    positionSide: activePositionSide,
  });
  const selectedPosition = portfolio?.positions.find((item) => (
    item.track_id === selectedTrackId
    && (positionMode !== "HEDGE" || item.position_side === activePositionSide)
  )) ?? null;
  const positionQty = finiteNumber(selectedPosition?.position.quantity) ?? 0;
  const reduceOnlyUnavailableMessage = replayReduceOnlyUnavailableMessage({
    reduceOnly,
    positionQuantity: positionQty,
    positionMode,
    targetPositionSide: activePositionSide,
  });
  const previewSide = replayOrderContextSide(positionQty, side, reduceOnly);
  const maxLeverage = Math.max(1, finiteNumber(config?.max_leverage) ?? 1);
  const [selectedLeverage, setLeverage] = useState(maxLeverage);
  const leverage = Math.min(Math.max(1, selectedLeverage), maxLeverage);
  const quantityStep = recordText(rule ?? {}, "quantity_step", "0.00000001");
  const quoteStep = recordText(rule ?? {}, "quote_step", "0.01");
  const markPrice = useMemo(() => {
    const fromTrack = finiteNumber(selectedTrack?.public_price);
    if (fromTrack !== null && fromTrack > 0) return fromTrack;
    const pos = portfolio?.positions.find((item) => item.track_id === selectedTrackId);
    const fromPos = finiteNumber(pos?.position.mark_price);
    return fromPos !== null && fromPos > 0 ? fromPos : null;
  }, [portfolio?.positions, selectedTrack?.public_price, selectedTrackId]);
  const referencePrice = useMemo(() => {
    if (orderType === "LIMIT" || orderType === "STOP_MARKET" || orderType === "TAKE_PROFIT_MARKET") {
      return finiteNumber(price);
    }
    return markPrice;
  }, [markPrice, orderType, price]);
  const sizingAvailableEquity = finiteNumber(
    contract?.margin_mode === "ISOLATED"
      ? recordText(selectedTrack?.account ?? {}, "available_equity", "")
      : portfolio?.available_equity,
  );
  const tradePlanEligible = !reduceOnly && (orderType === "MARKET" || orderType === "LIMIT");
  const previewPositionIntent = !reduceOnly
    && (orderType === "MARKET" || (tradePlanEnabled && tradePlanEligible)) ? "OPEN" : "NET";
  const maxQuantitySizingKey = JSON.stringify([
    selectedTrackId,
    isolatedAllocation,
    previewSide,
    orderType,
    reduceOnly,
    previewPositionIntent,
    reduceOnly ? positionQty : null,
  ]);
  const rebasedMaxQuantity = maxQuantitySnapshot?.sizingKey === maxQuantitySizingKey
    ? rebaseReplayMaxQuantity({
      previousMaxQuantity: finiteNumber(maxQuantitySnapshot.value),
      previousReferencePrice: maxQuantitySnapshot.referencePrice,
      nextReferencePrice: referencePrice,
      previousAvailableEquity: maxQuantitySnapshot.availableEquity,
      nextAvailableEquity: sizingAvailableEquity,
      previousLeverage: maxQuantitySnapshot.leverage,
      nextLeverage: leverage,
      reduceOnly,
    })
    : null;
  const intendedMaxSizeValue = (() => {
    if (rebasedMaxQuantity === null || rebasedMaxQuantity <= 0) return null;
    if (sizeMode === "QUANTITY") return rebasedMaxQuantity;
    if (referencePrice === null || referencePrice <= 0) return null;
    if (sizeMode === "NOTIONAL") return rebasedMaxQuantity * referencePrice;
    return (rebasedMaxQuantity * referencePrice) / Math.max(1, leverage);
  })();
  const resolvedSizeInput = sizeShareIntent !== null && intendedMaxSizeValue !== null
    ? replayQuantityForShare(
      String(intendedMaxSizeValue), sizeShareIntent,
      sizeMode === "QUANTITY" ? quantityStep : quoteStep,
    ) ?? "0"
    : sizeInput;
  const quantity = (() => {
    const input = finiteNumber(resolvedSizeInput);
    if (input === null || input <= 0) return "";
    if (sizeMode === "QUANTITY") return quantityForStep(resolvedSizeInput, quantityStep);
    if (referencePrice === null || referencePrice <= 0) return "";
    if (sizeMode === "NOTIONAL") return quantityForStep(input / referencePrice, quantityStep);
    return quantityForStep((input * leverage) / referencePrice, quantityStep);
  })();
  const tradePlanDraft = useMemo<ReplayTradePlanDraft | null>(() => (
    tradePlanEnabled && tradePlanEligible
      ? {
        sizing_mode: riskSizingMode,
        risk_amount: riskSizingMode === "RISK_AMOUNT" ? riskValue : null,
        risk_percent: riskSizingMode === "ACCOUNT_RISK_PERCENT" ? riskValue : null,
        invalidation_price: invalidationPrice,
        target_price: targetPrice,
        reason: tradeReason,
      }
      : null
  ), [
    invalidationPrice,
    riskSizingMode,
    riskValue,
    targetPrice,
    tradePlanEligible,
    tradePlanEnabled,
    tradeReason,
  ]);
  const previewOrder = viewer.actions.previewOrder;
  const orderCapacity = viewer.actions.orderCapacity;
  const cursorReady = store.virtualTimeMs !== null;
  const cursorAdvisoryEpoch = JSON.stringify([
    store.revision,
    store.sourceSequence,
    store.virtualTimeMs,
  ]);
  const previewKey = JSON.stringify([
    cursorAdvisoryEpoch,
    selectedTrackId,
    isolatedAllocation,
    previewPositionIntent,
    clientOrderId,
    previewSide,
    orderType,
    sizeMode,
    sizeInput,
    sizeShareIntent,
    reduceOnly,
    price,
    leverage,
    tradePlanDraft,
  ]);
  const maxQuantityContextKey = JSON.stringify([
    selectedTrackId,
    isolatedAllocation,
    previewSide,
    orderType,
    reduceOnly,
    previewPositionIntent,
    price,
    leverage,
    reduceOnly ? positionQty : null,
  ]);
  useEffect(() => {
    if (
      !viewerReady
      || store.connectionState !== "connected"
      || store.state !== "PAUSED"
      || !cursorReady
      || tradeValidationSide !== null
      || reduceOnlyUnavailableMessage !== null
      || (orderType !== "MARKET" && !price.trim())
    ) {
      return undefined;
    }
    capacityAdvisoryControllerRef.current?.abort();
    const controller = new AbortController();
    capacityAdvisoryControllerRef.current = controller;
    let settled = false;
    const scheduled = capacityScheduler.schedule(maxQuantityContextKey, () => {
      const context: ReplayOrderCapacityContext = {
        side: previewSide,
        order_type: orderType,
        reduce_only: reduceOnly,
        limit_price: orderType === "LIMIT" ? price : null,
        stop_price: orderType === "STOP_MARKET" || orderType === "TAKE_PROFIT_MARKET"
          ? price
          : null,
        leverage: String(leverage),
        ...(positionMode === "HEDGE" ? { position_side: activePositionSide } : {}),
      };
      setCapacityState({
        key: maxQuantityContextKey,
        status: "pending",
        result: null,
        error: null,
      });
      void orderCapacity(
        context,
        previewPositionIntent,
        controller.signal,
      ).then((result) => {
        if (controller.signal.aborted) return;
        setMaxQuantitySnapshot({
          key: maxQuantityContextKey,
          sizingKey: maxQuantitySizingKey,
          value: result.max_quantity,
          referencePrice: finiteNumber(result.reference_price),
          availableEquity: sizingAvailableEquity,
          leverage,
        });
        setCapacityState({
          key: maxQuantityContextKey,
          status: "ready",
          result,
          error: null,
        });
      }).catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setCapacityState({
          key: maxQuantityContextKey,
          status: "error",
          result: null,
          error: commandErrorMessage(error),
        });
      }).finally(() => {
        settled = true;
        if (capacityAdvisoryControllerRef.current === controller) {
          capacityAdvisoryControllerRef.current = null;
        }
      });
    });
    return () => {
      capacityScheduler.cancel();
      controller.abort();
      if (capacityAdvisoryControllerRef.current === controller) {
        capacityAdvisoryControllerRef.current = null;
      }
      if (scheduled && !settled) capacityScheduler.forget(maxQuantityContextKey);
    };
  // Cursor-driven equity is deliberately sampled only when this draft context
  // changes, including explicit funding of the selected isolated leg. The
  // cached cap is conservatively rebased between those requests.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    capacityScheduler,
    cursorReady,
    leverage,
    maxQuantityContextKey,
    maxQuantitySizingKey,
    orderCapacity,
    orderType,
    positionMode,
    activePositionSide,
    previewSide,
    previewPositionIntent,
    price,
    reduceOnly,
    reduceOnlyUnavailableMessage,
    store.connectionState,
    store.state,
    tradeValidationSide,
    viewerReady,
  ]);
  const currentCapacityState = capacityState?.key === maxQuantityContextKey
    ? capacityState
    : null;
  const capacity = currentCapacityState?.status === "ready"
    ? currentCapacityState.result
    : null;
  const capacityError = currentCapacityState?.status === "error"
    ? currentCapacityState.error
    : null;
  const capacityReadyKey = currentCapacityState?.status === "ready"
    ? currentCapacityState.key
    : null;
  const estimatedMaxQuantity = replayBoundClosingCapacity(rebasedMaxQuantity !== null
    ? quantityForStep(rebasedMaxQuantity, quantityStep)
    : capacity?.max_quantity
      ?? (maxQuantitySnapshot?.key === maxQuantityContextKey
        ? maxQuantitySnapshot.value
        : null), reduceOnly, positionQty);
  const sizingAvailability = replayOrderSizingAvailability(estimatedMaxQuantity, quantity);
  const quantityExceedsCapacity = sizingAvailability.quantityExceedsCapacity;
  useEffect(() => {
    // A server preview describes one exact replay boundary. Keep the
    // conservative, locally rebased capacity estimate, but never display a
    // stale fill/margin preview after the cursor moves. The new key requests
    // one preview once the paused cursor is quiet; submission still revalidates.
    setPreviewState((current) => current === null ? current : null);
  }, [cursorAdvisoryEpoch]);
  useEffect(() => {
    if (
      !viewerReady
      || store.connectionState !== "connected"
      || store.state !== "PAUSED"
      || !cursorReady
      || tradeValidationSide !== null
      || capacityReadyKey !== maxQuantityContextKey
      || viewer.controlPending
      || runtime.pendingCommand !== null
      || !quantity.trim()
      || quantityExceedsCapacity
      || (orderType !== "MARKET" && !price.trim())
      || (tradePlanDraft !== null && (
        !riskValue.trim()
        || !invalidationPrice.trim()
        || !targetPrice.trim()
        || !tradeReason.trim()
      ))
    ) {
      return undefined;
    }
    previewAdvisoryControllerRef.current?.abort();
    const controller = new AbortController();
    previewAdvisoryControllerRef.current = controller;
    let settled = false;
    const scheduled = previewScheduler.schedule(previewKey, () => {
      const previewDraftOrder: ReplayOrderRequest = {
        client_order_id: clientOrderId,
        side: previewSide,
        order_type: orderType,
        quantity: quantity.trim() || "0",
        reduce_only: reduceOnly,
        limit_price: orderType === "LIMIT" ? price : null,
        stop_price: orderType === "STOP_MARKET" || orderType === "TAKE_PROFIT_MARKET"
          ? price
          : null,
        leverage: String(leverage),
        ...(positionMode === "HEDGE" ? { position_side: activePositionSide } : {}),
      };
      setPreviewState({
        key: previewKey,
        status: "pending",
        result: null,
        error: null,
      });
      void previewOrder(
        previewDraftOrder,
        previewPositionIntent,
        tradePlanDraft,
        controller.signal,
      ).then((result) => {
        if (controller.signal.aborted) return;
        setPreviewState({
          key: previewKey,
          status: "ready",
          result,
          error: null,
        });
      }).catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setPreviewState({
          key: previewKey,
          status: "error",
          result: null,
          error: commandErrorMessage(error),
        });
      }).finally(() => {
        settled = true;
        if (previewAdvisoryControllerRef.current === controller) {
          previewAdvisoryControllerRef.current = null;
        }
      });
    });
    return () => {
      previewScheduler.cancel();
      controller.abort();
      if (previewAdvisoryControllerRef.current === controller) {
        previewAdvisoryControllerRef.current = null;
      }
      if (scheduled && !settled) previewScheduler.forget(previewKey);
    };
  // Derived quantity is sampled by the cursor/draft key. Rapid cursor movement
  // cancels the pending timer; playing never requests advisory previews.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    clientOrderId,
    capacityReadyKey,
    viewer.controlPending,
    runtime.pendingCommand,
    cursorReady,
    leverage,
    orderType,
    positionMode,
    activePositionSide,
    previewOrder,
    previewPositionIntent,
    price,
    previewScheduler,
    previewKey,
    reduceOnly,
    riskValue,
    selectedTrackId,
    previewSide,
    store.connectionState,
    store.state,
    targetPrice,
    tradePlanDraft,
    tradeReason,
    tradeValidationSide,
    invalidationPrice,
    maxQuantityContextKey,
    maxQuantitySizingKey,
    quantityExceedsCapacity,
    viewerReady,
  ]);
  const currentPreviewState = previewState?.key === previewKey ? previewState : null;
  const preview = currentPreviewState?.status === "ready"
    ? currentPreviewState.result
    : null;
  const previewPending = currentPreviewState?.status === "pending";
  const previewError = currentPreviewState?.status === "error"
    ? currentPreviewState.error
    : null;
  const capacityValidationError = quantityExceedsCapacity
    ? t("replay.paper.overCap", { qty: formatDecimal(estimatedMaxQuantity, 8), asset: quantityAsset })
    : null;
  const isSpot = config?.market_type.toLowerCase().includes("spot") ?? false;
  const positionSide: "flat" | "long" | "short" = positionQty > 0
    ? "long"
    : positionQty < 0
      ? "short"
      : "flat";
  const refForSize = referencePrice ?? finiteNumber(preview?.estimated_fill_price) ?? finiteNumber(preview?.reference_price);
  const maxSizeValue = useMemo(() => {
    if (estimatedMaxQuantity === null || estimatedMaxQuantity.trim() === "") return null;
    const maxQty = finiteNumber(estimatedMaxQuantity);
    if (maxQty === null || maxQty < 0) return null;
    if (maxQty === 0) return 0;
    if (sizeMode === "QUANTITY") return maxQty;
    if (refForSize === null || refForSize <= 0) return null;
    if (sizeMode === "NOTIONAL") return maxQty * refForSize;
    // MARGIN
    return (maxQty * refForSize) / Math.max(1, leverage);
  }, [estimatedMaxQuantity, leverage, refForSize, sizeMode]);
  const derivedSizeShare = useMemo(() => {
    const maximum = maxSizeValue;
    const current = finiteNumber(resolvedSizeInput);
    if (maximum === null || maximum <= 0 || current === null) return 0;
    return Math.max(0, Math.min(100, Math.round((current / maximum) * 100)));
  }, [maxSizeValue, resolvedSizeInput]);
  const displaySizeShare = maxSizeValue === 0 ? 0 : sliderDragging
    ? sliderPct
    : sizeShareIntent === null
      ? derivedSizeShare
      : Math.round(sizeShareIntent * 100);
  const displaySizeShareLabel = maxSizeValue === 0 ? "0"
    : quantityExceedsCapacity ? ">100" : String(displaySizeShare);

  const setSizeShare = (share: number) => {
    const maximum = maxSizeValue;
    if (maximum === null) return;
    const normalizedShare = Math.max(0, Math.min(1, share));
    setSizeShareIntent(normalizedShare);
    setSizeInput(replayQuantityForShare(
      String(maximum), normalizedShare, sizeMode === "QUANTITY" ? quantityStep : quoteStep,
    ) ?? "0");
  };

  const sizeUnit = sizeMode === "QUANTITY" ? quantityAsset : settlementAsset;
  const sizeModeLabel = sizeMode === "QUANTITY"
    ? t("replay.paper.qtyAsset")
    : sizeMode === "MARGIN"
      ? t("replay.paper.marginAmt")
      : t("replay.paper.notionalAmt");

  const ctaEnabled = (nextSide: "BUY" | "SELL"): { enabled: boolean; title: string } => {
    if (positionMode === "HEDGE") {
      if (!reduceOnly) return { enabled: true, title: "" };
      const targetSide = nextSide === "BUY" ? "SHORT" : "LONG";
      const target = portfolio?.positions.find((item) => (
        item.track_id === selectedTrackId && item.position_side === targetSide
      ));
      return target === undefined || (finiteNumber(target.position.quantity) ?? 0) === 0
        ? { enabled: false, title: targetSide === "LONG" ? t("replay.paper.noLong") : t("replay.paper.noShort") }
        : { enabled: true, title: "" };
    }
    if (reduceOnly) {
      if (positionSide === "flat") {
        return { enabled: false, title: t("replay.paper.noPos") };
      }
      if (positionSide === "long") {
        return nextSide === "SELL"
          ? { enabled: true, title: "" }
          : { enabled: false, title: t("replay.paper.longSellOnly") };
      }
      return nextSide === "BUY"
        ? { enabled: true, title: "" }
        : { enabled: false, title: t("replay.paper.shortBuyOnly") };
    }
    if (positionSide === "long" && nextSide === "SELL") {
      return { enabled: false, title: t("replay.paper.hasLong") };
    }
    if (positionSide === "short" && nextSide === "BUY") {
      return { enabled: false, title: t("replay.paper.hasShort") };
    }
    return { enabled: true, title: "" };
  };

  const ctaLabel = (nextSide: "BUY" | "SELL"): string => {
    if (reduceOnly) {
      return nextSide === "BUY" ? t("replay.paper.buyCloseShort") : t("replay.paper.sellCloseLong");
    }
    if (isSpot) {
      return nextSide === "BUY" ? t("replay.paper.buyAsset", { asset: quantityAsset }) : t("replay.paper.sellAsset", { asset: quantityAsset });
    }
    return nextSide === "BUY" ? t("replay.paper.openLongX", { lev: leverage }) : t("replay.paper.openShortX", { lev: leverage });
  };

  const placeOrderWithSide = async (nextSide: "BUY" | "SELL") => {
    const gate = ctaEnabled(nextSide);
    if (
      !gate.enabled
      || !commandReady
      || tradeValidationControllerRef.current !== null
    ) return;
    if (!quantity.trim() || (orderType !== "MARKET" && !price.trim())) {
      setNotice({ tone: "error", message: t("replay.paper.invalidInput") });
      return;
    }
    if (leverage < 1 || leverage > maxLeverage) {
      setNotice({ tone: "error", message: t("replay.paper.levRange", { max: maxLeverage }) });
      return;
    }
    const targetPositionSide: "LONG" | "SHORT" = reduceOnly
      ? nextSide === "BUY" ? "SHORT" : "LONG"
      : nextSide === "BUY" ? "LONG" : "SHORT";
    let order: ReplayOrderRequest = {
      client_order_id: clientOrderId,
      side: nextSide,
      order_type: orderType,
      quantity,
      reduce_only: reduceOnly,
      limit_price: orderType === "LIMIT" ? price : null,
      stop_price: orderType === "STOP_MARKET" || orderType === "TAKE_PROFIT_MARKET" ? price : null,
      leverage: String(leverage),
      ...(positionMode === "HEDGE" ? { position_side: targetPositionSide } : {}),
    };
    const intent = previewPositionIntent;
    const planForSide = tradePlanEnabled && tradePlanEligible && !reduceOnly
      ? tradePlanDraft
      : null;
    const sideForContext = positionMode === "HEDGE"
      ? nextSide
      : replayOrderContextSide(positionQty, nextSide, reduceOnly);
    const targetPositionQty = positionMode === "HEDGE"
      ? finiteNumber(portfolio?.positions.find((item) => (
        item.track_id === selectedTrackId && item.position_side === targetPositionSide
      ))?.position.quantity) ?? 0
      : positionQty;
    const sideContext: ReplayOrderCapacityContext = {
      side: sideForContext,
      order_type: orderType,
      reduce_only: reduceOnly,
      limit_price: orderType === "LIMIT" ? price : null,
      stop_price: orderType === "STOP_MARKET" || orderType === "TAKE_PROFIT_MARKET"
        ? price
        : null,
      leverage: String(leverage),
      ...(positionMode === "HEDGE" ? { position_side: targetPositionSide } : {}),
    };
    const sideAllocation = replayOrderIsolatedAllocation({
      marginMode: contract?.margin_mode,
      positionMode,
      allocations: positionMode === "HEDGE" ? contract?.isolated_wallets : contract?.isolated_allocations,
      trackId: selectedTrackId,
      positionSide: targetPositionSide,
    });
    const sideSizingKey = JSON.stringify([
      selectedTrackId,
      sideAllocation,
      sideForContext,
      orderType,
      reduceOnly,
      intent,
      reduceOnly ? targetPositionQty : null,
    ]);
    const sideContextKey = JSON.stringify([
      selectedTrackId,
      sideAllocation,
      sideForContext,
      orderType,
      reduceOnly,
      intent,
      price,
      leverage,
      reduceOnly ? targetPositionQty : null,
    ]);
    capacityScheduler.cancel();
    previewScheduler.cancel();
    capacityAdvisoryControllerRef.current?.abort();
    previewAdvisoryControllerRef.current?.abort();
    capacityAdvisoryControllerRef.current = null;
    previewAdvisoryControllerRef.current = null;
    const validationController = new AbortController();
    tradeValidationControllerRef.current = validationController;
    setTradeValidationSide(nextSide);
    const validationTimeout = globalThis.setTimeout(() => {
      validationController.abort(
        new DOMException(t("replay.paper.timeout"), "TimeoutError"),
      );
    }, REPLAY_ORDER_VALIDATION_TIMEOUT_MS);
    setNotice({ tone: "pending", message: t("replay.paper.fetchingCap") });
    try {
      const sideCapacity = await orderCapacity(
        sideContext,
        intent,
        validationController.signal,
      );
      setCapacityState({
        key: sideContextKey,
        status: "ready",
        result: sideCapacity,
        error: null,
      });
      setMaxQuantitySnapshot({
        key: sideContextKey,
        sizingKey: sideSizingKey,
        value: sideCapacity.max_quantity,
        referencePrice: finiteNumber(sideCapacity.reference_price),
        availableEquity: sizingAvailableEquity,
        leverage,
      });
      setSide(nextSide);
      if (sizeShareIntent !== null && planForSide === null) {
        const freshQuantity = replayQuantityForShare(
          sideCapacity.max_quantity, sizeShareIntent, quantityStep,
        );
        if (freshQuantity !== null) order = { ...order, quantity: freshQuantity };
      }
      const requestedQuantity = finiteNumber(order.quantity);
      const maximumQuantity = finiteNumber(sideCapacity.max_quantity);
      if (
        requestedQuantity === null
        || maximumQuantity === null
        || requestedQuantity > maximumQuantity
      ) {
        setNotice({
          tone: "error",
          message: t("replay.paper.overCap", { qty: formatDecimal(sideCapacity.max_quantity, 8), asset: quantityAsset }),
        });
        return;
      }
      setNotice({ tone: "pending", message: t("replay.paper.previewing") });
      const sidePreview = await previewOrder(
        order,
        intent,
        planForSide,
        validationController.signal,
      );
      if (sidePreview.order.side !== nextSide) {
        setNotice({ tone: "error", message: t("replay.paper.sideMismatch") });
        return;
      }
      if (
        sidePreview.cursor.revision !== store.revision
        || sidePreview.cursor.source_sequence !== store.sourceSequence
        || sidePreview.cursor.virtual_time_ms !== store.virtualTimeMs
      ) {
        setNotice({ tone: "error", message: t("replay.paper.cursorChanged") });
        return;
      }
      setNotice({ tone: "pending", message: t("replay.paper.submittingOrder") });
      const planned = sidePreview.trade_plan;
      if (planned !== null && planForSide !== null) {
        await viewer.actions.submitTrade("place_order", {
          ...order,
          quantity: planned.quantity,
          trade_plan: { ...planForSide },
        });
      } else if (orderType === "MARKET" && !reduceOnly) {
        await viewer.actions.submitTrade("execute_position_intent", {
          intent: "OPEN",
          side: nextSide,
          quantity: order.quantity,
          leverage: String(leverage),
          ...(positionMode === "HEDGE" ? { position_side: targetPositionSide } : {}),
        });
      } else {
        await viewer.actions.submitTrade("place_order", { ...order });
      }
      setClientOrderId(orderClientId());
      if (planned !== null) {
        setInvalidationPrice("");
        setTargetPrice("");
        setTradeReason("");
      }
      setPreviewState(null);
      setNotice({ tone: "success", message: t("replay.paper.accepted") });
    } catch (error) {
      if (tradeValidationMountedRef.current) {
        setNotice({ tone: "error", message: commandErrorMessage(error) });
      }
    } finally {
      globalThis.clearTimeout(validationTimeout);
      if (tradeValidationControllerRef.current === validationController) {
        tradeValidationControllerRef.current = null;
        if (tradeValidationMountedRef.current) setTradeValidationSide(null);
      }
    }
  };

  const buyGate = ctaEnabled("BUY");
  const sellGate = ctaEnabled("SELL");
  const orderSubmitting = tradeValidationSide !== null;
  // Submission cancels advisory requests and validates fresh same-cursor
  // capacity/preview. A background quote must not consume an otherwise valid
  // pointer or keyboard activation while its response is in flight.
  const transientOrderBlock = !commandReady;
  const commonPermanentOrderBlock = !commandAvailable
    || !quantity.trim()
    || (orderType !== "MARKET" && !price.trim());
  const sideExceedsCapacity = (nextSide: "BUY" | "SELL") => {
    const targetPositionSide = nextSide === "BUY" ? "SHORT" : "LONG";
    const targetQuantity = positionMode === "HEDGE"
      ? finiteNumber(portfolio?.positions.find((item) => (
        item.track_id === selectedTrackId && item.position_side === targetPositionSide
      ))?.position.quantity) ?? 0
      : positionQty;
    return replayOrderSizingAvailability(replayOrderSideCapacity(
      estimatedMaxQuantity, previewSide, nextSide, reduceOnly, targetQuantity,
    ), quantity).quantityExceedsCapacity;
  };
  const buyCtaState = replayOrderCtaState({
    permanentlyUnavailable: commonPermanentOrderBlock || !buyGate.enabled || sideExceedsCapacity("BUY"),
    transientlyBlocked: transientOrderBlock,
    submitting: orderSubmitting,
  });
  const sellCtaState = replayOrderCtaState({
    permanentlyUnavailable: commonPermanentOrderBlock || !sellGate.enabled || sideExceedsCapacity("SELL"),
    transientlyBlocked: transientOrderBlock,
    submitting: orderSubmitting,
  });
  const leverageOptions = useMemo(() => {
    const presets = [1, 2, 3, 5, 10, 20, 25, 50, 75, 100, 125].filter((value) => value <= maxLeverage);
    if (!presets.includes(Math.trunc(maxLeverage)) && maxLeverage >= 1) {
      presets.push(Math.trunc(maxLeverage));
    }
    if (!presets.includes(leverage) && leverage >= 1 && leverage <= maxLeverage) {
      presets.push(leverage);
    }
    return [...new Set(presets)].sort((a, b) => a - b);
  }, [leverage, maxLeverage]);

  const orderTypeTabs = [
    ["MARKET", t("replay.paper.typeMarket")],
    ["LIMIT", t("replay.paper.typeLimit")],
    ["STOP_MARKET", t("replay.paper.stopMkt")],
    ["TAKE_PROFIT_MARKET", t("replay.paper.tpMkt")],
  ] as const;
  const positionPnl = finiteNumber(selectedPosition?.position.unrealized_pnl);
  // Silent while idle; only surface progress, a rejection, or a blocking reason.
  const ticketMessage = notice?.message ?? reduceOnlyUnavailableMessage
    ?? capacityValidationError
    ?? capacityError
    ?? previewError
    ?? viewer.error
    ?? null;
  const ticketMessageTone = notice?.tone ?? (ticketMessage === null ? "idle" : "error");

  const unitInput = (input: ReactNode, unit: string) => (
    <span className="replay-unit-input">{input}<span className="replay-unit-input-unit">{unit}</span></span>
  );

  return (
    <div className="replay-paper-trading" data-replay-paper-surface="order-ticket">
    <div className="replay-order-surface">
      <div className="replay-ticket-scroll">
        <header className="replay-ticket-account">
          <div className="replay-ticket-context">
            <strong>{symbol}</strong>
            <span>{isSpot ? t("replay.paper.spot") : t("replay.paper.futures")}</span>
            <span className="replay-ticket-locks">
              {contract?.margin_mode === "ISOLATED" ? t("replay.wb.isolated") : t("replay.wb.cross")}
              {" · "}
              {positionMode === "HEDGE" ? t("replay.paper.hedge") : t("replay.paper.oneWay")}
            </span>
            <Select
              size="sm"
              className="replay-leverage-control"
              value={String(leverage)}
              title={t("replay.paper.levCap")}
              aria-label={t("replay.paper.leverageMax", { max: maxLeverage })}
              onChange={(event) => setLeverage(Math.min(maxLeverage, Math.max(1, Number(event.target.value) || 1)))}
            >
              {leverageOptions.map((value) => (
                <option key={value} value={value}>{value}x</option>
              ))}
            </Select>
          </div>
          <div className="replay-ticket-balance">
            <Stat label={t("replay.wb.equity")} value={<>{formatDecimal(portfolio?.equity ?? store.account?.equity, 2)} <small>{settlementAsset}</small></>} />
            <Stat label={t("replay.wb.available")} value={<>{formatDecimal(portfolio?.available_equity ?? store.account?.available_equity, 2)} <small>{settlementAsset}</small></>} />
          </div>
          {positionSide !== "flat" && (
            <p className="replay-ticket-position" data-position-side={positionSide}>
              <Badge tone={positionSide === "long" ? "success" : "danger"}>{positionSide === "long" ? t("replay.wb.long") : t("replay.wb.short")}</Badge>
              <span>{formatDecimal(Math.abs(positionQty))} {quantityAsset}</span>
              <span>{t("replay.wb.floatPnl")} <b data-value-tone={(positionPnl ?? 0) >= 0 ? "positive" : "negative"}>{formatDecimal(positionPnl, 2)}</b></span>
            </p>
          )}
        </header>

        <section className="replay-compact-ticket" data-replay-panel="order-ticket">
          <SegmentedControl
            fullWidth
            label={t("replay.paper.openClose")}
            value={reduceOnly ? "close" : "open"}
            options={[
              { value: "open", label: t("replay.paper.open") },
              { value: "close", label: t("replay.paper.close") },
            ]}
            onChange={(mode) => {
              const nextReduceOnly = mode === "close";
              if (nextReduceOnly !== reduceOnly) setSide(side === "BUY" ? "SELL" : "BUY");
              setReduceOnly(nextReduceOnly);
            }}
          />

          <Tabs
            id={orderTypeTabsId}
            label={t("replay.paper.orderType")}
            value={orderType}
            tabs={orderTypeTabs.map(([value, label]) => ({ value, label }))}
            onChange={setOrderType}
          />

          <TabPanel tabsId={orderTypeTabsId} value={orderType} className="replay-ticket-fields">
            {orderType !== "MARKET" && (
              <Field label={orderType === "LIMIT" ? t("replay.paper.limitPrice") : t("replay.paper.triggerPrice")}>
                {unitInput(<Input size="sm" data-replay-field="order-price" value={price} inputMode="decimal" onChange={(event) => setPrice(event.target.value)} />, settlementAsset)}
              </Field>
            )}
            <Field label={sizeModeLabel} hint={sizeMode !== "QUANTITY"
              ? `${t("replay.paper.approxQty", { qty: quantity || "--", asset: quantityAsset })}${refForSize !== null ? t("replay.paper.refPrice", { price: formatDecimal(refForSize, 6) }) : ""}`
              : undefined}>
              <span className="replay-size-input">
                <Input
                  size="sm"
                  data-replay-field="order-quantity"
                  value={resolvedSizeInput}
                  inputMode="decimal"
                  aria-invalid={quantityExceedsCapacity || undefined}
                  aria-describedby="replay-order-size-feedback"
                  onChange={(event) => {
                    setSizeShareIntent(null);
                    setSizeInput(event.target.value);
                  }}
                />
                <Select
                  size="sm"
                  id={sizeUnitId}
                  aria-label={t("replay.paper.sizeMode")}
                  value={sizeMode}
                  onChange={(event) => setSizeMode(event.target.value as SizeMode)}
                >
                  <option value="QUANTITY">{quantityAsset}</option>
                  <option value="MARGIN">{t("replay.paper.margin")} · {settlementAsset}</option>
                  <option value="NOTIONAL">{t("replay.paper.notional")} · {settlementAsset}</option>
                </Select>
              </span>
            </Field>

            <div
              className="replay-size-slider"
              role="group"
              aria-label={t("replay.paper.posShare")}
              style={{ ["--replay-size-pct" as string]: `${displaySizeShare}%` }}
            >
              <input
                type="range"
                aria-label={t("replay.paper.sizeQuick")}
                min={0}
                max={100}
                step={1}
                value={displaySizeShare}
                disabled={sizingAvailability.sliderDisabled || maxSizeValue === null}
                onPointerDown={() => {
                  setSliderDragging(true);
                  setSliderPct(displaySizeShare);
                }}
                onPointerUp={() => setSliderDragging(false)}
                onPointerCancel={() => setSliderDragging(false)}
                onLostPointerCapture={() => setSliderDragging(false)}
                onBlur={() => setSliderDragging(false)}
                onKeyUp={() => setSliderDragging(false)}
                onInput={(event) => {
                  const pct = Number((event.target as HTMLInputElement).value);
                  setSliderDragging(true);
                  setSliderPct(pct);
                  setSizeShare(pct / 100);
                }}
                onChange={(event) => {
                  const pct = Number(event.target.value);
                  setSliderPct(pct);
                  setSizeShare(pct / 100);
                }}
              />
              <div className="replay-size-slider-ticks">
                {[0.25, 0.5, 0.75, 1].map((share) => (
                  <Button
                    key={share}
                    size="sm"
                    variant="ghost"
                    disabled={sizingAvailability.sliderDisabled || maxSizeValue === null}
                    onClick={() => setSizeShare(share)}
                  >{share * 100}%</Button>
                ))}
              </div>
              <div className="replay-size-slider-meta">
                <span>
                  {t("replay.paper.refMax", {
                    value: maxSizeValue === null ? "--" : formatDecimal(maxSizeValue, sizeMode === "QUANTITY" ? 8 : 2),
                    unit: sizeUnit,
                  })}
                  {sizeMode !== "QUANTITY" && estimatedMaxQuantity !== null
                    ? ` · ${formatDecimal(estimatedMaxQuantity)} ${quantityAsset}`
                    : ""}
                </span>
                <span>{displaySizeShareLabel}%</span>
              </div>
            </div>
          </TabPanel>

          <dl className="replay-order-preview" aria-label={t("replay.paper.orderPreview")}>
            <div><dt>{t("replay.paper.notionalVal")}</dt><dd>{previewPending ? t("replay.paper.checking") : `${formatDecimal(preview?.estimated_notional, 2)} ${settlementAsset}`}</dd></div>
            <div><dt>{t("replay.paper.orderBudget")}</dt><dd>{formatDecimal(preview?.reserved_margin, 8)} {settlementAsset}</dd></div>
            <div><dt>{t("replay.paper.feeCap")}</dt><dd>{formatDecimal(preview?.estimated_fee, 8)} {settlementAsset}</dd></div>
          </dl>

          <div className="replay-trade-plan">
            <Checkbox
              label={t("replay.paper.riskPlan")}
              checked={tradePlanEnabled && tradePlanEligible}
              disabled={!tradePlanEligible}
              onChange={(event) => setTradePlanEnabled(event.target.checked)}
            />
            {tradePlanEnabled && tradePlanEligible && (
              <div className="replay-trade-plan-fields">
                <Field label={t("replay.paper.riskMode")}>
                  <Select
                    size="sm"
                    value={riskSizingMode}
                    onChange={(event) => setRiskSizingMode(event.target.value as typeof riskSizingMode)}
                  >
                    <option value="ACCOUNT_RISK_PERCENT">{t("replay.paper.accountRiskPct")}</option>
                    <option value="RISK_AMOUNT">{t("replay.paper.riskAmt")}</option>
                  </Select>
                </Field>
                <Field label={riskSizingMode === "RISK_AMOUNT" ? t("replay.paper.maxLoss") : t("replay.paper.accountRisk")}>
                  {unitInput(<Input size="sm" value={riskValue} inputMode="decimal" onChange={(event) => setRiskValue(event.target.value)} />, riskSizingMode === "RISK_AMOUNT" ? settlementAsset : "%")}
                </Field>
                <Field label={t("replay.paper.invalidPx")}>
                  {unitInput(<Input size="sm" value={invalidationPrice} inputMode="decimal" onChange={(event) => setInvalidationPrice(event.target.value)} />, settlementAsset)}
                </Field>
                <Field label={t("replay.paper.targetPx")}>
                  {unitInput(<Input size="sm" value={targetPrice} inputMode="decimal" onChange={(event) => setTargetPrice(event.target.value)} />, settlementAsset)}
                </Field>
                <Field label={t("replay.paper.reason")} className="replay-trade-plan-reason" hint={t("replay.paper.planHint")}>
                  <Textarea value={tradeReason} maxLength={500} rows={3} onChange={(event) => setTradeReason(event.target.value)} placeholder={t("replay.paper.reasonPh")} />
                </Field>
                <dl className="replay-order-preview" aria-label={t("replay.paper.planPreview")}>
                  <div><dt>{t("replay.paper.planQty")}</dt><dd>{preview?.trade_plan?.quantity ?? "--"} {quantityAsset}</dd></div>
                  <div><dt>{t("replay.paper.planRisk")}</dt><dd>{preview?.trade_plan?.risk_amount ?? "--"} {settlementAsset}</dd></div>
                  <div><dt>{t("replay.paper.planRR")}</dt><dd>{preview?.trade_plan?.reward_risk_ratio ?? "--"}</dd></div>
                </dl>
              </div>
            )}
          </div>
        </section>
      </div>

      <footer className="replay-ticket-footer">
        <div id="replay-order-size-feedback" className="replay-trade-notice" role={ticketMessageTone === "error" ? "alert" : "status"} aria-live="polite" data-tone={ticketMessageTone}>
          {ticketMessage}
        </div>
        <div className="replay-dual-cta">
          <button
            type="button"
            className="replay-submit-order"
            data-side="BUY"
            data-replay-action="place-order"
            data-replay-transient-blocked={transientOrderBlock ? "true" : "false"}
            title={buyGate.title || undefined}
            disabled={buyCtaState.disabled}
            aria-disabled={buyCtaState.ariaDisabled}
            onClick={() => void placeOrderWithSide("BUY")}
          >{tradeValidationSide === "BUY" ? t("replay.paper.submitting") : ctaLabel("BUY")}</button>
          <button
            type="button"
            className="replay-submit-order"
            data-side="SELL"
            data-replay-action="place-order"
            data-replay-transient-blocked={transientOrderBlock ? "true" : "false"}
            title={sellGate.title || undefined}
            disabled={sellCtaState.disabled}
            aria-disabled={sellCtaState.ariaDisabled}
            onClick={() => void placeOrderWithSide("SELL")}
          >{tradeValidationSide === "SELL" ? t("replay.paper.submitting") : ctaLabel("SELL")}</button>
        </div>
        <small className="replay-order-fidelity" data-fidelity={contract?.execution_fidelity ?? "LOADING"} title={t("replay.paper.submitHint")}>
          {contract?.execution_fidelity === "BOOK_ASSISTED_CONTINUITY_GATED_NO_QUEUE"
            ? t("replay.paper.l2Assist")
            : t("replay.paper.approxFill")}
        </small>
      </footer>
    </div>
    </div>
  );
}

export function ReplayTradingWorkbench({ runtime, viewer, formatTime }: Pick<ReplayRightRailProps, "runtime" | "viewer" | "formatTime">) {
  const { api } = useReplayOperations(viewer.viewerState?.run_id, "rail");
  useLocale();
  const recordTabsId = useId();
  const [activeTab, setActiveTab] = useState<WorkbenchTab>("positions");
  const [orderSelection, setOrderSelection] = useState<Readonly<{
    trackId: string;
    orderIds: readonly string[];
  }>>({ trackId: "", orderIds: [] });
  const [replaceDraft, setReplaceDraft] = useState<Readonly<{
    trackId: string;
    orderId: string;
    quantity: string;
    price: string;
  }> | null>(null);
  const [closeDraft, setCloseDraft] = useState<Readonly<{
    trackId: string;
    positionSide?: "LONG" | "SHORT";
    value: string;
  }> | null>(null);
  const [protectionDraft, setProtectionDraft] = useState<Readonly<{
    trackId: string;
    positionSide?: "LONG" | "SHORT";
    stopLoss: string;
    takeProfit: string;
  }> | null>(null);
  const [leverageDraft, setLeverageDraft] = useState<Readonly<{
    trackId: string;
    positionSide: "LONG" | "SHORT";
    value: string;
  }> | null>(null);
  const [positionPanel, setPositionPanel] = useState<Readonly<{
    trackId: string;
    positionSide?: "LONG" | "SHORT";
    kind: "close" | "protection" | "leverage";
  }> | null>(null);
  const [filterSelectedTrackOnly, setFilterSelectedTrackOnly] = useState(false);
  const closeQtyInputRef = useRef<HTMLInputElement | null>(null);
  const [isolatedAmount, setIsolatedAmount] = useState("0");
  const [isolatedSide, setIsolatedSide] = useState<"LONG" | "SHORT">("LONG");
  const [notice, setNotice] = useState<TradeNotice>(null);
  useTradeNoticeAutoDismiss(notice, setNotice);
  const [reportSnapshot, setReportSnapshot] = useState<Readonly<{
    runId: string;
    state: "loaded" | "error";
    trades: readonly ReplayClosedTrade[];
  }> | null>(null);
  const store = runtime.store;
  const config = store.sessionConfig;
  const ownsController = replayOwnsController(store, runtime.clientInstanceId);
  const commandReady = ownsController
    && store.connectionState === "connected"
    && runtime.pendingCommand === null
    && !viewer.viewerPending
    && store.state !== "ENDED";
  const portfolio = viewer.marketTracks?.portfolio ?? null;
  const accountView = portfolio ?? store.account;
  const accountPnl = finiteNumber(accountView?.unrealized_pnl);
  const pnlTone = accountPnl === null ? undefined : accountPnl >= 0 ? "positive" : "negative";
  const contract = contractPortfolio(portfolio);
  const selectedTrackId = viewer.viewerState?.selected_track_id ?? "track-1";
  const selectedTrack = viewer.marketTracks?.tracks.find((item) => item.track_id === selectedTrackId) ?? null;
  const settlementAsset = selectedTrack?.settlement_asset ?? store.account?.quote_asset ?? "";
  const selectedSymbol = selectedTrack?.symbol ?? config?.symbol ?? "--";
  const portfolioPositions = portfolio?.positions ?? [];
  const positionTrackCount = new Set(portfolioPositions.map((item) => item.track_id)).size;
  const visiblePositions = filterSelectedTrackOnly
    ? portfolioPositions.filter((item) => item.track_id === selectedTrackId)
    : portfolioPositions;
  const selectedPosition = portfolioPositions.find((item) => item.track_id === selectedTrackId) ?? null;
  const structuredOrders: readonly JsonRecord[] = useMemo(() => contract?.orders
    ?? store.orders.map((order) => order as unknown as JsonRecord), [contract, store.orders]);
  const structuredFills: readonly JsonRecord[] = useMemo(() => contract?.fills
    ?? store.fills.map((fill) => fill as unknown as JsonRecord), [contract, store.fills]);
  const openOrders = useMemo(() => structuredOrders.filter((order) => (
    !TERMINAL_ORDER_STATES.has(recordText(order, "status", "OPEN"))
  )), [structuredOrders]);
  const selectedOrderIds = orderSelection.trackId === selectedTrackId
    ? orderSelection.orderIds.filter((orderId) => openOrders.some((order) => (
        recordText(order, "order_id") === orderId
        && recordText(order, "track_id", selectedTrackId) === selectedTrackId
      )))
    : [];
  const fallbackHistoricalOrders = useMemo(() => structuredOrders.filter((order) => (
    TERMINAL_ORDER_STATES.has(recordText(order, "status", "OPEN"))
  )), [structuredOrders]);
  const runId = viewer.viewerState?.run_id ?? null;
  const historicalOrderPages = useAccountRecordPages({
    runId,
    recordType: "ORDERS",
    orderScope: "HISTORY",
    enabled: contract !== null && activeTab === "order-history",
    revision: contract?.history.historical_orders ?? 0,
  });
  const fillPages = useAccountRecordPages({
    runId,
    recordType: "FILLS",
    orderScope: "ALL",
    enabled: contract !== null && activeTab === "fills",
    revision: contract?.history.fills_total ?? 0,
  });
  const ledgerPages = useAccountRecordPages({
    runId,
    recordType: "LEDGER",
    orderScope: "ALL",
    enabled: contract !== null && activeTab === "risk",
    revision: contract?.history.ledger_entries_total ?? 0,
  });
  const historicalOrders = contract === null
    ? [...fallbackHistoricalOrders].reverse()
    : historicalOrderPages.items;
  const visibleFills = contract === null
    ? [...structuredFills].slice(-REPLAY_ACTIVITY_VIEW_LIMIT).reverse()
    : fillPages.items;
  const fallbackClosedTrades = runtime.report?.report.closed_trades ?? store.closedTrades;
  const currentReport = reportSnapshot?.runId === runId ? reportSnapshot : null;
  const reportState = runId === null ? "idle" : currentReport?.state ?? "loading";
  const reportClosedTrades = currentReport?.trades ?? [];
  const closedTrades = reportState === "loaded" ? reportClosedTrades : fallbackClosedTrades;
  const recentClosedTrades = useMemo(() => recentReplayActivity(closedTrades), [closedTrades]);
  const rule = selectedRule(contract, selectedTrackId);
  const quantityStep = recordText(rule ?? {}, "quantity_step", "0.00000001");
  const selectedPositionSignedQuantity = finiteNumber(selectedPosition?.position.quantity) ?? 0;
  const selectedPositionQuantity = Math.abs(selectedPositionSignedQuantity);
  const defaultCloseQuantity = selectedPositionQuantity > 0
    ? quantityForStep(selectedPositionQuantity, quantityStep)
    : "";
  const closeQuantity = closeDraft?.trackId === selectedTrackId
    ? closeDraft.value
    : defaultCloseQuantity;
  const warningCount = store.warnings.length;

  const time = (value: number) => formatTime?.(value)
    ?? formatReplayPublicTime(value, {
      blindMode: config?.blind_mode ?? true,
      originMs: store.replayStartMs,
    });

  useEffect(() => {
    if (runId === null) return undefined;
    const controller = new AbortController();
    void api.reportRun(runId, controller.signal).then((response) => {
      setReportSnapshot({ runId, state: "loaded", trades: response.report.closed_trades });
    }).catch((error: unknown) => {
      if (controller.signal.aborted) return;
      setReportSnapshot({ runId, state: "error", trades: [] });
      setNotice({ tone: "error", message: t("replay.paper.closedSyncFailed", { error: commandErrorMessage(error) }) });
    });
    return () => controller.abort();
  }, [api, contract?.history.fills_total, runId, structuredFills.length]);

  useEffect(() => {
    if (positionPanel?.kind !== "close" || positionPanel.trackId !== selectedTrackId) return;
    const timer = globalThis.setTimeout(() => {
      closeQtyInputRef.current?.focus();
      closeQtyInputRef.current?.select();
    }, 0);
    return () => globalThis.clearTimeout(timer);
  }, [positionPanel, selectedTrackId]);

  const togglePositionPanel = (
    trackId: string,
    kind: "close" | "protection" | "leverage",
    positionSide?: "LONG" | "SHORT",
  ) => {
    setPositionPanel((current) => (
      current?.trackId === trackId
        && current.kind === kind
        && current.positionSide === positionSide
        ? null
        : { trackId, kind, ...(positionSide === undefined ? {} : { positionSide }) }
    ));
  };

  const runTrade = async (
    type: TradeType,
    payload: Readonly<Record<string, ReplayV2Json>>,
    pendingMessage: string,
    successMessage: string,
  ) => {
    setNotice({ tone: "pending", message: pendingMessage });
    try {
      await viewer.actions.submitTrade(type, payload);
      setNotice({ tone: "success", message: successMessage });
      if (type === "close_position" || payload.intent === "CLOSE") setCloseDraft(null);
      if (type === "replace_order") setReplaceDraft(null);
      if (type === "cancel_order" || type === "cancel_orders") {
        setOrderSelection({ trackId: selectedTrackId, orderIds: [] });
      }
    } catch (error) {
      setNotice({ tone: "error", message: commandErrorMessage(error) });
    }
  };

  const selectedTrackOpenOrders = openOrders.filter((order) => (
    recordText(order, "track_id", selectedTrackId) === selectedTrackId
  ));
  const toggleSelectedOrder = (orderId: string, checked: boolean) => {
    setOrderSelection((current) => {
      const orderIds = current.trackId === selectedTrackId ? current.orderIds : [];
      return {
        trackId: selectedTrackId,
        orderIds: checked
          ? orderIds.includes(orderId) ? orderIds : [...orderIds, orderId]
          : orderIds.filter((value) => value !== orderId),
      };
    });
  };
  const replaceOrder = (order: JsonRecord) => {
    const orderId = recordText(order, "order_id");
    const orderTypeValue = recordText(order, "order_type");
    const draft = replaceDraft?.trackId === selectedTrackId
      && replaceDraft.orderId === orderId
      ? replaceDraft
      : null;
    if (draft === null) return;
    void runTrade(
      "replace_order",
      {
        order_id: orderId,
        client_order_id: orderClientId().replace(/^ticket-/, "replace-"),
        quantity: draft.quantity,
        limit_price: orderTypeValue === "LIMIT" ? draft.price : null,
        stop_price: orderTypeValue === "STOP_MARKET" || orderTypeValue === "TAKE_PROFIT_MARKET"
          ? draft.price
          : null,
      },
      t("replay.paper.replacing"),
      t("replay.paper.replaced"),
    );
  };

  const symbolForTrack = (trackId: string) => viewer.marketTracks?.tracks.find((track) => track.track_id === trackId)?.symbol ?? trackId;
  const tabCounts: Readonly<Partial<Record<WorkbenchTab, number>>> = {
    positions: portfolioPositions.length,
    "open-orders": openOrders.length,
    "order-history": contract?.history.historical_orders ?? historicalOrders.length,
    fills: contract?.history.fills_total ?? structuredFills.length,
  };
  const orderStatusTone = (status: string) => status === "FILLED" ? "success" as const
    : status === "REJECTED" || status === "EXPIRED" ? "danger" as const
      : TERMINAL_ORDER_STATES.has(status) ? "neutral" as const : "accent" as const;
  const unitInput = (input: ReactNode, unit: string) => (
    <span className="replay-unit-input">{input}<span className="replay-unit-input-unit">{unit}</span></span>
  );
  const loadMoreButton = (page: Readonly<{ nextCursor: string | null; loadingMore: boolean; items: readonly unknown[]; totalCount: number; loadMore: () => Promise<void> }>) => (
    page.nextCursor !== null && (
      <Button size="sm" variant="ghost" className="replay-record-more" disabled={page.loadingMore} onClick={() => void page.loadMore()}>
        {page.loadingMore ? t("replay.wb.loading") : t("replay.wb.loadMore", { shown: page.items.length, total: page.totalCount })}
      </Button>
    )
  );

  return (
    <section className="replay-trading-workbench" data-replay-workbench="rail" aria-label={t("replay.wb.accountAria")}>
      <header className="replay-workbench-header">
        <div className="replay-workbench-summary">
          <Stat label={settlementAsset ? `${t("replay.wb.equity")} · ${settlementAsset}` : t("replay.wb.equity")} value={formatDecimal(accountView?.equity, 2)} />
          <Stat label={t("replay.wb.available")} value={formatDecimal(accountView?.available_equity, 2)} />
          <Stat
            label={t("replay.wb.floatPnl")}
            value={formatDecimal(accountView?.unrealized_pnl, 2)}
            tone={pnlTone === "positive" ? "success" : pnlTone === "negative" ? "danger" : "neutral"}
          />
          {warningCount > 0 && <Badge tone="warning">{t("replay.wb.execWarnings", { count: warningCount })}</Badge>}
        </div>
        <Tabs
          id={recordTabsId}
          label={t("replay.wb.recordsAria")}
          value={activeTab}
          tabs={WORKBENCH_TAB_IDS.map((value) => ({
            value,
            label: workbenchTabLabel(value),
            ...(tabCounts[value] !== undefined ? { badge: tabCounts[value] } : {}),
          }))}
          onChange={setActiveTab}
        />
      </header>

      <TabPanel tabsId={recordTabsId} value={activeTab} className="replay-workbench-panel">
        {notice !== null && (
          <InlineAlert
            tone={notice.tone === "error" ? "danger" : notice.tone === "success" ? "success" : "info"}
          >{notice.message}</InlineAlert>
        )}

        {activeTab === "positions" && (
          <div className="replay-rail-account-scroll" data-replay-panel="positions">
            {positionTrackCount > 1 && (
              <div className="replay-account-toolbar">
                <Checkbox
                  label={t("replay.wb.currentSymbol")}
                  checked={filterSelectedTrackOnly}
                  onChange={(event) => setFilterSelectedTrackOnly(event.target.checked)}
                />
                <small>{selectedSymbol}</small>
              </div>
            )}
            {portfolioPositions.length === 0 ? (
              <EmptyState compact title={t("replay.wb.noPos")} description={t("replay.wb.noPosHint")} />
            ) : visiblePositions.length === 0 ? (
              <EmptyState compact title={t("replay.wb.noPosSymbol")} description={t("replay.wb.noPosSymbolHint")} />
            ) : visiblePositions.map((item) => {
              const quantityValue = finiteNumber(item.position.quantity) ?? 0;
              const positionSide = quantityValue >= 0 ? "long" : "short";
              const hedgePositionSide = item.position_side;
              const selected = item.track_id === selectedTrackId;
              const samePanelLeg = positionPanel?.positionSide === hedgePositionSide;
              const showClose = selected && positionPanel?.trackId === item.track_id && samePanelLeg && positionPanel.kind === "close";
              const showProtection = selected && positionPanel?.trackId === item.track_id && samePanelLeg && positionPanel.kind === "protection";
              const showLeverage = selected && positionPanel?.trackId === item.track_id && samePanelLeg && positionPanel.kind === "leverage";
              const uPnl = finiteNumber(item.position.unrealized_pnl) ?? 0;
              const maintenanceTierExtrapolated = (
                item.maintenance_margin_proof?.position_tier_extrapolated === true
              );
              const liquidationTierExtrapolated = (
                item.maintenance_margin_proof?.liquidation_tier_extrapolated === true
              );
              const maintenanceProofTitle = item.maintenance_margin_proof === undefined
                ? t("replay.wb.mmUndeclaredShort")
                : maintenanceTierExtrapolated
                ? t("replay.wb.mmOverCap", { cap: item.maintenance_margin_proof?.last_tier_notional_cap ?? "--" })
                : t("replay.wb.mmVersioned");
              const marginLabel = item.margin_equity ?? item.isolated_margin ?? null;
              const protectionOrders = item.protection?.orders ?? [];
              const itemQtyAsset = baseAsset(item.symbol, settlementAsset);
              const itemCloseQuantity = closeDraft?.trackId === item.track_id
                && closeDraft.positionSide === hedgePositionSide
                ? closeDraft.value
                : quantityForStep(Math.abs(quantityValue), quantityStep);
              const itemStopLossPrice = protectionDraft?.trackId === item.track_id
                && protectionDraft.positionSide === hedgePositionSide
                ? protectionDraft.stopLoss
                : "";
              const itemTakeProfitPrice = protectionDraft?.trackId === item.track_id
                && protectionDraft.positionSide === hedgePositionSide
                ? protectionDraft.takeProfit
                : "";
              const itemLeverage = leverageDraft?.trackId === item.track_id
                && leverageDraft.positionSide === hedgePositionSide
                ? leverageDraft.value
                : String(item.leverage ?? config?.max_leverage ?? "");
              const legPayload = hedgePositionSide === undefined
                ? {}
                : { position_side: hedgePositionSide };
              return (
                <article className="replay-position-card" key={`${item.track_id}:${hedgePositionSide ?? "NET"}`} data-position-side={positionSide} data-selected-track={selected ? "true" : "false"}>
                  <header className="replay-record-head">
                    <div className="replay-record-title">
                      <strong>{item.symbol}</strong>
                      <span className="replay-badge-row">
                        <Badge tone={positionSide === "long" ? "success" : "danger"}>{positionSide === "long" ? t("replay.wb.long") : t("replay.wb.short")}</Badge>
                        <Badge>{contract?.margin_mode === "ISOLATED" ? t("replay.wb.isolated") : t("replay.wb.cross")}</Badge>
                        <Badge title={t("replay.wb.legLev")}>{item.leverage ?? config?.max_leverage ?? "--"}x</Badge>
                      </span>
                    </div>
                    <div className="replay-position-pnl">
                      <small>{t("replay.wb.pnl", { asset: settlementAsset })}</small>
                      <b data-value-tone={uPnl >= 0 ? "positive" : "negative"}>{formatDecimal(item.position.unrealized_pnl, 4)}</b>
                    </div>
                  </header>
                  <dl className="replay-metric-flat">
                     <div><dt>{t("replay.wb.qty", { asset: itemQtyAsset })}</dt><dd>{formatDecimal(Math.abs(quantityValue))}</dd></div>
                     <div><dt>{t("replay.wb.entry")}</dt><dd>{formatDecimal(item.position.entry_price, 6)}</dd></div>
                     <div>
                       <dt title={item.mark_fidelity ?? t("replay.wb.markUndeclared")}>{t("replay.wb.mark", { fidelity: replayMarkFidelityLabel(item.mark_fidelity) })}</dt>
                       <dd>{formatDecimal(replayPositiveModelPrice(item.position.mark_price), 6)}</dd>
                     </div>
                     <div title={liquidationTierExtrapolated
                       ? t("replay.wb.liqSearchOver", { cap: item.maintenance_margin_proof?.last_tier_notional_cap ?? "--" })
                       : t("replay.wb.simRisk")}><dt>{t("replay.wb.liqPrice", { extra: liquidationTierExtrapolated ? t("replay.wb.liqExtrap") : "" })}</dt><dd>{formatDecimal(replayPositiveModelPrice(item.liquidation_price), 6)}</dd></div>
                     <div><dt>{t("replay.wb.im")}</dt><dd>{formatDecimal(item.initial_margin, 4)}</dd></div>
                     <div title={maintenanceProofTitle}><dt>{t("replay.wb.mm")}{maintenanceTierExtrapolated ? t("replay.wb.mmExtrap") : ""}</dt><dd>{formatDecimal(item.maintenance_margin, 4)}</dd></div>
                     <div><dt>{t("replay.wb.riskCover")}</dt><dd>{item.risk_ratio == null ? "--" : `${formatDecimal(item.risk_ratio, 2)}×`}</dd></div>
                     <div><dt>{t("replay.wb.lev")}</dt><dd>{formatDecimal(item.leverage, 2)}x</dd></div>
                     <div title={t("replay.wb.simRisk")}><dt>{t("replay.wb.bankruptcy")}</dt><dd>{formatDecimal(replayPositiveModelPrice(item.bankruptcy_price), 6)}</dd></div>
                     <div><dt>{t("replay.wb.fundingAcc")}</dt><dd>{formatDecimal(item.accumulated_funding, 8)}</dd></div>
                     <div className="wide"><dt>{t("replay.wb.protection")}</dt><dd>{protectionOrders.length === 0
                       ? t("replay.wb.none")
                       : protectionOrders.map((order) => `${order.order_type === "STOP_MARKET" ? t("replay.wb.stop") : t("replay.wb.tp")} ${formatDecimal(order.stop_price, 6)}`).join(" · ")}</dd></div>
                    {marginLabel !== null && (
                      <div className="wide"><dt>{t("replay.wb.marginEquity")}</dt><dd>{formatDecimal(marginLabel, 4)} {settlementAsset}</dd></div>
                    )}
                  </dl>
                  {!selected && (
                    <Button size="sm" disabled={viewer.viewerPending} onClick={() => {
                      const activate = viewer.actions.openTrack
                        ? viewer.actions.openTrack(item.track_id, "current")
                        : viewer.actions.selectTrack(item.track_id);
                      void activate.catch(() => undefined);
                    }}>
                      {t("replay.wb.switchTrack")}
                    </Button>
                  )}
                  {selected && (
                    <>
                      <div className="replay-position-primary-actions">
                        {hedgePositionSide !== undefined && (
                          <Button
                            size="sm"
                            aria-expanded={showLeverage}
                            onClick={() => togglePositionPanel(item.track_id, "leverage", hedgePositionSide)}
                          >{t("replay.wb.setLev")}</Button>
                        )}
                        <Button
                          size="sm"
                          aria-expanded={showProtection}
                          onClick={() => togglePositionPanel(item.track_id, "protection", hedgePositionSide)}
                        >{t("replay.wb.setProtect")}</Button>
                        <Button
                          size="sm"
                          aria-expanded={showClose}
                          onClick={() => togglePositionPanel(item.track_id, "close", hedgePositionSide)}
                        >{t("replay.wb.close")}</Button>
                        <Button
                          size="sm"
                          variant="danger"
                          data-replay-action="close-position"
                          disabled={!commandReady}
                          onClick={() => void runTrade("execute_position_intent", { intent: "CLOSE", side: null, quantity: null, ...legPayload }, t("replay.paper.closeAllPending"), t("replay.paper.closeAllOk"))}
                        >{t("replay.wb.closeAll")}</Button>
                      </div>
                      {showClose && (
                        <section className="replay-position-actions">
                          <header><strong>{t("replay.wb.closeQty")}</strong><small>{t("replay.wb.closeHint")}</small></header>
                          <Field label={t("replay.wb.qtyLabel")}>
                            {unitInput(<Input size="sm" ref={closeQtyInputRef} value={itemCloseQuantity} inputMode="decimal" onChange={(event) => setCloseDraft({ trackId: selectedTrackId, ...(hedgePositionSide === undefined ? {} : { positionSide: hedgePositionSide }), value: event.target.value })} aria-label={t("replay.wb.closeQty")} />, itemQtyAsset)}
                          </Field>
                          <div className="replay-position-shares">{[0.25, 0.5, 1].map((share) => <Button size="sm" variant="ghost" key={share} onClick={() => setCloseDraft({ trackId: selectedTrackId, ...(hedgePositionSide === undefined ? {} : { positionSide: hedgePositionSide }), value: quantityForStep(Math.abs(quantityValue) * share, quantityStep) })}>{share * 100}%</Button>)}</div>
                          <Button
                            size="sm"
                            variant="primary"
                            data-replay-action="close-partial"
                            disabled={!commandReady || !itemCloseQuantity.trim()}
                            onClick={() => void runTrade("execute_position_intent", { intent: "CLOSE", side: null, quantity: itemCloseQuantity, ...legPayload }, t("replay.paper.closePending"), t("replay.paper.closeOk"))}
                          >{t("replay.wb.confirmClose")}</Button>
                        </section>
                      )}
                      {showLeverage && hedgePositionSide !== undefined && (
                        <section className="replay-position-actions">
                          <header><strong>{t("replay.wb.levHeader")}</strong><small>{t("replay.wb.levIndependent", { side: hedgePositionSide })}</small></header>
                          <Field label={t("replay.paper.leverage")}>
                            {unitInput(<Input size="sm" value={itemLeverage} inputMode="decimal" onChange={(event) => setLeverageDraft({ trackId: item.track_id, positionSide: hedgePositionSide, value: event.target.value })} aria-label={t("replay.wb.lev")} />, "x")}
                          </Field>
                          <Button
                            size="sm"
                            variant="primary"
                            data-replay-action="set-position-leverage"
                            disabled={!commandReady || !itemLeverage.trim()}
                            onClick={() => void runTrade(
                              "set_position_leverage",
                              { position_side: hedgePositionSide, leverage: itemLeverage },
                              t("replay.paper.levPending", { side: hedgePositionSide }),
                              t("replay.paper.levOk", { side: hedgePositionSide }),
                            )}
                          >{t("replay.wb.confirmLev")}</Button>
                        </section>
                      )}
                      {showProtection && (
                        <section className="replay-position-actions">
                          <header><strong>{t("replay.wb.protectHeader")}</strong><small>{t("replay.wb.protectHint")}</small></header>
                          <Field label={t("replay.wb.slPrice")}>
                            {unitInput(<Input size="sm" value={itemStopLossPrice} inputMode="decimal" onChange={(event) => setProtectionDraft({ trackId: selectedTrackId, ...(hedgePositionSide === undefined ? {} : { positionSide: hedgePositionSide }), stopLoss: event.target.value, takeProfit: itemTakeProfitPrice })} />, settlementAsset)}
                          </Field>
                          <Field label={t("replay.wb.tpPrice")}>
                            {unitInput(<Input size="sm" value={itemTakeProfitPrice} inputMode="decimal" onChange={(event) => setProtectionDraft({ trackId: selectedTrackId, ...(hedgePositionSide === undefined ? {} : { positionSide: hedgePositionSide }), stopLoss: itemStopLossPrice, takeProfit: event.target.value })} />, settlementAsset)}
                          </Field>
                          <div className="replay-position-shares">
                            <Button
                              size="sm"
                              variant="primary"
                              data-replay-action="set-position-protection"
                              disabled={!commandReady || (!itemStopLossPrice.trim() && !itemTakeProfitPrice.trim())}
                              onClick={() => void runTrade(
                                "set_position_protection",
                                {
                                  quantity: null,
                                  stop_loss_price: itemStopLossPrice.trim() || null,
                                  take_profit_price: itemTakeProfitPrice.trim() || null,
                                  ...legPayload,
                                },
                                t("replay.paper.protectPending"),
                                t("replay.paper.protectOk"),
                              )}
                            >{t("replay.wb.setProtectBtn")}</Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              data-replay-action="clear-position-protection"
                              disabled={!commandReady}
                              onClick={() => void runTrade(
                                "set_position_protection",
                                { quantity: null, stop_loss_price: null, take_profit_price: null, ...legPayload },
                                t("replay.paper.clearPending"),
                                t("replay.paper.clearOk"),
                              )}
                            >{t("replay.wb.clearProtect")}</Button>
                          </div>
                        </section>
                      )}
                      {contract?.position_mode !== "HEDGE" && (
                        <Disclosure summary={t("replay.wb.more")}>
                          <Button
                            size="sm"
                            data-replay-action="reverse-position"
                            disabled={!commandReady || !closeQuantity.trim()}
                            onClick={() => void runTrade(
                              "execute_position_intent",
                              {
                                intent: "REVERSE",
                                side: selectedPositionSignedQuantity > 0 ? "SELL" : "BUY",
                                quantity: closeQuantity,
                              },
                              t("replay.paper.reversePending"),
                              t("replay.paper.reverseOk"),
                            )}
                          >{t("replay.wb.reverseTo", { side: selectedPositionSignedQuantity > 0 ? t("replay.wb.short") : t("replay.wb.long") })}</Button>
                        </Disclosure>
                      )}
                    </>
                  )}
                </article>
              );
            })}

            <Disclosure
              summary={<>{t("replay.wb.recentClosed")} · {closedTrades.length}{reportState === "loading" ? <small> {t("replay.wb.syncing")}</small> : null}</>}
            >
              <div className="replay-rail-record-list">
                {recentClosedTrades.length === 0 ? <p className="replay-record-note">{t("replay.wb.noClosed")}</p> : recentClosedTrades.map((item) => (
                  <article className="replay-compact-record" key={item.trade_id}>
                    <header className="replay-record-head"><span data-order-side={item.side}>{sideLabel(item.side)} · {formatDecimal(item.quantity)}</span><strong data-value-tone={(finiteNumber(item.realized_pnl) ?? 0) >= 0 ? "positive" : "negative"}>{formatDecimal(item.realized_pnl, 4)} {settlementAsset}</strong></header>
                    <dl className="replay-metric-flat"><div><dt>{t("replay.wb.openPx")}</dt><dd>{formatDecimal(item.entry_price, 6)}</dd></div><div><dt>{t("replay.wb.closePx")}</dt><dd>{formatDecimal(item.exit_price, 6)}</dd></div></dl>
                  </article>
                ))}
              </div>
            </Disclosure>
          </div>
        )}

        {(activeTab === "open-orders" || activeTab === "order-history") && (() => {
          const orders = activeTab === "open-orders" ? openOrders : historicalOrders;
          const page = activeTab === "order-history" && contract !== null
            ? historicalOrderPages
            : null;
          return (
            <div className="replay-rail-account-scroll replay-rail-record-list" data-replay-panel={activeTab}>
              {activeTab === "open-orders" && selectedTrackOpenOrders.length > 0 && (
                <section className="replay-order-batch-actions" aria-label={t("replay.wb.batchCancel")}>
                  <Button
                    size="sm"
                    disabled={!commandReady || selectedOrderIds.length === 0}
                    onClick={() => void runTrade(
                      "cancel_orders",
                      { scope: "ORDER_IDS", order_ids: [...selectedOrderIds] },
                      t("replay.paper.cancelSelectedPending", { count: selectedOrderIds.length }),
                      t("replay.paper.cancelSelectedOk", { count: selectedOrderIds.length }),
                    )}
                  >{t("replay.wb.cancelSelected", { count: selectedOrderIds.length })}</Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={!commandReady}
                    onClick={() => void runTrade(
                      "cancel_orders",
                      { scope: "SELECTED_TRACK", order_ids: [] },
                      t("replay.paper.cancelSymbolPending", { symbol: selectedSymbol }),
                      t("replay.paper.cancelSymbolOk", { symbol: selectedSymbol }),
                    )}
                  >{t("replay.wb.cancelSymbol")}</Button>
                </section>
              )}
              {page?.loading === true && <p className="replay-record-note" role="status">{t("replay.wb.loadingHistory")}</p>}
              {page?.error !== null && page !== null && <InlineAlert tone="danger">{t("replay.wb.historyFailed", { error: page.error })}</InlineAlert>}
              {!page?.loading && orders.length === 0 ? <EmptyState compact title={activeTab === "open-orders" ? t("replay.wb.noOrders") : t("replay.wb.noHistory")} description={activeTab === "open-orders" ? t("replay.wb.noOrdersHint") : t("replay.wb.noHistoryHint")} /> : orders.map((order, index) => {
                const orderId = recordText(order, "order_id", `order-${index}`);
                const trackId = recordText(order, "track_id", selectedTrackId);
                const status = recordText(order, "status", "OPEN");
                const timestamp = eventTime(order);
                const editable = !TERMINAL_ORDER_STATES.has(status) && trackId === selectedTrackId;
                const editing = replaceDraft?.trackId === trackId && replaceDraft.orderId === orderId;
                const orderTypeValue = recordText(order, "order_type");
                const orderSide = recordText(order, "side");
                const reduceOnlyOrder = recordBoolean(order, "reduce_only");
                return (
                  <article className="replay-compact-record" key={`${trackId}:${orderId}`} data-order-status={status}>
                    <header className="replay-record-head">
                      <div className="replay-record-title">
                        {editable
                          ? <Checkbox label={<strong>{symbolForTrack(trackId)}</strong>} aria-label={t("replay.wb.selectOrder", { id: orderId })} checked={selectedOrderIds.includes(orderId)} onChange={(event) => toggleSelectedOrder(orderId, event.target.checked)} />
                          : <strong>{symbolForTrack(trackId)}</strong>}
                        <span className="replay-badge-row">
                          <Badge tone={orderSide === "BUY" ? "success" : "danger"}>{orderSide === "BUY" ? (reduceOnlyOrder ? t("replay.wb.closeShort") : t("replay.wb.openLong")) : (reduceOnlyOrder ? t("replay.wb.closeLong") : t("replay.wb.openShort"))}</Badge>
                          <Badge>{orderTypeLabel(orderTypeValue)}</Badge>
                          <Badge>{contract?.margin_mode === "ISOLATED" ? t("replay.wb.isolated") : t("replay.wb.cross")} · {config?.max_leverage ?? "--"}x</Badge>
                        </span>
                      </div>
                      <Badge className="replay-order-status" tone={orderStatusTone(status)}>{orderStatusLabel(status)}</Badge>
                    </header>
                    <dl className="replay-metric-flat">
                      <div><dt>{t("replay.wb.orderQty")}</dt><dd>{formatDecimal(recordText(order, "quantity"))}</dd></div>
                      <div><dt>{t("replay.wb.filled")}</dt><dd>{formatDecimal(recordText(order, "filled_quantity", "0"))}</dd></div>
                      <div><dt>{t("replay.wb.orderPrice")}</dt><dd>{formatDecimal(orderPrice(order), 6)}</dd></div>
                      {timestamp !== null && <div className="wide"><dt>{t("replay.wb.time")}</dt><dd>{time(timestamp)}</dd></div>}
                    </dl>
                    {editing && replaceDraft !== null && (
                      <div className="replay-order-replace-form">
                        <Field label={t("replay.wb.remainQty")}><Input size="sm" inputMode="decimal" value={replaceDraft.quantity} onChange={(event) => setReplaceDraft({ ...replaceDraft, quantity: event.target.value })} /></Field>
                        {orderTypeValue !== "MARKET" && <Field label={t("replay.wb.newPrice")}><Input size="sm" inputMode="decimal" value={replaceDraft.price} onChange={(event) => setReplaceDraft({ ...replaceDraft, price: event.target.value })} /></Field>}
                        <div className="replay-position-shares">
                          <Button size="sm" variant="primary" disabled={!commandReady || !replaceDraft.quantity.trim() || (orderTypeValue !== "MARKET" && !replaceDraft.price.trim())} onClick={() => replaceOrder(order)}>{t("replay.wb.confirmReplace")}</Button>
                          <Button size="sm" variant="ghost" onClick={() => setReplaceDraft(null)}>{t("replay.wb.cancel")}</Button>
                        </div>
                      </div>
                    )}
                    {editable && (
                      <div className="replay-order-card-actions">
                        {!editing && (
                          <Button size="sm" variant="ghost" disabled={!commandReady} onClick={() => setReplaceDraft({ trackId, orderId, quantity: recordText(order, "remaining_quantity", recordText(order, "quantity")), price: recordText(order, "limit_price", recordText(order, "stop_price", "")) })}>{t("replay.wb.replace")}</Button>
                        )}
                        <Button size="sm" variant="danger" disabled={!commandReady} onClick={() => void runTrade("cancel_order", { order_id: orderId }, t("replay.paper.cancelPending"), t("replay.paper.cancelOk"))}>{t("replay.wb.cancelOrder")}</Button>
                      </div>
                    )}
                  </article>
                );
              })}
              {page !== null && loadMoreButton(page)}
            </div>
          );
        })()}

        {activeTab === "fills" && (
          <div className="replay-rail-account-scroll replay-rail-record-list" data-replay-panel="fills">
            {fillPages.loading && contract !== null && <p className="replay-record-note" role="status">{t("replay.wb.loadingFills")}</p>}
            {fillPages.error !== null && contract !== null && <InlineAlert tone="danger">{t("replay.wb.fillsFailed", { error: fillPages.error })}</InlineAlert>}
            {!fillPages.loading && visibleFills.length === 0 ? <EmptyState compact title={t("replay.wb.noFills")} description={t("replay.wb.noFillsHint")} /> : visibleFills.map((fill, index) => {
              const timestamp = eventTime(fill);
              const fillSide = recordText(fill, "side");
              return (
                <article className="replay-compact-record" key={recordText(fill, "fill_id", `fill-${index}`)}>
                  <header className="replay-record-head">
                    <div className="replay-record-title">
                      <strong>{symbolForTrack(recordText(fill, "track_id", selectedTrackId))}</strong>
                      <span className="replay-badge-row">
                        <Badge tone={fillSide === "BUY" ? "success" : "danger"}>{sideLabel(fillSide)}</Badge>
                        <Badge>{recordText(fill, "liquidity") === "MAKER" ? t("replay.wb.maker") : t("replay.wb.taker")}</Badge>
                      </span>
                    </div>
                    <span className="replay-record-amount">{formatDecimal(recordText(fill, "quantity"))} @ {formatDecimal(recordText(fill, "price"), 6)}</span>
                  </header>
                  <dl className="replay-metric-flat">
                    <div><dt>{t("replay.wb.fee")}</dt><dd>{formatDecimal(recordText(fill, "configured_fee", recordText(fill, "fee")), 6)} {settlementAsset}</dd></div>
                    <div className="wide"><dt>{t("replay.wb.time")}</dt><dd>{timestamp === null ? "--" : time(timestamp)}</dd></div>
                  </dl>
                  <small className="replay-record-id" title={recordText(fill, "reason")}>{recordText(fill, "fill_id", "--")}</small>
                </article>
              );
            })}
            {contract !== null && loadMoreButton(fillPages)}
          </div>
        )}

        {activeTab === "assets" && (
          <div className="replay-rail-account-scroll" data-replay-panel="account-assets">
            <section className="replay-asset-strip">
              <header className="replay-record-head">
                <strong><span className="replay-asset-icon" aria-hidden="true">{settlementAsset.slice(0, 1) || "U"}</span>{settlementAsset || t("replay.wb.assetFallback")}</strong>
                <small>{t("replay.wb.initial", { value: formatDecimal(portfolio?.initial_equity, 2) })}</small>
              </header>
              <dl className="replay-metric-flat">
                <div><dt>{t("replay.wb.coinEquity")}</dt><dd>{formatDecimal(accountView?.equity, 4)}</dd></div>
                <div><dt>{t("replay.wb.used")}</dt><dd>{formatDecimal(accountView?.margin_used, 4)}</dd></div>
                <div><dt>{t("replay.wb.available")}</dt><dd>{formatDecimal(accountView?.available_equity, 4)}</dd></div>
                <div><dt>{t("replay.wb.floatPnl")}</dt><dd data-value-tone={pnlTone}>{formatDecimal(accountView?.unrealized_pnl, 4)}</dd></div>
                <div><dt>{t("replay.wb.realized")}</dt><dd>{formatDecimal(portfolio?.realized_pnl, 4)}</dd></div>
                <div><dt>{t("replay.wb.feesPaid")}</dt><dd>{formatDecimal(portfolio?.fees_paid, 6)}</dd></div>
                <div><dt>{t("replay.wb.mm")}</dt><dd>{formatDecimal(contract?.maintenance_margin, 4)}</dd></div>
                <div><dt>{t("replay.wb.riskCover")}</dt><dd>{contract?.risk_ratio == null ? "--" : `${formatDecimal(contract.risk_ratio, 2)}×`}</dd></div>
                <div><dt>{t("replay.hub.funding")}</dt><dd>{formatDecimal(contract?.funding_cashflow, 6)}</dd></div>
              </dl>
            </section>
          </div>
        )}

        {activeTab === "risk" && (
          <div className="replay-risk-dashboard replay-rail-account-scroll" data-replay-panel="account-risk">
            <section className="replay-risk-card">
              <header className="replay-record-head"><strong>{t("replay.wb.rules")}</strong><Badge>{contract?.status ?? t("replay.wb.loadingStatus")}</Badge></header>
              <dl className="replay-metric-flat">
                <div><dt>{t("replay.wb.marginMode")}</dt><dd>{contract?.margin_mode === "ISOLATED" ? t("replay.wb.isolated") : t("replay.wb.cross")}</dd></div>
                <div><dt>{t("replay.wb.execModel")}</dt><dd>{contract?.execution_fidelity === "BOOK_ASSISTED_CONTINUITY_GATED_NO_QUEUE" ? t("replay.wb.l2Assist") : t("replay.wb.touchApprox")}</dd></div>
                <div><dt>{t("replay.wb.ledgerDelta")}</dt><dd>{contract === null ? "--" : recordText(contract.ledger, "reconciliation_delta")}</dd></div>
                <div className="wide"><dt>{t("replay.wb.histAccount")}</dt><dd>{contract?.account_history.mode === "HISTORICAL_EXACT" ? t("replay.wb.histExact") : t("replay.wb.priceProxy")}</dd></div>
              </dl>
            </section>
            <section className="replay-risk-card">
              <header className="replay-record-head"><strong>{t("replay.wb.fidelityBound")}</strong><Badge>{contract?.account_history.auditor.status ?? "NOT_RUN"}</Badge></header>
              <p>{contract?.execution_fidelity === "BOOK_ASSISTED_CONTINUITY_GATED_NO_QUEUE" ? t("replay.wb.modelL2") : t("replay.wb.modelNoQueue")}</p>
              <p>{t("replay.wb.markLabel", { value: contract === null ? "--" : recordText(contract.fidelity, "mark") })}</p>
              <p>{t("replay.wb.mmLabel", { value: contract === null
                ? "--"
                : recordText(contract.fidelity, "maintenance_margin") === "LAST_MAINTENANCE_TIER_RATE_DEDUCTION_EXTRAPOLATED"
                  ? t("replay.wb.mmLastTier")
                  : recordText(contract.fidelity, "maintenance_margin") === "VERSIONED_MAINTENANCE_TIER_APPLIED"
                    ? t("replay.wb.mmInTier")
                    : t("replay.wb.mmUndeclared") })}</p>
              <p>{t("replay.wb.liqLabel", { value: contract === null
                ? "--"
                : recordText(contract.fidelity, "liquidation_projection") === "LAST_MAINTENANCE_TIER_RATE_DEDUCTION_EXTRAPOLATED"
                  ? t("replay.wb.liqLastTier")
                  : recordText(contract.fidelity, "liquidation_projection") === "VERSIONED_MAINTENANCE_TIER_APPLIED"
                    ? t("replay.wb.liqInTier")
                    : t("replay.wb.mmUndeclared") })}</p>
              <Button size="sm" className="replay-risk-action" data-replay-action="audit-account" disabled={viewer.viewerPending} onClick={() => void viewer.actions.auditAccount().catch(() => undefined)}>{t("replay.wb.audit")}</Button>
            </section>
            {contract !== null && (
              <Disclosure
                className="replay-risk-card"
                defaultOpen={contract.history.ledger_entries_total > 0}
                summary={<>{t("replay.wb.ledger")} · {contract.history.ledger_entries_total}</>}
              >
                {ledgerPages.loading && <p className="replay-record-note" role="status">{t("replay.wb.loadingLedger")}</p>}
                {ledgerPages.error !== null && <InlineAlert tone="danger">{t("replay.wb.ledgerFailed", { error: ledgerPages.error })}</InlineAlert>}
                <div className="replay-rail-record-list">
                  {ledgerPages.items.map((entry, index) => {
                    const timestamp = eventTime(entry) ?? recordNumber(entry, "virtual_time_ms");
                    return (
                      <article className="replay-compact-record" key={recordText(entry, "posting_id", `ledger-${index}`)}>
                        <header className="replay-record-head"><strong>{recordText(entry, "kind")}</strong><span data-value-tone={(finiteNumber(entry.cash_delta) ?? 0) >= 0 ? "positive" : "negative"}>{formatDecimal(entry.cash_delta, 8)} {recordText(entry, "asset", settlementAsset)}</span></header>
                        <small className="replay-record-id">{recordText(entry, "reference_type")} · {recordText(entry, "reference_id")} · {timestamp === null ? "--" : time(timestamp)}</small>
                      </article>
                    );
                  })}
                </div>
                {loadMoreButton(ledgerPages)}
              </Disclosure>
            )}
            {contract?.margin_mode === "ISOLATED" && (
              <section className="replay-risk-card">
                <header className="replay-record-head"><strong>{t("replay.wb.isolatedAlloc")}</strong><small>{selectedSymbol}</small></header>
                {contract.position_mode === "HEDGE" && (
                  <Field label={t("replay.wb.posLeg")}>
                    <Select size="sm" value={isolatedSide} onChange={(event) => setIsolatedSide(event.target.value as "LONG" | "SHORT")}>
                      <option value="LONG">LONG</option>
                      <option value="SHORT">SHORT</option>
                    </Select>
                  </Field>
                )}
                <Field label={t("replay.wb.allocAmt")} hint={t("replay.wb.current", { value: String(contract.isolated_allocations[contract.position_mode === "HEDGE" ? `${selectedTrackId}:${isolatedSide}` : selectedTrackId] ?? "0"), asset: settlementAsset })}>
                  {unitInput(<Input size="sm" value={isolatedAmount} inputMode="decimal" onChange={(event) => setIsolatedAmount(event.target.value)} />, settlementAsset)}
                </Field>
                <Button size="sm" variant="primary" className="replay-risk-action" disabled={!commandReady || !isolatedAmount.trim()} onClick={() => void viewer.actions.submitTrade("allocate_isolated_margin", { track_id: selectedTrackId, position_side: contract.position_mode === "HEDGE" ? isolatedSide : null, amount: isolatedAmount }).catch(() => undefined)}>{t("replay.wb.setAlloc")}</Button>
              </section>
            )}
            <section className="replay-risk-card" data-replay-panel="historical-market-liquidations" data-replay-domain="historical-market-liquidation">
              <header className="replay-record-head"><strong>{t("replay.wb.mktLiq")}</strong><Badge>{contract?.liquidation_channels.historical_market.fidelity ?? "UNSUPPORTED_NO_HISTORY"}</Badge></header>
              <p>{t("replay.wb.mktLiqHint")}</p>
            </section>
            <section className="replay-risk-card" data-replay-panel="simulated-liquidations" data-replay-domain="simulated-account-liquidation">
              <header className="replay-record-head"><strong>{t("replay.wb.simLiq")}</strong><Badge tone={(contract?.liquidations.length ?? 0) > 0 ? "warning" : "neutral"}>{contract?.liquidations.length ?? 0}</Badge></header>
              <p>{t("replay.wb.simLiqHint")}</p>
              <ReplayLiquidationTimeline
                cases={contract?.liquidations ?? []}
                formatVirtualTime={time}
              />
              {(contract?.liquidation_recoveries.length ?? 0) > 0 && (
                <Disclosure summary={t("replay.wb.recoveries", { count: contract?.liquidation_recoveries.length ?? 0 })}>
                  <ReplayLiquidationTimeline
                    cases={contract?.liquidation_recoveries ?? []}
                    formatVirtualTime={time}
                    emptyLabel={t("replay.wb.recoverEmpty")}
                  />
                </Disclosure>
              )}
            </section>
          </div>
        )}
      </TabPanel>
    </section>
  );
}

export function ReplayMarketDataDock({ runtime, viewer, indicatorStatus, formatTime }: ReplayRightRailProps) {
  useLocale();
  const tabsId = useId();
  const [activeTab, setActiveTab] = useState<MarketTab>("book");
  const store = runtime.store;
  const config = store.sessionConfig;
  const selectedTrackId = viewer.viewerState?.selected_track_id ?? "track-1";
  const selectedTrack = viewer.marketTracks?.tracks.find((item) => item.track_id === selectedTrackId);
  const historicalBook = selectedTrack?.historical_book ?? null;
  const tradeFlow = useReplayTradeFlow({
    runId: viewer.viewerState?.run_id ?? null,
    trackId: selectedTrackId,
    sourceKind: config?.source_kind ?? null,
    revealedSequence: store.sourceSequence,
  });
  const time = (value: number) => formatTime?.(value)
    ?? formatReplayPublicTime(value, { blindMode: config?.blind_mode ?? true, originMs: store.replayStartMs });
  const bookLevels = (side: "bid" | "ask", levels: readonly (readonly [string, string])[]) => (
    <ol className="replay-book-side" data-book-side={side}>
      {levels.map(([levelPrice, levelQuantity]) => (
        <li key={`${side}:${levelPrice}`} data-book-side={side}>
          <span>{formatDecimal(levelPrice, 6)}</span>
          <span>{formatDecimal(levelQuantity)}</span>
        </li>
      ))}
    </ol>
  );
  return (
    <div className="replay-market-context" data-replay-paper-surface="market-data">
      <Tabs
        id={tabsId}
        className="replay-market-context-tabs"
        label={t("replay.dock.marketAria")}
        value={activeTab}
        tabs={MARKET_TAB_IDS.map((value) => ({ value, label: marketTabLabel(value) }))}
        onChange={setActiveTab}
      />
      <TabPanel tabsId={tabsId} value={activeTab} className="replay-market-context-body">
        {activeTab === "book" && (
          <section className="replay-market-context-section" data-replay-panel="historical-book" data-replay-book-status={historicalBook?.status ?? "OFF"}>
            <h2>{t("replay.dock.histL2", { symbol: selectedTrack?.symbol ?? "--" })}</h2>
            {historicalBook === null || historicalBook.status === "OFF"
              ? <EmptyState compact title={t("replay.dock.bookOff")} description={t("replay.dock.bookOffHint")} />
              : historicalBook.status !== "READY"
                ? (
                  <InlineAlert
                    tone="warning"
                    title={t("replay.dock.bookCleared", { status: historicalBook.status })}
                    action={(
                      <Button
                        size="sm"
                        data-replay-action="resync-historical-book"
                        disabled={viewer.viewerPending || viewer.marketTracks?.global_clock?.state !== "PAUSED"}
                        onClick={() => void viewer.actions.resyncHistoricalBook().catch(() => undefined)}
                      >{t("replay.dock.resync")}</Button>
                    )}
                  >{historicalBook.message}</InlineAlert>
                )
                : (
                  <>
                    <p className="replay-market-context-note">{t("replay.dock.l2Ready")}</p>
                    <div className="replay-book-columns">
                      <div><h3>{t("replay.dock.bids")}</h3>{bookLevels("bid", historicalBook.bids)}</div>
                      <div><h3>{t("replay.dock.asks")}</h3>{bookLevels("ask", historicalBook.asks)}</div>
                    </div>
                  </>
                )}
          </section>
        )}
        {activeTab === "flow" && (
          <section className="replay-market-context-section" data-replay-panel="trade-flow" data-replay-trade-flow-state={tradeFlow.state}>
            <h2>{t("replay.dock.tapeTitle")}</h2>
            {tradeFlow.state === "UNSUPPORTED_SOURCE_MODE" && <EmptyState compact title={t("replay.dock.flowOff")} description={t("replay.dock.flowOffHint")} />}
            {tradeFlow.state === "LOADING" && <p className="replay-market-context-note" role="status">{t("replay.dock.flowLoading")}</p>}
            {tradeFlow.state === "DEGRADED" && <InlineAlert tone="warning" title={t("replay.dock.flowDegraded")}>{tradeFlow.error ?? t("replay.dock.flowFail")}</InlineAlert>}
            {tradeFlow.state === "CONTIGUOUS" && (
              <>
                <div className="replay-trade-flow-stats">
                  <Stat label={t("replay.dock.windowCvd")} value={formatDecimal(tradeFlow.cvd)} />
                  <Stat label={t("replay.dock.pageDelta")} value={formatDecimal(tradeFlow.pageDelta)} />
                </div>
                <p className="replay-market-context-note">{t("replay.dock.tapeHint", { fidelity: tradeFlow.fidelity })}</p>
                <ol className="replay-trade-flow-list">
                  {[...tradeFlow.tape].reverse().map((item) => (
                    <li key={item.source_sequence} data-aggressor-side={item.aggressor_side}>
                      <strong>{sideLabel(item.aggressor_side)} {formatDecimal(item.quantity)} @ {formatDecimal(item.price, 6)}</strong>
                      <span>Δ {formatDecimal(item.cvd_delta)} · agg #{item.agg_trade_id}</span>
                      <small>{time(item.trade_time_ms)} · {t("replay.dock.rawAgg", { count: item.raw_trade_count })}</small>
                    </li>
                  ))}
                </ol>
              </>
            )}
          </section>
        )}
        {activeTab === "indicators" && (
          <section className="replay-market-context-section" data-replay-panel="indicators">
            <h2>{t("replay.dock.localInd")}</h2>
            <p>{t("replay.dock.localIndHint", { count: indicatorStatus.sourceBarCount })}</p>
            <p className="replay-market-context-note">{t("replay.dock.hostedOff")}</p>
          </section>
        )}
      </TabPanel>
    </div>
  );
}
