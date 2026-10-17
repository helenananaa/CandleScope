import type {
  IChartApiBase,
  ITimeScaleApi,
  Logical,
  LogicalRange,
} from "lightweight-charts";
import type {
  ChartSeriesInputRow,
  ChartTime,
  ViewportAnchor,
  ViewportLogicalRange,
  ViewportRestorePlan,
} from "./chartAdapterTypes.js";

const DEFAULT_UNLOCK_DELAY_MS = 200;
const PRIORITY = {
  fit: 10,
  restore: 20,
  compensate: 30,
};
const COMPENSATE_INTENT = "compensateShift";
const LOGICAL_SHIFT_EPSILON = 1e-7;

type AdapterChart = IChartApiBase<ChartTime>;
type AdapterTimeScale = ITimeScaleApi<ChartTime>;
type TimerHandle = ReturnType<typeof setTimeout>;

interface ViewportIntent {
  name: string;
  priority: number;
  shift?: number;
  apply: (timeScale: AdapterTimeScale, chart: AdapterChart | null) => unknown;
}

export interface ViewportControllerOptions {
  chartProvider?: (() => AdapterChart | null) | null;
  contentLogicalRangeProvider?: (() => ViewportLogicalRange | null) | null;
  unlockDelayMs?: number;
  setTimer?: (callback: () => void, delayMs: number) => TimerHandle;
  clearTimer?: (timer: TimerHandle) => void;
}

function safeCall<TResult>(fn: () => TResult, fallback: TResult): TResult {
  try {
    return fn();
  } catch {
    return fallback;
  }
}

function finiteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function toLogicalRange(range: ViewportLogicalRange): LogicalRange {
  return {
    from: range.from as Logical,
    to: range.to as Logical,
  };
}

export function logicalRangeForLatestBarPosition({
  barSpacing,
  contentLastLogical,
  position = 0.5,
  width,
}: {
  barSpacing?: unknown;
  contentLastLogical?: unknown;
  position?: unknown;
  width?: unknown;
} = {}): ViewportLogicalRange | null {
  const spacing = Number(barSpacing);
  const last = Number(contentLastLogical);
  const scaleWidth = Number(width);
  const normalizedPosition = Number(position);
  if (!Number.isFinite(spacing) || spacing <= 0
    || !Number.isFinite(last)
    || !Number.isFinite(scaleWidth) || scaleWidth <= 0
    || !Number.isFinite(normalizedPosition)
    || normalizedPosition < 0 || normalizedPosition > 1) return null;
  // LWC sets spacing to width / (to - from + 1). Using width / spacing
  // as the endpoint difference zooms out by one bar on every follow intent.
  const span = scaleWidth / spacing - 1;
  if (!Number.isFinite(span) || span <= 0) return null;
  const from = last - span * normalizedPosition;
  return { from, to: from + span };
}

export class ViewportController {
  private readonly chartProvider: () => AdapterChart | null;
  private readonly contentLogicalRangeProvider: (() => ViewportLogicalRange | null) | null;
  private readonly unlockDelayMs: number;
  private readonly setTimer: (callback: () => void, delayMs: number) => TimerHandle;
  private readonly clearTimer: (timer: TimerHandle) => void;
  private userInteracting: boolean;
  private unlockTimer: TimerHandle | null;
  private pendingIntent: ViewportIntent | null;
  private readonly fitSessionKeys: Set<string>;
  private readonly resetScaleOptions: { barSpacing: number; rightOffset: number } | null;
  private frozenOnNewBars = false;

  constructor({
    chartProvider,
    contentLogicalRangeProvider = null,
    unlockDelayMs = DEFAULT_UNLOCK_DELAY_MS,
    setTimer = (callback, delayMs) => setTimeout(callback, delayMs),
    clearTimer = (timer) => clearTimeout(timer),
  }: ViewportControllerOptions = {}) {
    this.chartProvider = chartProvider || (() => null);
    this.contentLogicalRangeProvider = contentLogicalRangeProvider;
    this.unlockDelayMs = unlockDelayMs;
    this.setTimer = setTimer;
    this.clearTimer = clearTimer;
    this.userInteracting = false;
    this.unlockTimer = null;
    this.pendingIntent = null;
    this.fitSessionKeys = new Set();
    this.resetScaleOptions = safeCall(() => {
      const options = this.getTimeScale()?.options();
      return options ? { barSpacing: options.barSpacing, rightOffset: options.rightOffset } : null;
    }, null);
  }

  getChart(): AdapterChart | null {
    return this.chartProvider?.() || null;
  }

  getTimeScale(): AdapterTimeScale | null {
    return this.getChart()?.timeScale?.() || null;
  }

