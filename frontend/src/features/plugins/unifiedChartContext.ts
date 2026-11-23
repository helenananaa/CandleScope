import { useLayoutEffect, useRef } from "react";
import type { UnifiedIdentity } from "../../../desktop/unified-entry-lifecycle.mjs";
import type { SeriesWindowView } from "../market-data/window/seriesWindowView.js";
import { unifiedBackgroundRequest } from "./pluginPlatformApi.js";

export const MAX_PLUGIN_CHART_BARS = 256;
const schema = "candlescope.unified-chart/1";
export type PluginChartMode = "live" | "quick-replay" | "history-study" | "replay" | "replay-review" | "strategy-replay";
export interface PluginChartObservation {
  mode: PluginChartMode;
  runId: string | null;
  trackId: string | null;
  seriesId: string;
  symbol: string;
  interval: string;
  dataRevision: string;
  visibleThroughMs: number;
}
export interface PluginChartScope extends PluginChartObservation {
  schema: typeof schema;
  documentId: string;
  chartId: string;
  instanceId: string;
}
export interface PluginChartBar {
  openTimeMs: number;
  observedThroughMs: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number | null;
  closed: boolean;
}
export interface PluginChartPoint { timeMs: number; value: number }
export interface PluginChartReceipt {
  scope: PluginChartScope;
  identity: UnifiedIdentity;
  instanceId: string;
  result: { points: PluginChartPoint[] };
}
type ChartTarget = { sessionId: string; frontendInstanceId: string; entryId: string }
  | { sessionId: string; pluginId: string; identity: UnifiedIdentity; instanceId: string; entryId: string };
type Source = {
  observe(): PluginChartObservation | null;
  bars(observation: PluginChartObservation): PluginChartBar[];
  subscribe?(listener: () => void): () => void;
};
type Chart = { source: Source; instanceId: string; pending: Map<AbortController, PluginChartScope> };
type Transport = (body: unknown, signal: AbortSignal) => Promise<unknown>;

function matches<T extends object>(expected: T, value: unknown): boolean {
  if (!value || typeof value !== "object") return false;
  const entries = Object.entries(expected);
  return Object.keys(value).length === entries.length
    && entries.every(([key, field]) => (value as Record<string, unknown>)[key] === field);
}

export class PluginChartOwner {
  private charts = new Map<string, Chart>();
  private documentId = "";

  constructor(private readonly transport: Transport, private readonly makeId: () => string = () => crypto.randomUUID()) {}

  get id(): string {
    return this.documentId ||= this.makeId();
  }

  attach(chartId: string, source: Source) {
    const previous = this.charts.get(chartId);
    if (previous) for (const call of previous.pending.keys()) call.abort();
    const chart: Chart = { source, instanceId: this.makeId(), pending: new Map() };
    this.charts.set(chartId, chart);
    return {
      update: (next: Source) => {
        chart.source = next;
        this.revokeChanged(chartId, chart);
      },
      dispose: () => {
        for (const call of chart.pending.keys()) call.abort();
        if (this.charts.get(chartId) === chart) this.charts.delete(chartId);
      },
    };
  }

  private scope(chartId: string, chart: Chart): PluginChartScope | null {
    const observation = chart.source.observe();
    if (!observation) return null;
    return { ...observation, schema, documentId: this.id, chartId, instanceId: chart.instanceId };
  }

  private revokeChanged(chartId: string, chart: Chart) {
    if (!chart.pending.size) return;
    const current = this.scope(chartId, chart);
    for (const [controller, scope] of chart.pending) {
      if (!matches(scope, current)) controller.abort();
    }
  }

  list(): PluginChartScope[] {
    return [...this.charts].flatMap(([chartId, chart]) => {
      const scope = this.scope(chartId, chart);
      return scope ? [scope] : [];
    });
  }

  isCurrent(scope: PluginChartScope): boolean {
    const chart = this.charts.get(scope.chartId);
    const current = chart ? this.scope(scope.chartId, chart) : null;
    return current !== null && matches(current, scope);
  }

