import type {
  IndicatorDefinition,
  IndicatorParameterSchema,
  IndicatorParams,
} from "../indicators/indicatorTypes.js";
import type { LocalIndicatorName } from "./localDataTypes.js";


export interface LocalIndicatorCatalogEntry {
  engineName: LocalIndicatorName;
  name: string;
  shortName: string;
  description: string;
  paneTarget: "main" | "sub";
  params: IndicatorParams;
  paramSchema: IndicatorParameterSchema[];
}

const PRICE_SOURCES = ["open", "high", "low", "close", "hl2", "hlc3", "ohlc4"];

export const LOCAL_INDICATOR_CATALOG: readonly LocalIndicatorCatalogEntry[] = [
  {
    engineName: "MA",
    name: "移动平均线",
    shortName: "MA",
    description: "简单移动平均线，叠加在主图。",
    paneTarget: "main",
    params: { period: 20, source: "close", color: "#f59e0b" },
    paramSchema: [
      { key: "period", label: "周期", type: "int", default: 20, min: 1, max: 500 },
      { key: "source", label: "价格源", type: "string", default: "close", options: PRICE_SOURCES },
      { key: "color", label: "颜色", type: "color", default: "#f59e0b" },
    ],
  },
  {
    engineName: "EMA",
    name: "指数移动平均线",
    shortName: "EMA",
    description: "指数加权移动平均线，叠加在主图。",
    paneTarget: "main",
    params: { period: 20, source: "close", color: "#3b82f6" },
    paramSchema: [
      { key: "period", label: "周期", type: "int", default: 20, min: 1, max: 500 },
      { key: "source", label: "价格源", type: "string", default: "close", options: PRICE_SOURCES },
      { key: "color", label: "颜色", type: "color", default: "#3b82f6" },
    ],
  },
  {
    engineName: "RSI",
    name: "相对强弱指标",
    shortName: "RSI",
    description: "独立窗格中的相对强弱指标。",
    paneTarget: "sub",
    params: { period: 14, source: "close", color: "#a855f7" },
    paramSchema: [
      { key: "period", label: "周期", type: "int", default: 14, min: 2, max: 100 },
      { key: "source", label: "价格源", type: "string", default: "close", options: PRICE_SOURCES },
      { key: "color", label: "颜色", type: "color", default: "#a855f7" },
    ],
  },
  {
    engineName: "MACD",
    name: "指数平滑异同移动平均线",
    shortName: "MACD",
    description: "DIF、DEA 与柱状图，显示在独立窗格。",
    paneTarget: "sub",
    params: {
      fast: 12,
      slow: 26,
      signal: 9,
      source: "close",
      hist_up_color: "#22c55e",
      hist_down_color: "#ef4444",
    },
    paramSchema: [
      { key: "fast", label: "快线", type: "int", default: 12, min: 1, max: 100 },
      { key: "slow", label: "慢线", type: "int", default: 26, min: 1, max: 200 },
      { key: "signal", label: "信号线", type: "int", default: 9, min: 1, max: 50 },
      { key: "source", label: "价格源", type: "string", default: "close", options: PRICE_SOURCES },
      { key: "hist_up_color", label: "正柱颜色", type: "color", default: "#22c55e" },
      { key: "hist_down_color", label: "负柱颜色", type: "color", default: "#ef4444" },
    ],
  },
  {
    engineName: "BOLL",
    name: "布林带",
    shortName: "BOLL",
    description: "中轨、上轨和下轨，叠加在主图。",
    paneTarget: "main",
    params: {
      period: 20,
      mult: 2,
      source: "close",
      color_middle: "#f59e0b",
      color_upper: "#ef4444",
      color_lower: "#22c55e",
    },
    paramSchema: [
      { key: "period", label: "周期", type: "int", default: 20, min: 2, max: 200 },
      { key: "mult", label: "倍数", type: "float", default: 2, min: 0.5, max: 5, step: 0.5 },
      { key: "source", label: "价格源", type: "string", default: "close", options: PRICE_SOURCES },
      { key: "color_middle", label: "中轨", type: "color", default: "#f59e0b" },
      { key: "color_upper", label: "上轨", type: "color", default: "#ef4444" },
      { key: "color_lower", label: "下轨", type: "color", default: "#22c55e" },
    ],
  },
] as const;

const CATALOG_BY_NAME = new Map(
  LOCAL_INDICATOR_CATALOG.map((entry) => [entry.engineName, entry]),
);
let localIndicatorOrdinal = 0;

function normalizeParams(
  entry: LocalIndicatorCatalogEntry,
  supplied: IndicatorParams | undefined,
): IndicatorParams {
  const next: IndicatorParams = { ...entry.params };
  for (const schema of entry.paramSchema) {
    const key = schema.key ?? schema.name;
    if (!key || supplied?.[key] === undefined) continue;
    const value = supplied[key];
    if (schema.type === "int" || schema.type === "float") {
      if (typeof value !== "number" || !Number.isFinite(value)) continue;
      if (schema.type === "int" && !Number.isInteger(value)) continue;
      if (schema.min !== undefined && value < schema.min) continue;
      if (schema.max !== undefined && value > schema.max) continue;
    } else if (schema.type === "color") {
      if (typeof value !== "string" || !/^#[0-9a-fA-F]{6}$/.test(value)) continue;
    } else if (schema.options !== undefined) {
      if (typeof value !== "string" || !schema.options.includes(value)) continue;
    }
    next[key] = value;
  }
  return next;
}

function newIndicatorId(name: LocalIndicatorName): string {
  localIndicatorOrdinal += 1;
  const random = globalThis.crypto?.randomUUID?.().replaceAll("-", "")
    ?? `${Date.now().toString(36)}${localIndicatorOrdinal.toString(36)}`;
  return `local-${name.toLowerCase()}-${random}`;
}

export function localIndicatorCatalogEntry(
  name: string | null | undefined,
): LocalIndicatorCatalogEntry | null {
  return CATALOG_BY_NAME.get(String(name || "").toUpperCase() as LocalIndicatorName) ?? null;
}

export function createLocalIndicatorDefinition(
  name: LocalIndicatorName,
): IndicatorDefinition {
  const entry = CATALOG_BY_NAME.get(name);
  if (!entry) throw new Error(`Unknown local indicator ${name}`);
  return definitionFromEntry(entry, newIndicatorId(name));
}

function definitionFromEntry(
  entry: LocalIndicatorCatalogEntry,
  id: string,
): IndicatorDefinition {
  return {
    id,
    executionTarget: "local",
    name: entry.shortName,
    engineName: entry.engineName,
    params: { ...entry.params },
    visible: true,
    lines: [],
    description: entry.description,
    category: "Local builtin",
    paneTarget: entry.paneTarget,
    paramSchema: entry.paramSchema.map((schema) => ({ ...schema })),
    isPreset: true,
    is_builtin: true,
    kind: "builtin",
  };
}

export function normalizeLocalIndicatorDefinition(
  indicator: IndicatorDefinition,
): IndicatorDefinition | null {
  const entry = localIndicatorCatalogEntry(indicator.engineName);
  if (entry === null || !indicator.id.startsWith("local-")) return null;
  return {
    ...definitionFromEntry(entry, indicator.id),
    params: normalizeParams(entry, indicator.params),
    visible: indicator.visible !== false,
    lines: indicator.lines ?? [],
    ...(indicator.error === undefined ? {} : { error: indicator.error }),
  };
}
