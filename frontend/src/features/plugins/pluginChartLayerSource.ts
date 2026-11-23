import type {
  PluginChartLayer,
  PluginChartLayerV2,
  PluginChartRenderItem,
  PluginMarketIdentity,
} from "./pluginPlatformTypes.js";

export interface PluginChartRenderEntry {
  id: string;
  item: Exclude<PluginChartRenderItem, { type: "marker" }>;
  zOrder: "above-series" | "below-series";
}

export interface PluginChartLayerSnapshot {
  entries: readonly PluginChartRenderEntry[];
  revision: number;
}

/** What the chart-layer renderer reads: plugin layers, strategy overlays, or both combined. */
export interface ChartLayerSource {
  getSnapshot(): PluginChartLayerSnapshot;
  subscribe(listener: () => void): () => void;
}

/** Draw several chart-layer sources as one; entries keep their own ids and z-order. */
export function combineChartLayerSources(
  values: readonly (ChartLayerSource | null | undefined)[],
): ChartLayerSource | null {
  const sources = values.filter((value): value is ChartLayerSource => value != null);
  if (sources.length <= 1) return sources[0] ?? null;
  let revision = 0;
  let key = "";
  let cached: PluginChartLayerSnapshot = { entries: [], revision };
  return {
    getSnapshot() {
      const snapshots = sources.map((source) => source.getSnapshot());
      const next = snapshots.map((snapshot) => snapshot.revision).join(":");
      if (next !== key) {
        key = next;
        revision += 1;
        cached = { entries: snapshots.flatMap((snapshot) => [...snapshot.entries]), revision };
      }
      return cached;
    },
    subscribe(listener) {
      const stops = sources.map((source) => source.subscribe(listener));
      return () => { for (const stop of stops) stop(); };
    },
  };
}

const EMPTY_SNAPSHOT: PluginChartLayerSnapshot = Object.freeze({
  entries: Object.freeze([]),
  revision: 0,
});

function isV2Layer(layer: PluginChartLayer): layer is PluginChartLayerV2 {
  return layer.render.schemaVersion === "candlescope.render/2";
}

function isAnalysisItem(
  item: PluginChartRenderItem,
): item is Exclude<PluginChartRenderItem, { type: "marker" }> {
  return item.type !== "marker";
}

export class PluginChartLayerSource {
  private snapshot: PluginChartLayerSnapshot = EMPTY_SNAPSHOT;
  private readonly listeners = new Set<() => void>();
  private key = "[]";

  getSnapshot(): PluginChartLayerSnapshot {
    return this.snapshot;
  }

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  update(layers: readonly PluginChartLayer[], identity: PluginMarketIdentity): void {
    const selectedLayers = layers.filter((layer): layer is PluginChartLayerV2 => (
      isV2Layer(layer)
      && layer.chartId === "main-chart"
      && layer.context.mode === "live"
      && layer.context.exchange === identity.exchange
      && layer.context.marketType === identity.marketType
      && layer.series.symbol === identity.symbol
      && layer.series.interval === identity.interval
    ));
    const nextKey = JSON.stringify(selectedLayers.map((layer) => [
      layer.id,
      layer.generation,
      layer.revision,
      layer.chartRevision,
      layer.zOrder,
    ]));
    if (nextKey === this.key) return;
    const entries = selectedLayers
      .flatMap((layer) => layer.render.items
        .filter(isAnalysisItem)
        .map((item) => ({
          id: `plugin:${layer.id}:${item.id}`,
          item,
          zOrder: layer.zOrder,
        } satisfies PluginChartRenderEntry)));
    this.key = nextKey;
    this.snapshot = Object.freeze({
      entries: Object.freeze(entries),
      revision: this.snapshot.revision + 1,
    });
    for (const listener of this.listeners) listener();
  }
}