  async invoke(scope: PluginChartScope, target: ChartTarget, input: unknown): Promise<PluginChartReceipt> {
    const chart = this.charts.get(scope.chartId);
    const pinned = chart ? this.scope(scope.chartId, chart) : null;
    if (!chart || !pinned || !matches(pinned, scope)) throw new Error("Chart observation changed");
    if (chart.pending.size >= 8) throw new Error("Chart computation limit reached");
    const bars = chart.source.bars(pinned);
    if (!bars.length || bars.length > MAX_PLUGIN_CHART_BARS) throw new Error("No bounded chart frame available");
    const abort = new AbortController();
    chart.pending.set(abort, pinned);
    const unsubscribe = chart.source.subscribe?.(() => this.revokeChanged(pinned.chartId, chart));
    try {
      const result = await this.transport({ target, scope: pinned, bars, input: input ?? null }, abort.signal) as PluginChartReceipt;
      if (abort.signal.aborted || this.charts.get(pinned.chartId) !== chart || !matches(pinned, this.scope(pinned.chartId, chart))
        || !matches(pinned, result?.scope)) throw new Error("Chart observation changed");
      if ("identity" in target && (!matches(target.identity, result.identity) || target.instanceId !== result.instanceId)) {
        throw new Error("Plugin execution instance changed");
      }
      return result;
    } finally {
      unsubscribe?.();
      chart.pending.delete(abort);
    }
  }
}

export const pluginChartOwner = new PluginChartOwner((body, signal) => unifiedBackgroundRequest("/invoke-chart", body, signal));

export function usePluginChartSource(chartId: string, source: Source | null): void {
  const lease = useRef<ReturnType<PluginChartOwner["attach"]> | null>(null);
  const enabled = source !== null;
  useLayoutEffect(() => {
    if (!enabled) return undefined;
    // The following layout effect installs the committed observation before paint.
    const attachment = pluginChartOwner.attach(chartId, { observe: () => null, bars: () => [] });
    lease.current = attachment;
    return () => { attachment.dispose(); lease.current = null; };
  }, [chartId, enabled]);
  useLayoutEffect(() => {
    if (source) lease.current?.update(source);
  });
}

export function pluginChartBar(
  openTimeMs: number, observedThroughMs: number, closed: boolean,
  bar: { open?: number | string; high?: number | string; low?: number | string; close?: number | string; volume?: number | string | null },
): PluginChartBar | null {
  const [open, high, low, close] = [bar.open, bar.high, bar.low, bar.close].map(Number);
  const volume = bar.volume == null ? null : Number(bar.volume);
  if (![open, high, low, close].every(Number.isFinite)
    || !Number.isSafeInteger(openTimeMs) || !Number.isSafeInteger(observedThroughMs)
    || observedThroughMs < openTimeMs || (volume !== null && !Number.isFinite(volume))) return null;
  return { openTimeMs, observedThroughMs, closed, open: open!, high: high!, low: low!, close: close!, volume };
}

type Row = Parameters<typeof pluginChartBar>[3];
export function observePluginBar(open: number, end: number, closed: boolean, row: Row): PluginChartBar[] {
  const bar = pluginChartBar(open, end, closed, row);
  return bar ? [bar] : [];
}

const revisions = new WeakMap<object, number>();
let nextRevision = 0;
export function pluginProjectionRevision(frame: object): number {
  const current = revisions.get(frame);
  if (current !== undefined) return current;
  const revision = ++nextRevision;
  revisions.set(frame, revision);
  return revision;
}

export function livePluginChartSource(store: SeriesWindowView, symbol: string, interval: string): Source {
  let version = -1;
  let horizon = 0;
  return {
    observe() {
      if (store.isEmpty() || !store.seriesKey) return null;
      const current = Number(store.version);
      if (version !== current) {
        version = current;
        horizon = Date.now();
      }
      return {
        mode: "live", runId: null, trackId: null, seriesId: store.seriesKey, symbol, interval,
        dataRevision: `${pluginProjectionRevision(store)}:${current}`, visibleThroughMs: horizon,
      };
    },
    bars({ visibleThroughMs }) {
      const rows = store.snapshot().slice(-MAX_PLUGIN_CHART_BARS);
      return rows.flatMap((row, index) => {
        const open = Number(row.time) * 1000;
        if (open > visibleThroughMs || (row.is_closed !== true && index !== rows.length - 1)) return [];
        // The next published bar opening is the exact upper bound even for
        // calendar intervals. The tail is known only as of this live observation.
        const next = rows[index + 1];
        const end = next ? Math.min(visibleThroughMs, Number(next.time) * 1000 - 1) : visibleThroughMs;
        return observePluginBar(open, end, row.is_closed === true, row);
      });
    },
    subscribe: listener => store.subscribe(listener),
  };
}
