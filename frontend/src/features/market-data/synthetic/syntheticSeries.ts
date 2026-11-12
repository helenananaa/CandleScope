import type { DisplayRow } from "../../chart-representation/chartRepresentationTypes.js";
import type { MarketSeries } from "../marketDataTypes.js";
import { resolveKlineSeriesIdentity } from "../klineSeriesIdentity.js";

export interface SyntheticRequest {
  source: Record<string, string>;
  config: { transform: "renko" | "heikin-ashi"; semantics: "display-window/1";
    mode: "traditional" | "atr"; box_size: number; atr_length: number };
  anchor: number;
  through: number;
  limit: number;
}

export interface SyntheticRow extends DisplayRow {
  readonly id: string;
  readonly ordinal: number;
}

export interface SyntheticSnapshot {
  readonly seriesId: string;
  readonly generation: string;
  readonly revision: number;
  readonly status: string;
  readonly reason: string | null;
  readonly from: number;
  readonly total: number;
  readonly rows: readonly SyntheticRow[];
}

export const EMPTY_SYNTHETIC: SyntheticSnapshot = Object.freeze({
  seriesId: "", generation: "", revision: 0, status: "preparing", reason: null,
  from: 0, total: 0, rows: Object.freeze([]),
});

export function syntheticRequest(source: MarketSeries, transform: "renko" | "heikin-ashi",
  settings: { mode?: string; boxSize?: number; atrLength?: number }, anchor: number, through: number): SyntheticRequest {
  const identity = resolveKlineSeriesIdentity(source.exchange, source);
  return {
    source: { symbol: source.symbol, interval: source.interval, exchange: source.exchange, market_type: source.marketType,
      provider_id: identity.providerId, venue: identity.venue, asset_class: identity.assetClass,
      series_variant: identity.seriesVariant, price_adjustment: identity.priceAdjustment,
      session_variant: identity.sessionVariant, volume_semantics: identity.volumeSemantics },
    config: { transform, semantics: "display-window/1",
      mode: settings.mode === "atr" ? "atr" : "traditional",
      box_size: settings.boxSize ?? 1, atr_length: settings.atrLength ?? 14 },
    anchor, through, limit: 5000,
  };
}

function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Invalid synthetic message");
  return value as Record<string, unknown>;
}
function integer(value: unknown): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) throw new Error("Invalid synthetic cursor");
  return value;
}
function text(value: unknown): string {
  if (typeof value !== "string" || !value || value.length > 256) throw new Error("Invalid synthetic identity");
  return value;
}
function deepFreeze<T>(value: T): T {
  if (value && typeof value === "object") {
    Object.freeze(value);
    for (const child of Object.values(value)) if (child && typeof child === "object") deepFreeze(child);
  }
  return value;
}

/** Synthetic ordinals are the record key. Source time is lineage, not a key. */
export function adoptSynthetic(previous: SyntheticSnapshot, raw: unknown, request: SyntheticRequest): SyntheticSnapshot {
  const message = record(raw);
  if (message["type"] === "error") throw new Error(String(message["reason"] || "Synthetic series unavailable"));
  if (message["protocol"] !== "candlescope.synthetic/1") throw new Error("Unsupported synthetic protocol");
  const definition = record(message["definition"]);
  const source = record(definition["source"]), config = record(definition["config"]);
  if (config["algorithm"] !== "close-source/1") throw new Error("Unsupported synthetic algorithm");
  if (Object.entries(request.source).some(([key, value]) => source[key] !== value)
    || Object.entries(request.config).some(([key, value]) => config[key] !== value)
    || definition["anchor"] !== request.anchor || definition["through"] !== request.through) {
    throw new Error("Synthetic series identity changed");
  }
  const seriesId = text(message["series_id"]), generation = text(message["generation"]);
  const revision = integer(message["revision"]), status = text(message["status"]);
  if (previous.seriesId && seriesId !== previous.seriesId) throw new Error("Synthetic series identity changed");
  if (previous.seriesId && revision <= previous.revision) return previous;
  const kind = message["type"];
  if (kind === "status") {
    return Object.freeze({ ...previous, seriesId, generation, revision, status,
      reason: String(message["reason"] || "Synthetic series unavailable") });
  }
  if (kind !== "snapshot" && kind !== "patch") throw new Error("Unsupported synthetic operation");
  if (kind === "patch" && (generation !== previous.generation || revision !== previous.revision + 1)) {
    throw new Error("Synthetic stream requires a new snapshot");
  }
  const from = integer(message["from_index"]), total = integer(message["total"]);
  if (!Array.isArray(message["rows"]) || message["rows"].length > 50_000 || total > 50_000) throw new Error("Synthetic output budget exceeded");
  const rows = message["rows"].map((rawRow, index): SyntheticRow => {
    const row = record(rawRow), ordinal = integer(row["ordinal"]), id = text(row["id"]);
    if (ordinal !== from + index || id !== `${seriesId}:${generation}:${ordinal}`) throw new Error("Invalid synthetic output order");
    for (const field of ["open", "high", "low", "close"]) {
      if (typeof row[field] !== "number" || !Number.isFinite(row[field])) throw new Error("Invalid synthetic price");
    }
    const axis = row["time"];
    if (request.config.transform === "renko") {
      const time = record(axis);
      if (integer(time["order"]) !== ordinal || typeof time["sourceTime"] !== "number"
        || !Number.isSafeInteger(time["sourceTime"]) || time["sourceTime"] < request.anchor
        || time["sourceTime"] > request.through) throw new Error("Invalid synthetic axis");
      integer(time["sourceOrdinal"]);
    } else if (typeof axis !== "number" || !Number.isSafeInteger(axis) || axis < request.anchor || axis > request.through) {
      throw new Error("Invalid synthetic time");
    }
    const lineage = record(record(row["customValues"])["chartProjection"]);
    const sourceFrom = integer(lineage["sourceFromTime"]), sourceTo = integer(lineage["sourceToTime"]);
    if (sourceFrom < request.anchor || sourceTo > request.through || sourceFrom > sourceTo
      || lineage["projectorId"] !== request.config.transform || lineage["synthetic"] !== true) {
      throw new Error("Invalid synthetic lineage");
    }
    return deepFreeze(structuredClone(row)) as unknown as SyntheticRow;
  });
  let nextRows: readonly SyntheticRow[], start = from;
  if (kind === "snapshot") {
    if (from + rows.length !== total) throw new Error("Invalid synthetic snapshot bounds");
    nextRows = rows;
  } else {
    const removed = integer(message["delete_count"]);
    if (from + removed !== previous.total || from + rows.length !== total) throw new Error("Invalid synthetic patch bounds");
    nextRows = from < previous.from ? rows : [...previous.rows.slice(0, from - previous.from), ...rows];
    start = Math.min(from, previous.from);
  }
  if (nextRows.length > request.limit) {
    start += nextRows.length - request.limit;
    nextRows = nextRows.slice(-request.limit);
  }
  return Object.freeze({ seriesId, generation, revision, status,
    reason: message["reason"] == null ? null : String(message["reason"]),
    from: start, total, rows: Object.freeze(nextRows) });
}
