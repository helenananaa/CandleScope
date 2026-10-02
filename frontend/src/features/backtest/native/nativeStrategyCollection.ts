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
  language: "pine" | "pyne";
  executionMode?: "NATIVE" | "CANDLESCOPE";
  drafts: Record<string, string>;
  runs: Record<string, string>;
  runHistory?: Record<string, string[]>;
}
export interface NativeStrategyCollection {
  activeId: string;
  items: NativeStrategyInstance[];
  comparisons?: Record<string, NativeComparisonSelection>;
}
export function normalizeNativeStrategies(value: unknown): NativeStrategyCollection {
  const raw = value && typeof value === "object" ? value as Record<string, unknown> : {};
  const ids = new Set<string>();
  const strings = (input: unknown): Record<string, string> => Object.fromEntries(Object.entries(input && typeof input === "object" ? input : {}).filter(([key, item]) => key !== "__proto__" && typeof item === "string"));
  const items: NativeStrategyInstance[] = [];
  const entries: unknown[] = Array.isArray(raw.items) ? raw.items : [];
  for (const candidate of entries) {
    if (!candidate || typeof candidate !== "object") continue;
    const entry = candidate as Record<string, unknown>;
    if (!entry || typeof entry !== "object" || typeof entry.id !== "string" || !entry.id || ids.has(entry.id)) continue;
    ids.add(entry.id);
    const history = entry.runHistory && typeof entry.runHistory === "object" ? Object.fromEntries(Object.entries(entry.runHistory).map(([key, value]) => [key, Array.isArray(value) ? [...new Set((value as unknown[]).filter((id): id is string => typeof id === "string" && !!id))] : []])) : undefined;
    items.push({ ...(history ? { runHistory: history } : {}), id: entry.id, name: typeof entry.name === "string" ? entry.name.slice(0, 80) : "", language: entry.language === "pyne" ? "pyne" : "pine", drafts: strings(entry.drafts), runs: strings(entry.runs), ...(entry.executionMode === "CANDLESCOPE" ? { executionMode: "CANDLESCOPE" as const } : {}) });
  }
  if (!items.length && !Array.isArray(raw.items)) items.push({ id: "default", name: "", language: "pine", drafts: {}, runs: {} });
  return { activeId: typeof raw.activeId === "string" && items.some((item) => item.id === raw.activeId) ? raw.activeId : items[0]?.id ?? "", items, ...(raw.comparisons && typeof raw.comparisons === "object" ? { comparisons: Object.fromEntries(Object.entries(raw.comparisons).map(([key, value]) => [key, normalizeComparison(value)])) } : {}) };
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
