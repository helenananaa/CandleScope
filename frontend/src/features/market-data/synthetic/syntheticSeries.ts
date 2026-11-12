import type { DisplayRow } from "../../chart-representation/chartRepresentationTypes.js";
import type { MarketSeries } from "../marketDataTypes.js";
import { resolveKlineSeriesIdentity } from "../klineSeriesIdentity.js";

export const SYNTHETIC_TRANSFORMS = ["heikin-ashi", "renko", "point-and-figure", "kagi", "line-break"] as const;
export type SyntheticTransform = typeof SYNTHETIC_TRANSFORMS[number];
export function isSyntheticTransform(value: string): value is SyntheticTransform {
  return (SYNTHETIC_TRANSFORMS as readonly string[]).includes(value);
}
export interface SyntheticSettings {
  mode?: string; boxSize?: number; atrLength?: number; reversalAmount?: number; numberOfLines?: number;
}
export type SyntheticOrigin =
  | { kind: "CAPTURED_WINDOW"; capture_id: string; cutoff_ms: number }
  | { kind: "RUN_RESULT"; run_id: string; config_hash: string; report_hash: string; chart_hash: string }
  | { kind: "FROZEN_SNAPSHOT"; dataset_id: string; data_epoch: string; snapshot_hash: string; run_id: string; chart_hash: string }
  | { kind: "LOCAL_DATASET"; dataset_id: string; data_epoch: string }
  | { kind: "REPLAY"; session_id: string; track_id: string; data_epoch: string;
      revealed_boundary_ms: number; source_sequence: number; history_epoch?: string };
