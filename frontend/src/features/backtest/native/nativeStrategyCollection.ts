import { isRetiredPyneStrategyLanguage, retiredStrategyId, type RetiredStrategyRecord } from "../chart-tester/retiredPyneStrategy.js";

export interface PinnedStrategyRun { id: string; name: string; runId: string; mode: "NATIVE" | "CANDLESCOPE" }
export interface NativeComparisonSelection { name: string; pinned: PinnedStrategyRun[]; metric: "returnPct" | "drawdownPct" }
export function normalizeComparison(value: unknown): NativeComparisonSelection {
  const raw = value && typeof value === "object" ? value as Record<string, unknown> : {};
  const entries: unknown[] = Array.isArray(raw.pinned) ? raw.pinned : [];
  const pinned: PinnedStrategyRun[] = [];
  for (const candidate of entries) {
    if (!candidate || typeof candidate !== "object") continue;
    const item = candidate as Record<string, unknown>;
    if (typeof item.id !== "string" || typeof item.runId !== "string" || !item.id || !item.runId || pinned.some((p) => p.id === item.id) || pinned.length >= 4) continue;
    if (item.mode !== "NATIVE" && item.mode !== "CANDLESCOPE") continue;
    pinned.push({ id: item.id, runId: item.runId, name: typeof item.name === "string" ? item.name.slice(0, 80) : item.id, mode: item.mode });
  }
  return { name: typeof raw.name === "string" ? raw.name.slice(0, 80) : "", pinned, metric: raw.metric === "drawdownPct" ? "drawdownPct" : "returnPct" };
}
export interface NativeStrategyInstance {
  id: string;
  name: string;
  language: "pine";
  executionMode?: "NATIVE" | "CANDLESCOPE";
  drafts: Record<string, string>;
  runs: Record<string, string>;
  runHistory?: Record<string, string[]>;
}
export interface NativeStrategyCollection {
  activeId: string;
  items: NativeStrategyInstance[];
  /**
   * Pyne entries saved by builds before PR #105, kept exactly as stored. They are listed as
   * retired, never selected or run, and never become Pine. Only the user removes them.
   */
  retired?: RetiredStrategyRecord[];
  comparisons?: Record<string, NativeComparisonSelection>;
}

function retiredEntry(value: unknown): RetiredStrategyRecord | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const entry = value as Record<string, unknown>;
  if (!isRetiredPyneStrategyLanguage(entry.language) || typeof entry.id !== "string" || !entry.id) return null;
  try {
    const stored = JSON.parse(JSON.stringify(entry)) as unknown;
    return stored && typeof stored === "object" && !Array.isArray(stored) ? stored as RetiredStrategyRecord : null;
  } catch {
    return { id: entry.id, language: entry.language, ...(typeof entry.name === "string" ? { name: entry.name.slice(0, 80) } : {}) };
  }
}
export function normalizeNativeStrategies(value: unknown): NativeStrategyCollection {
  const raw = value && typeof value === "object" ? value as Record<string, unknown> : {};
  const ids = new Set<string>();
  const strings = (input: unknown): Record<string, string> => Object.fromEntries(Object.entries(input && typeof input === "object" ? input : {}).filter(([key, item]) => key !== "__proto__" && typeof item === "string"));
  const items: NativeStrategyInstance[] = [];
  const retired: RetiredStrategyRecord[] = [];
  const keepRetired = (candidate: unknown) => {
    const entry = retiredEntry(candidate);
    if (entry && !retired.some((other) => retiredStrategyId(other) === retiredStrategyId(entry))) retired.push(entry);
  };
  const entries: unknown[] = Array.isArray(raw.items) ? raw.items : [];
  for (const candidate of entries) {
    if (!candidate || typeof candidate !== "object") continue;
    const entry = candidate as Record<string, unknown>;
    if (isRetiredPyneStrategyLanguage(entry.language)) { keepRetired(entry); continue; }
    if (!entry || typeof entry !== "object" || typeof entry.id !== "string" || !entry.id || ids.has(entry.id)) continue;
    if (entry.language !== "pine") continue;
    ids.add(entry.id);
    const history = entry.runHistory && typeof entry.runHistory === "object" ? Object.fromEntries(Object.entries(entry.runHistory).map(([key, value]) => [key, Array.isArray(value) ? [...new Set((value as unknown[]).filter((id): id is string => typeof id === "string" && !!id))] : []])) : undefined;
    items.push({ ...(history ? { runHistory: history } : {}), id: entry.id, name: typeof entry.name === "string" ? entry.name.slice(0, 80) : "", language: "pine", drafts: strings(entry.drafts), runs: strings(entry.runs), ...(entry.executionMode === "CANDLESCOPE" ? { executionMode: "CANDLESCOPE" as const } : {}) });
  }
  if (Array.isArray(raw.retired)) raw.retired.forEach(keepRetired);
  if (!items.length && !Array.isArray(raw.items)) items.push({ id: "default", name: "", language: "pine", drafts: {}, runs: {} });
  return { activeId: typeof raw.activeId === "string" && items.some((item) => item.id === raw.activeId) ? raw.activeId : items[0]?.id ?? "", items, ...(retired.length ? { retired } : {}), ...(raw.comparisons && typeof raw.comparisons === "object" ? { comparisons: Object.fromEntries(Object.entries(raw.comparisons).map(([key, value]) => [key, normalizeComparison(value)])) } : {}) };
}
/** The collection without one retired Pyne entry: the user's remove, and nothing else changes. */
export function withoutRetiredStrategy(collection: NativeStrategyCollection, id: string): NativeStrategyCollection {
  const { retired = [], ...rest } = collection;
  const kept = retired.filter((entry) => retiredStrategyId(entry) !== id);
  return kept.length ? { ...rest, retired: kept } : rest;
}
export function strategyInstanceScope(scope: string, id: string): string {
  return id === "default" ? scope : `${scope}:strategy:${id}`;
}
export function copyNativeStrategy(item: NativeStrategyInstance, id: string, name: string): NativeStrategyInstance {
  return { ...item, id, name, drafts: { ...item.drafts }, runs: {}, runHistory: {} };
}

export function recordStrategyRun(item: NativeStrategyInstance, context: string, id: string): Partial<NativeStrategyInstance> {
  return { runs: { ...item.runs, [context]: id }, runHistory: { ...item.runHistory,
    [context]: [...new Set([id, ...(item.runHistory?.[context] ?? []), ...(item.runs[context] ? [item.runs[context]!] : [])])] } };
}
export function strategyRunIds(item: NativeStrategyInstance, mode: string): Set<string> {
  const ids = new Set<string>();
  for (const key of new Set([...Object.keys(item.runs), ...Object.keys(item.runHistory ?? {})])) {
    try { const context: unknown = JSON.parse(key); if (!Array.isArray(context) || context[0] !== mode) continue; } catch { continue; }
    if (item.runs[key]) ids.add(item.runs[key]!);
    for (const id of item.runHistory?.[key] ?? []) ids.add(id);
  }
  return ids;
}
