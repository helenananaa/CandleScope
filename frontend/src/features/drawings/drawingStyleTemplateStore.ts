import type { DrawingStylePatch } from "./drawingInteractionController.js";

export type StyleFamily = "stroke" | "shape" | "fibonacci" | "highlighter";
export interface DrawingStyleTemplate { name: string; family: StyleFamily; style: DrawingStylePatch }
export type TemplateError = "storage" | "invalid" | "duplicate" | "limit";
export type TemplateResult = { ok: true; templates: DrawingStyleTemplate[] } | { ok: false; error: TemplateError };
type TemplateStorage = Pick<Storage, "getItem" | "setItem">;
export const STYLE_TEMPLATE_KEY = "candlescope.drawing-style-templates.v1";
export const STYLE_TEMPLATE_EVENT = "candlescope:drawing-style-templates";

export function styleFamily(type: string): StyleFamily | null {
  if (["rectangle", "ellipse", "shape"].includes(type)) return "shape";
  if (type === "fibonacci") return "fibonacci";
  if (type === "highlighter") return "highlighter";
  return ["line", "line-segment", "line-ray", "line-infinite", "horizontal-line", "vertical-line", "cross-line", "angle-measure", "freehand"].includes(type) ? "stroke" : null;
}

function record(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
function color(value: unknown): string | null {
  if (typeof value !== "string") return null;
  if (/^#[a-f\d]{3}$/i.test(value)) return `#${[...value.slice(1)].map((part) => part + part).join("")}`.toLowerCase();
  return /^#[a-f\d]{6}$/i.test(value) ? value.toLowerCase() : null;
}
function finite(value: unknown, min: number, max: number): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= min && value <= max;
}

/** Explicit allowlist: templates can never carry object identity, coordinates,
 * text content, position risk levels, or future drawing defaults. */
export function templateStyle(family: StyleFamily, value: unknown): DrawingStylePatch | null {
  if (!record(value)) return null;
  const stroke = color(value.color);
  if (!stroke || !finite(value.lineWidth, 1, 10)) return null;
  const style: DrawingStylePatch = { color: stroke, lineWidth: value.lineWidth };
  if (family === "shape") {
    const fill = color(value.fillColor);
    if (!fill || !finite(value.fillOpacity, 0, 1) || !["solid", "dashed", "dotted"].includes(String(value.lineStyle))) return null;
    style.fillColor = fill; style.fillOpacity = value.fillOpacity;
    style.lineStyle = value.lineStyle as "solid" | "dashed" | "dotted";
  }
  if (family === "highlighter") {
    if (!finite(value.opacity, 0.05, 1)) return null;
    style.opacity = value.opacity;
  }
  if (family === "fibonacci") {
    if (!Array.isArray(value.levels) || value.levels.length > 32) return null;
    const levels: NonNullable<DrawingStylePatch["levels"]> = [];
    for (const level of value.levels) {
      if (!record(level) || !finite(level.level, -Number.MAX_VALUE, Number.MAX_VALUE)
        || typeof level.enabled !== "boolean" || !color(level.color)
        || levels.some((item) => Math.abs(item.level - Number(level.level)) < 0.0001)) return null;
      levels.push({ level: level.level, color: color(level.color)!, enabled: level.enabled });
    }
    style.levels = levels;
  }
  return style;
}

export function readStyleTemplates(storage?: TemplateStorage): TemplateResult {
  try {
    const raw = (storage ?? localStorage).getItem(STYLE_TEMPLATE_KEY);
    if (raw === null) return { ok: true, templates: [] };
    if (raw.length > 131072) return { ok: false, error: "invalid" };
    let parsed: unknown;
    try { parsed = JSON.parse(raw); } catch { return { ok: false, error: "invalid" }; }
    if (!record(parsed) || parsed.version !== 1 || !Array.isArray(parsed.templates) || parsed.templates.length > 80) return { ok: false, error: "invalid" };
    const templates: DrawingStyleTemplate[] = [];
    for (const item of parsed.templates) {
      if (!record(item) || !["stroke", "shape", "fibonacci", "highlighter"].includes(String(item.family))
        || typeof item.name !== "string" || !item.name.trim() || item.name !== item.name.trim() || [...item.name].length > 32) return { ok: false, error: "invalid" };
      const family = item.family as StyleFamily;
      const style = templateStyle(family, item.style);
      if (!style || templates.filter((entry) => entry.family === family).length >= 20
        || templates.some((entry) => entry.family === family && entry.name.toLowerCase() === String(item.name).toLowerCase())) return { ok: false, error: "invalid" };
      templates.push({ family, name: item.name, style });
    }
    return { ok: true, templates };
  } catch { return { ok: false, error: "storage" }; }
}

export function changeStyleTemplate(
  action: { kind: "save"; family: StyleFamily; name: string; style: unknown } | { kind: "delete"; family: StyleFamily; name: string },
  storage?: TemplateStorage,
): TemplateResult {
  const loaded = readStyleTemplates(storage);
  if (!loaded.ok) return loaded;
  const name = action.name.trim();
  if (!name || [...name].length > 32) return { ok: false, error: "invalid" };
  let templates = loaded.templates;
  if (action.kind === "save") {
    const style = templateStyle(action.family, action.style);
    if (!style) return { ok: false, error: "invalid" };
    if (templates.some((item) => item.family === action.family && item.name.toLowerCase() === name.toLowerCase())) return { ok: false, error: "duplicate" };
    if (templates.filter((item) => item.family === action.family).length >= 20) return { ok: false, error: "limit" };
    templates = [...templates, { name, family: action.family, style }];
  } else templates = templates.filter((item) => item.family !== action.family || item.name !== name);
  try {
    (storage ?? localStorage).setItem(STYLE_TEMPLATE_KEY, JSON.stringify({ version: 1, templates }));
    if (!storage && typeof window !== "undefined") window.dispatchEvent(new Event(STYLE_TEMPLATE_EVENT));
    return { ok: true, templates };
  } catch { return { ok: false, error: "storage" }; }
}