  isLocked(): boolean {
    return this.userInteracting;
  }

  markUserInteracting(): void {
    this.userInteracting = true;
    if (this.unlockTimer) this.clearTimer(this.unlockTimer);
    this.unlockTimer = this.setTimer(() => {
      this.userInteracting = false;
      this.unlockTimer = null;
      this.flushPendingIntent();
    }, this.unlockDelayMs);
  }

  dispose(): void {
    this.resetSession();
  }

  resetSession(): void {
    if (this.frozenOnNewBars) this.getTimeScale()?.applyOptions?.({ shiftVisibleRangeOnNewBar: true });
    this.frozenOnNewBars = false;
    if (this.unlockTimer != null) this.clearTimer(this.unlockTimer);
    this.unlockTimer = null;
    this.userInteracting = false;
    this.pendingIntent = null;
    this.fitSessionKeys.clear();
  }

  applyIntent(
    name: string,
    priority: number,
    apply: ViewportIntent["apply"],
  ): boolean {
    if (this.userInteracting) {
      if (!this.pendingIntent || priority >= this.pendingIntent.priority) {
        this.pendingIntent = { name, priority, apply };
      }
      return false;
    }
    const timeScale = this.getTimeScale();
    if (!timeScale) return false;
    return Boolean(apply(timeScale, this.getChart()));
  }

  private applyImmediateIntent(apply: ViewportIntent["apply"]): boolean {
    // An explicit surface/dataset transition owns the viewport now. Any
    // queued compensation belongs to the outgoing surface and must not run
    // after the target range has been restored.
    this.pendingIntent = null;
    const timeScale = this.getTimeScale();
    if (!timeScale) return false;
    return Boolean(apply(timeScale, this.getChart()));
  }

  flushPendingIntent(): boolean {
    const intent = this.pendingIntent;
    this.pendingIntent = null;
    if (!intent) return false;
    return this.applyIntent(intent.name, intent.priority, intent.apply);
  }

  private contentRange(): ViewportLogicalRange | null {
    const range = safeCall(() => this.contentLogicalRangeProvider?.() ?? null, null);
    return finiteNumber(range?.from) && finiteNumber(range?.to) && range.from <= range.to
      ? range : null;
  }

  /** Persist whitespace relative to market rows, excluding axis-only carriers. */
  captureRightOffset(): number | null {
    const timeScale = this.getTimeScale();
    if (!timeScale) return null;
    const content = this.contentRange();
    const logical = safeCall(() => timeScale.getVisibleLogicalRange(), null);
    return content && finiteNumber(logical?.to)
      ? logical.to - content.to
      : safeCall(() => timeScale.scrollPosition(), null);
  }

  private anchorContent(timeScale: AdapterTimeScale, offset: number, barSpacing?: number | null): boolean {
    const content = this.contentRange();
    if (!content) return false;
    const range = logicalRangeForLatestBarPosition({
      barSpacing: barSpacing ?? timeScale.options().barSpacing,
      contentLastLogical: content.to + offset,
      position: 1,
      width: timeScale.width(),
    });
    if (!range) return false;
    // A reopened session starts at the market tail. Older shared-axis shifts
    // may have persisted an offset that puts the entire view in the future.
    // Keep its zoom, but recover usable default padding in that case.
    if (range.from > content.to) {
      const padding = Math.min(range.to - range.from,
        Math.max(0, this.resetScaleOptions?.rightOffset ?? 0));
      const shift = range.to - (content.to + padding);
      range.from -= shift;
      range.to -= shift;
    }
    timeScale.setVisibleLogicalRange(toLogicalRange(range));
    return true;
  }

  resetToDefault(): boolean {
    return this.applyIntent("resetToDefault", PRIORITY.restore, (timeScale) => {
      timeScale.resetTimeScale();
      // The chart engine's default reset includes hidden future carriers.
      // Retain its default zoom/padding around the real content instead.
      const defaults = this.resetScaleOptions ?? timeScale.options();
      this.anchorContent(timeScale, Math.max(0, defaults.rightOffset), defaults.barSpacing);
      return true;
    });
  }

  fitSemanticContent(timeScale: AdapterTimeScale): boolean {
    const contentRangeProvider = this.contentLogicalRangeProvider;
    const contentRange = contentRangeProvider
      ? safeCall(() => contentRangeProvider(), null)
      : null;
    if (finiteNumber(contentRange?.from)
      && finiteNumber(contentRange?.to)
      && contentRange.from <= contentRange.to
      && typeof timeScale?.setVisibleLogicalRange === "function") {
      const configuredRightOffset = safeCall(
        () => Number(timeScale.options?.().rightOffset),
        0,
      );
      const rightOffset = Number.isFinite(configuredRightOffset)
        ? Math.max(0, configuredRightOffset)
        : 0;
      const to = Math.max(contentRange.from + 1, contentRange.to + rightOffset);
      timeScale.setVisibleLogicalRange(toLogicalRange({ from: contentRange.from, to }));
      return true;
    }
    timeScale?.fitContent?.();
    return true;
  }

