import { getDateTimeLocale, t } from "../../i18n/index.js";
import { drawingName } from "../drawings/drawingObjectLabels.js";
import { ReplayV2ApiError } from "./replayV2Api.js";

/**
 * Replay training saves the whole workspace drawing document. When the server
 * rejects only some drawings it names them (`details.rejected`). Those drawings
 * are left out of the run record at their current revision and the rest is saved
 * again, so one rejected drawing cannot block every later save. Editing a left-out
 * drawing offers it again; deleting it drops it from the list.
 */
export type ReplayDrawingRejectionReason = "UNSUPPORTED_KIND" | "UNSUPPORTED_FIELD" | "INVALID";

export interface ReplayRejectedDrawing {
  readonly chart: string;
  readonly id: string;
  readonly kind: string | null;
  readonly reason: ReplayDrawingRejectionReason;
  /** The tool variant read from the drawing itself (arrow path, ray, price range…), for its name. */
  readonly variant?: string | null;
}

interface ExcludedDrawing extends ReplayRejectedDrawing {
  readonly revision: string;
}

export type ReplayDrawingExclusions = Map<string, ExcludedDrawing>;

type ChartRecord = Readonly<Record<string, unknown>>;

const REASONS: ReadonlySet<string> = new Set(["UNSUPPORTED_KIND", "UNSUPPORTED_FIELD", "INVALID"]);

function exclusionKey(chart: string, id: string): string {
  return `${chart}\u0000${id}`;
}

function entityRevision(entity: unknown): { id: string; revision: string } | null {
  if (entity === null || typeof entity !== "object") return null;
  const { id, geometryRevision, styleRevision } = entity as Record<string, unknown>;
  if (typeof id !== "string" || typeof geometryRevision !== "number" || typeof styleRevision !== "number") return null;
  return { id, revision: `${geometryRevision}:${styleRevision}` };
}

function record(value: unknown): Readonly<Record<string, unknown>> {
  return value !== null && typeof value === "object" ? value as Readonly<Record<string, unknown>> : {};
}

/** The same variant the drawing object list names the drawing by. */
function drawingVariant(entity: unknown): string | null {
  const { kind, geometry: rawGeometry, style: rawStyle } = record(entity);
  const geometry = record(rawGeometry);
  const style = record(rawStyle);
  const text = (value: unknown) => (typeof value === "string" ? value : null);
  switch (kind) {
    case "shape": return text(geometry.shapeType) ?? "rectangle";
    case "path": return style.arrowEnd === true ? "path-arrow" : "path-line";
    case "line": return style.arrowEnd === true ? "line-arrow" : text(geometry.lineType) ?? "line";
    case "axis-line": return `${text(geometry.axisLineType) ?? "horizontal"}-line`;
    case "range-measure": return `measure-${text(geometry.measureType) ?? "price-time"}`;
    default: return text(kind);
  }
}

function chartEntities(chart: ChartRecord | undefined): readonly unknown[] {
  return Array.isArray(chart?.entities) ? chart.entities as readonly unknown[] : [];
}

/** The drawings a rejected save names, or null when it names none that can be traced to a chart. */
export function replayRejectedDrawings(cause: unknown): ReplayRejectedDrawing[] | null {
  if (!(cause instanceof ReplayV2ApiError) || cause.code !== "REVIEW_DRAWING_INVALID") return null;
  const listed = cause.details.rejected;
  if (!Array.isArray(listed) || listed.length === 0) return null;
  const rejected: ReplayRejectedDrawing[] = [];
  for (const item of listed as readonly unknown[]) {
    if (item === null || typeof item !== "object") return null;
    const { chart, id, kind, reason } = item as Record<string, unknown>;
    if (typeof chart !== "string" || typeof id !== "string") return null;
    rejected.push({
      chart,
      id,
      kind: typeof kind === "string" ? kind : null,
      reason: typeof reason === "string" && REASONS.has(reason) ? reason as ReplayDrawingRejectionReason : "INVALID",
    });
  }
  return rejected;
}

