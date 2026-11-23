/**
 * Pyne was removed in PR #105 (2026-10-26). Builds before it saved strategies
 * with `language: "pyne"`: browser drafts, a chart's strategy attachment and a
 * chart's native strategy entries. They are kept as the user stored them and
 * listed as retired. Nothing opens, edits, imports or runs them, and they are
 * never shown as Pine or Python. Only the user can delete them.
 */
export const RETIRED_PYNE_STRATEGY_LANGUAGE = "pyne" as const;

export function isRetiredPyneStrategyLanguage(value: unknown): boolean {
  return typeof value === "string" && value.trim().toLowerCase() === RETIRED_PYNE_STRATEGY_LANGUAGE;
}

/** What a draft list shows for a retired draft. Its source is never read out. */
export interface RetiredStrategyDraft {
  id: string;
  displayName: string;
  language: typeof RETIRED_PYNE_STRATEGY_LANGUAGE;
  updatedAt: number | null;
}

/** A retired strategy record from a chart workspace, kept exactly as stored. */
export type RetiredStrategyRecord = Readonly<Record<string, unknown>>;

/** The name a list shows for a retired record; empty when it stored none. */
export function retiredStrategyName(record: RetiredStrategyRecord): string {
  const name = typeof record.displayName === "string"
    ? record.displayName
    : typeof record.name === "string" ? record.name : "";
  return name.trim().slice(0, 120);
}

export function retiredStrategyId(record: RetiredStrategyRecord): string {
  return typeof record.id === "string" ? record.id : "";
}

export function sortRetiredDrafts(drafts: readonly RetiredStrategyDraft[]): RetiredStrategyDraft[] {
  return [...drafts].sort((left, right) => (right.updatedAt ?? 0) - (left.updatedAt ?? 0)
    || left.id.localeCompare(right.id));
}
