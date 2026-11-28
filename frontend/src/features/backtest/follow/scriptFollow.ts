/**
 * FOLLOW for SCRIPT-authority runs (ADR-BACKTEST-015 P4a, decision O1).
 *
 * The engine fixes a run's range when it is created, so a native Pine strategy on the
 * chart follows live bars by rebuilding: after each signal-interval bar closes, a new
 * FIXED run covers the latest prefix and replaces the shown result when it completes.
 * Each FOLLOW result is therefore exactly the FIXED run of the same input (§3.4).
 *
 * Limits (O2, confirmed 2026-11-27): a rebuild starts from at most the latest 5,000 bars;
 * one rebuild at a time, later closes folded into one more; identical inputs reuse their
 * run (the idempotency key is the input's hash).
 *
 * Incremental rebuilds (B-157a): when the backend reports that a rebuild's engine session
 * can be extended, the next rebuild keeps its start, so its input continues the previous
 * one and only the new bars execute. The window then grows to at most twice the budget
 * and starts again from the latest 5,000 bars, one full rebuild per 5,000 closes.
 */
import type { SeriesWindowView } from "../../market-data/window/seriesWindowView.js";
import { INTERVAL_UNIT_SECONDS, parseIntervalParts } from "../../../utils/intervals.js";

export const SCRIPT_FOLLOW_BAR_BUDGET = 5_000;

export interface FollowRange {
  start_time_ms: number;
  /** Inclusive: the last closed bar's close, as chart-context ranges are. */
  end_time_ms: number;
}

/** A fixed-length signal interval in ms; null for calendar intervals (weeks, months), which FOLLOW does not cover. */
export function fixedIntervalMs(interval: string): number | null {
  const parts = parseIntervalParts(interval);
  if (!parts || parts.unit === "w" || parts.unit === "M") return null;
  return parts.amount * INTERVAL_UNIT_SECONDS[parts.unit] * 1000;
}

/** The open time of the newest closed bar in the chart's window, or null. A forming last bar is not closed. */
export function latestClosedBarOpenMs(window: Pick<SeriesWindowView, "last" | "intervalSeconds"> | null): number | null {
  const last = window?.last();
  if (!window || !last || typeof last.is_closed !== "boolean" || !window.intervalSeconds) return null;
  const open = Number(last.time) * 1000;
  if (!Number.isSafeInteger(open) || open < 0) return null;
  return last.is_closed ? open : open - window.intervalSeconds * 1000;
}

/**
 * The prefix a rebuild covers: up to the closed bar, starting at the base run's start until the budget
 * slides it. `keptStartMs`, the previous rebuild's start when that rebuild can be extended, is kept
 * until the window would exceed twice the budget.
 */
export function followRange(baseStartMs: number, closedOpenMs: number, intervalMs: number,
  budget = SCRIPT_FOLLOW_BAR_BUDGET, keptStartMs: number | null = null): FollowRange {
  const end = closedOpenMs + intervalMs - 1;
  if (keptStartMs !== null && keptStartMs >= baseStartMs && keptStartMs <= closedOpenMs
    && (closedOpenMs - keptStartMs) / intervalMs + 1 <= 2 * budget) {
    return { start_time_ms: keptStartMs, end_time_ms: end };
  }
  return { start_time_ms: Math.max(baseStartMs, closedOpenMs - (budget - 1) * intervalMs), end_time_ms: end };
}

function stable(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stable);
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.keys(value as Record<string, unknown>).sort()
      .map((key) => [key, stable((value as Record<string, unknown>)[key])]));
  }
  return value;
}

/** An idempotency key that is the input's identity: the same input reuses its run instead of recomputing. */
export async function followInputKey(payload: Record<string, unknown>): Promise<string> {
  const bytes = new TextEncoder().encode(JSON.stringify(stable(payload)));
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", bytes));
  return `follow-${[...digest].map((byte) => byte.toString(16).padStart(2, "0")).join("")}`;
}

/** What the user's last run on the chart was, so its prefix can be rebuilt as bars close. */
export interface ScriptFollowBase<Run> {
  /** The start the user's run resolved to; rebuilds keep it until the budget slides the window. */
  startMs: number;
  /** The end the shown result covers (inclusive). */
  coveredEndMs: number;
  intervalMs: number;
  /** One FIXED run over `range` with the base's inputs, followed to its end; null when the data is not ready. */
  rebuild(range: FollowRange, signal: AbortSignal): Promise<Run | null>;
  /** Whether the engine can extend this rebuild with the next bars (B-157a); then the next one keeps its start. */
  extendable?(run: Run): boolean;
}

/**
 * One cell's FOLLOW loop: rebuild when a newer bar has closed than the shown result covers.
 * At most one rebuild runs; closes during it are folded into a single next rebuild.
 */
export class ScriptFollowController<Run> {
  private base: ScriptFollowBase<Run> | null = null;
  private closedOpenMs: number | null = null;
  /** The last rebuild's start while its engine session can be extended. */
  private keptStartMs: number | null = null;
  private running: AbortController | null = null;
  private again = false;
  private disposed = false;

  constructor(private readonly onRun: (run: Run, range: FollowRange) => void,
    private readonly onError: (failure: unknown) => void) {}

  /** A new base (the user started a run) or none; an in-flight rebuild of the old base is abandoned. */
  setBase(base: ScriptFollowBase<Run> | null): void {
    this.running?.abort();
    this.running = null;
    this.again = false;
    this.keptStartMs = null;
    this.base = base;
    this.check();
  }

  /** The chart's newest closed bar. */
  setClosedBar(openMs: number | null): void {
    this.closedOpenMs = openMs;
    this.check();
  }

  get busy(): boolean { return this.running !== null; }

  /** The end the followed result covers, or null when nothing is followed. */
  get coveredEndMs(): number | null { return this.base?.coveredEndMs ?? null; }

  /** Stop following; an in-flight rebuild is abandoned. */
  dispose(): void {
    this.disposed = true;
    this.running?.abort();
    this.running = null;
  }

  /** Follow again after `dispose` (React StrictMode runs an effect's cleanup and setup twice on mount). */
  resume(): void {
    this.disposed = false;
    this.check();
  }

  private check(): void {
    const base = this.base, closed = this.closedOpenMs;
    if (this.disposed || !base || closed === null || closed + base.intervalMs - 1 <= base.coveredEndMs) return;
    if (this.running) { this.again = true; return; }
    const controller = new AbortController();
    this.running = controller;
    const range = followRange(base.startMs, closed, base.intervalMs, SCRIPT_FOLLOW_BAR_BUDGET, this.keptStartMs);
    void base.rebuild(range, controller.signal).then((run) => {
      if (controller.signal.aborted || this.base !== base) return;
      if (run !== null) {
        base.coveredEndMs = range.end_time_ms;
        this.keptStartMs = base.extendable?.(run) ? range.start_time_ms : null;
        this.onRun(run, range);
      }
    }, (failure: unknown) => {
      if (!controller.signal.aborted) this.onError(failure);
    }).finally(() => {
      if (this.running !== controller) return;
      this.running = null;
      if (this.again) { this.again = false; this.check(); }
    });
  }
}