/** Leave the named drawings out at their current revision; returns how many were newly left out. */
export function excludeRejectedDrawings(
  exclusions: ReplayDrawingExclusions,
  charts: Readonly<Record<string, ChartRecord>>,
  rejected: readonly ReplayRejectedDrawing[],
): number {
  let added = 0;
  for (const item of rejected) {
    const entity = chartEntities(charts[item.chart]).find((candidate) => entityRevision(candidate)?.id === item.id);
    const current = entityRevision(entity);
    if (!current) continue;
    const key = exclusionKey(item.chart, item.id);
    if (exclusions.get(key)?.revision === current.revision) continue;
    exclusions.set(key, { ...item, variant: drawingVariant(entity), revision: current.revision });
    added += 1;
  }
  return added;
}

/**
 * The workspace document to save, without left-out drawings. A left-out drawing
 * that was edited or deleted stops being left out.
 */
export function replayDrawingSaveDocument(
  runId: string,
  charts: Readonly<Record<string, ChartRecord>>,
  exclusions: ReplayDrawingExclusions,
): {
  document: Readonly<Record<string, unknown>> & { charts: Readonly<Record<string, ChartRecord>> };
  count: number;
  excluded: readonly ReplayRejectedDrawing[];
} {
  const stillExcluded = new Set<string>();
  const kept: Record<string, ChartRecord> = {};
  let count = 0;
  for (const [scope, chart] of Object.entries(charts)) {
    if (!Array.isArray(chart.entities)) {
      kept[scope] = chart;
      continue;
    }
    const entities = chart.entities as readonly unknown[];
    const saved = entities.filter((entity) => {
      const current = entityRevision(entity);
      if (!current) return true;
      const key = exclusionKey(scope, current.id);
      if (exclusions.get(key)?.revision !== current.revision) return true;
      stillExcluded.add(key);
      return false;
    });
    kept[scope] = saved.length === entities.length ? chart : { ...chart, entities: saved };
    count += saved.length;
  }
  for (const key of [...exclusions.keys()]) {
    if (!stillExcluded.has(key)) exclusions.delete(key);
  }
  return {
    document: { documentSchemaVersion: 2, scopeKey: `replay-run:${runId}`, charts: kept },
    count,
    excluded: [...exclusions.values()].map(({ chart, id, kind, reason, variant }) => ({ chart, id, kind, reason, variant })),
  };
}

export function sameRejectedDrawings(
  first: readonly ReplayRejectedDrawing[],
  second: readonly ReplayRejectedDrawing[],
): boolean {
  return first.length === second.length && first.every((item, index) => {
    const other = second[index];
    return other !== undefined && item.chart === other.chart && item.id === other.id
      && item.kind === other.kind && item.reason === other.reason && item.variant === other.variant;
  });
}

function listFormat(items: readonly string[]): string {
  try {
    return new Intl.ListFormat(getDateTimeLocale(), { type: "conjunction" }).format(items);
  } catch {
    return items.join(", ");
  }
}

/** One message naming the left-out drawings and why the run record refused them. */
export function replayRejectedDrawingsMessage(rejected: readonly ReplayRejectedDrawing[]): string {
  const counts = new Map<string, number>();
  for (const item of rejected) {
    const variant = item.variant ?? item.kind;
    const name = variant === null ? item.id : variant === "text" ? t("drawing.objects.text") : drawingName(variant);
    counts.set(name, (counts.get(name) ?? 0) + 1);
  }
  const names = [...counts].map(([name, count]) => (count > 1 ? `${name} (${count})` : name));
  const reasons = [
    rejected.some((item) => item.reason !== "INVALID") ? t("replay.drawings.notSavedUnsupported") : null,
    rejected.some((item) => item.reason === "INVALID") ? t("replay.drawings.notSavedInvalid") : null,
  ].filter((reason): reason is string => reason !== null);
  return [t("replay.drawings.notSaved", { drawings: listFormat(names) }), ...reasons].join(" ");
}