  fitOnce(sessionKey = "default"): boolean {
    if (this.fitSessionKeys.has(sessionKey)) return false;
    this.fitSessionKeys.add(sessionKey);
    return this.applyIntent("fitOnce", PRIORITY.fit, (timeScale) => {
      return this.fitSemanticContent(timeScale);
    });
  }

  resetFit(sessionKey: string | null = null): void {
    if (sessionKey == null) {
      this.fitSessionKeys.clear();
      return;
    }
    this.fitSessionKeys.delete(sessionKey);
  }

  applySessionRestore(
    plan: ViewportRestorePlan | null | undefined,
    { sessionKey = "default" }: { sessionKey?: string } = {},
  ): boolean {
    if (!plan) return this.fitOnce(sessionKey);
    return this.applyIntent("sessionRestore", PRIORITY.restore, (timeScale) => {
      if (finiteNumber(plan.barSpacing)) {
        timeScale.applyOptions?.({ barSpacing: plan.barSpacing });
      }

      let restored = false;
      if (plan.mode === "anchor") {
        const offset = finiteNumber(plan.rightOffset)
          ? plan.rightOffset : Math.max(0, timeScale.options().rightOffset);
        if (!this.anchorContent(timeScale, offset, plan.barSpacing) && finiteNumber(plan.rightOffset)) {
          // Generic charts without a semantic content provider retain the
          // chart engine's scrollPosition contract.
          timeScale.scrollToPosition?.(plan.rightOffset, false);
        }
        restored = true;
      }
      const timeRange = plan.timeRange;
      if (!restored && plan.mode === "time" && timeRange) {
        restored = safeCall(() => {
          timeScale.setVisibleRange(timeRange);
          return true;
        }, false);
      }
      const logicalRange = plan.logicalRange;
      if (!restored && plan.mode === "logical" && logicalRange) {
        restored = safeCall(() => {
          timeScale.setVisibleLogicalRange(toLogicalRange(logicalRange));
          return true;
        }, false);
      }
      if (restored && finiteNumber(plan.scrollPosition)) {
        timeScale.scrollToPosition?.(plan.scrollPosition, false);
      }
      if (!restored) {
        this.fitSemanticContent(timeScale);
      }
      this.fitSessionKeys.add(sessionKey);
      return true;
    });
  }

  restoreProjectionRange(
    logicalRange: ViewportLogicalRange | null | undefined,
    {
      barSpacing = null,
      immediate = false,
      freezeOnNewBars = false,
    }: {
      barSpacing?: number | null;
      immediate?: boolean;
      freezeOnNewBars?: boolean;
    } = {},
  ): boolean {
    const apply = (timeScale: AdapterTimeScale) => {
      if (finiteNumber(barSpacing)) {
        timeScale.applyOptions?.({ barSpacing });
      }
      if (finiteNumber(logicalRange?.from) && finiteNumber(logicalRange?.to)) {
        const span = logicalRange.to - logicalRange.from;
        const requiredSpacing = Number(timeScale.width?.()) / span;
        const minimumSpacing = Number(timeScale.options?.().minBarSpacing ?? 0.5);
        // The default LWC minimum would silently widen a large source-time
        // view when switching to a finer period. Lower it only as required.
        if (span > 0 && Number.isFinite(requiredSpacing) && requiredSpacing > 0
          && requiredSpacing < minimumSpacing) {
          timeScale.applyOptions?.({ minBarSpacing: requiredSpacing });
        }
        if (freezeOnNewBars) {
          timeScale.applyOptions?.({ shiftVisibleRangeOnNewBar: false });
          this.frozenOnNewBars = true;
        }
        timeScale.setVisibleLogicalRange?.(toLogicalRange(logicalRange));
        return true;
      }
      return this.fitSemanticContent(timeScale);
    };
    return immediate
      ? this.applyImmediateIntent(apply)
      : this.applyIntent("projectionRestore", PRIORITY.restore, apply);
  }