export type BackendSyntheticSource = MarketSeries & {
  syntheticOrigin?: SyntheticOrigin;
  syntheticSeriesKey?: string;
  syntheticCapture?: { scope: string; cutoff_ms: number };
};
export interface SyntheticRequest {
  source: Record<string, string>;
  config: { transform: SyntheticTransform; semantics: "display-window/1";
    mode: "traditional" | "atr"; box_size: number; atr_length: number;
    reversal_amount: number; number_of_lines: number };
  anchor: number;
  through: number;
  limit: number;
  complete_window: boolean;
  origin?: SyntheticOrigin;
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

function boundedInteger(value: number | undefined, fallback: number, min: number, max: number): number {
  const number = Math.trunc(Number(value));
  return Number.isFinite(number) && number >= min && number <= max ? number : fallback;
}
function positiveSetting(value: number | undefined, fallback: number): number {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : fallback;
}
export function syntheticRequest(source: BackendSyntheticSource, transform: SyntheticTransform,
  settings: SyntheticSettings, anchor: number, through: number): SyntheticRequest {
  const identity = resolveKlineSeriesIdentity(source.exchange, source);
  return {
    source: { symbol: source.symbol, interval: source.interval, exchange: source.exchange, market_type: source.marketType,
      provider_id: identity.providerId, venue: identity.venue, asset_class: identity.assetClass,
      series_variant: identity.seriesVariant, price_adjustment: identity.priceAdjustment,
      session_variant: identity.sessionVariant, volume_semantics: identity.volumeSemantics },
    config: { transform, semantics: "display-window/1",
      mode: settings.mode === "atr" ? "atr" : "traditional",
      box_size: positiveSetting(settings.boxSize, 1),
      atr_length: Math.max(2, Math.min(500, Math.trunc(Number(settings.atrLength)) || 14)),
      reversal_amount: transform === "kagi" ? positiveSetting(settings.reversalAmount, 1)
        : boundedInteger(settings.reversalAmount, 3, 1, 100),
      number_of_lines: boundedInteger(settings.numberOfLines, 3, 1, 50) },
    anchor, through, limit: 5000, complete_window: true,
    ...(source.syntheticOrigin ? { origin: source.syntheticOrigin } : {}),
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
function positive(value: unknown): boolean {
  return typeof value === "number" && Number.isFinite(value) && value > 0;
}
function validateRepresentation(row: Record<string, unknown>, transform: SyntheticTransform) {
  if (transform === "heikin-ashi") return;
  const custom = record(row["customValues"]);
  const field = { renko: "renko", "point-and-figure": "pointAndFigure", kagi: "kagi", "line-break": "lineBreak" }[transform];
  const values = record(custom[field]);
  const direction = values["direction"];
  if (values["source"] !== "close") throw new Error("Invalid synthetic price source");
  if (transform === "point-and-figure") {
    if (!["x", "o"].includes(String(direction)) || !positive(values["boxSize"])
      || !Number.isSafeInteger(values["reversalAmount"]) || !positive(values["reversalAmount"])) throw new Error("Invalid Point & Figure column");
  } else {
    if (!["up", "down"].includes(String(direction))) throw new Error("Invalid synthetic direction");
    if (transform === "renko" && (!positive(values["boxSize"]) || values["wickPolicy"] !== "none")) throw new Error("Invalid Renko brick");
    if (transform === "line-break" && (!Number.isSafeInteger(values["numberOfLines"]) || !positive(values["numberOfLines"])
      || typeof values["referenceHigh"] !== "number" || !Number.isFinite(values["referenceHigh"])
      || typeof values["referenceLow"] !== "number" || !Number.isFinite(values["referenceLow"]))) throw new Error("Invalid Line Break reference");
    if (transform === "kagi") {
      const sections = values["sections"];
      if (!["yang", "yin"].includes(String(values["state"])) || !positive(values["reversalAmount"])
        || !Number.isSafeInteger(values["reversalTicks"]) || !positive(values["reversalTicks"])
        || !Array.isArray(sections) || sections.length < 1 || sections.length > 2) throw new Error("Invalid Kagi leg");
      for (const raw of sections) {
        const section = record(raw);
        if (typeof section["from"] !== "number" || !Number.isFinite(section["from"])
          || typeof section["to"] !== "number" || !Number.isFinite(section["to"])
          || !["yang", "yin"].includes(String(section["style"]))) throw new Error("Invalid Kagi section");
      }
    }
  }
}

/** Synthetic ordinals are the record key. Source time is lineage, not a key. */
export function adoptSynthetic(previous: SyntheticSnapshot, raw: unknown, request: SyntheticRequest): SyntheticSnapshot {
  const message = record(raw);
  if (message["type"] === "error") throw new Error(String(message["reason"] || "Synthetic series unavailable"));
  if (message["protocol"] !== "candlescope.synthetic/1") throw new Error("Unsupported synthetic protocol");
  const definition = record(message["definition"]);
  const source = record(definition["source"]), config = record(definition["config"]);
  const origin = definition["origin"];
  if (request.origin ? (!origin || typeof origin !== "object" || Array.isArray(origin)
    || Object.keys(origin).length !== Object.keys(request.origin).length
    || Object.entries(request.origin).some(([key, value]) => (origin as Record<string, unknown>)[key] !== value))
    : origin != null) throw new Error("Synthetic source origin changed");
  if (config["algorithm"] !== "close-source/2") throw new Error("Unsupported synthetic algorithm");
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
    if (Number(row["high"]) < Math.max(Number(row["open"]), Number(row["close"]), Number(row["low"]))
      || Number(row["low"]) > Math.min(Number(row["open"]), Number(row["close"]))) throw new Error("Invalid synthetic OHLC");
    const axis = row["time"];
    if (request.config.transform !== "heikin-ashi") {
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
    validateRepresentation(row, request.config.transform);
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
  const retention = request.complete_window ? 50_000 : request.limit;
  if (nextRows.length > retention) {
    start += nextRows.length - retention;
    nextRows = nextRows.slice(-retention);
  }
  return Object.freeze({ seriesId, generation, revision, status,
    reason: message["reason"] == null ? null : String(message["reason"]),
    from: start, total, rows: Object.freeze(nextRows) });
}