  followLatest(
    contentLastLogical: number,
    {
      position = 0.5,
    }: {
      position?: number;
    } = {},
  ): boolean {
    return this.applyIntent("followLatest", PRIORITY.restore, (timeScale) => {
      const range = logicalRangeForLatestBarPosition({
        barSpacing: safeCall(() => Number(timeScale.options?.().barSpacing), Number.NaN),
        contentLastLogical,
        position,
        width: safeCall(() => Number(timeScale.width?.()), Number.NaN),
      });
      if (!range) return false;
      if (this.frozenOnNewBars) timeScale.applyOptions?.({ shiftVisibleRangeOnNewBar: true });
      this.frozenOnNewBars = false;
      timeScale.setVisibleLogicalRange?.(toLogicalRange(range));
      return true;
    });
  }

  captureAnchor(previousRows: ChartSeriesInputRow[]): ViewportAnchor | null {
    if (!previousRows?.length) return null;
    const timeScale = this.getTimeScale();
    const range = safeCall(() => timeScale?.getVisibleLogicalRange?.(), null);
    if (!range || !Number.isFinite(range.from)) return null;
    const index = Math.min(previousRows.length - 1, Math.max(0, Math.round(range.from)));
    const time = previousRows[index]?.time;
    if (time == null) return null;
    return {
      time,
      index,
      screenOffset: index - range.from,
    };
  }

  applyAnchorShift(
    anchor: ViewportAnchor | null | undefined,
    indexOfTime: ((time: ChartTime) => number) | null | undefined,
  ): boolean {
    if (!anchor || typeof indexOfTime !== "function") return false;
    const newIndex = indexOfTime(anchor.time);
    if (
      !Number.isFinite(newIndex)
      || newIndex < 0
      || !Number.isFinite(anchor.screenOffset)
    ) return false;

    const timeScale = this.getTimeScale();
    const currentRange = safeCall(() => timeScale?.getVisibleLogicalRange?.(), null);
    if (
      !currentRange
      || !Number.isFinite(currentRange.from)
      || !Number.isFinite(currentRange.to)
    ) return false;

    // Lightweight Charts rebases the logical range automatically for a pure
    // prepend. Preserve the anchor's screen offset and apply only any residual
    // shift left after setData (for example, a mid-window merge). This avoids
    // double-shifting prepends while keeping structural updates pixel-stable.
    const desiredFrom = newIndex - anchor.screenOffset;
    return this.applyLogicalShiftNow(desiredFrom - currentRange.from, currentRange);
  }

  applyLogicalShiftNow(shift: number, currentRange: LogicalRange | null = null): boolean {
    if (!Number.isFinite(shift)) return false;
    if (Math.abs(shift) <= LOGICAL_SHIFT_EPSILON) return true;

    const timeScale = this.getTimeScale();
    const range = currentRange || safeCall(() => timeScale?.getVisibleLogicalRange?.(), null);
    if (
      !timeScale
      || !range
      || !Number.isFinite(range.from)
      || !Number.isFinite(range.to)
    ) return false;

    // Structural compensation is coordinate rebasing, not an independent
    // navigation intent. It must happen synchronously with setData even while
    // the user-interaction lock is active, otherwise one wrong frame is shown
    // and the queued correction becomes a visible jump.
    return safeCall(() => {
      timeScale.setVisibleLogicalRange?.(toLogicalRange({
        from: range.from + shift,
        to: range.to + shift,
      }));
      return true;
    }, false);
  }

  queueShift(shift: number): boolean {
    if (!Number.isFinite(shift) || shift === 0) return false;
    if (this.userInteracting && this.pendingIntent?.name === COMPENSATE_INTENT) {
      // Accumulate shifts queued during one interaction so none are lost.
      this.pendingIntent.shift = (this.pendingIntent.shift || 0) + shift;
      return false;
    }
    const intent: ViewportIntent = {
      name: COMPENSATE_INTENT,
      priority: PRIORITY.compensate,
      shift,
      apply: () => false,
    };
    intent.apply = (timeScale) => {
      const range = safeCall(() => timeScale.getVisibleLogicalRange?.(), null);
      if (!range || !Number.isFinite(range.from) || !Number.isFinite(range.to)) return false;
      const intentShift = intent.shift || 0;
      timeScale.setVisibleLogicalRange?.(toLogicalRange({
        from: range.from + intentShift,
        to: range.to + intentShift,
      }));
      return true;
    };
    if (this.userInteracting) {
      if (!this.pendingIntent || intent.priority >= this.pendingIntent.priority) {
        this.pendingIntent = intent;
      }
      return false;
    }
    const timeScale = this.getTimeScale();
    if (!timeScale) return false;
    return Boolean(intent.apply(timeScale, this.getChart()));
  }

  compensateInsert(addedLeft = 0): boolean {
    return this.applyLogicalShiftNow(Number(addedLeft) || 0);
  }
}

export function createViewportController(
  options: ViewportControllerOptions = {},
): ViewportController {
  return new ViewportController(options);
}
