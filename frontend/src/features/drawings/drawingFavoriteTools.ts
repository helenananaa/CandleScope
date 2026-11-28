import { useSyncExternalStore } from "react";
import type { DrawingToolId } from "./drawingTypes.js";

/**
 * Favorite drawing tools (PL-4): up to nine tools the user starred in the
 * toolbar menus, in the order they were added. They show as their own
 * toolbar buttons and Alt+1…Alt+9 picks them. Stored per browser profile.
 */
export const FAVORITE_TOOLS_KEY = "candlescope.drawing.favoriteTools.v1";
export const MAX_FAVORITE_TOOLS = 9;
const FAVORITE_TOOLS_EVENT = "candlescope:drawing-favorite-tools";

interface FavoriteStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
}

const EMPTY: readonly DrawingToolId[] = Object.freeze([]);
let cachedRaw: string | null | undefined;
let cachedTools: readonly DrawingToolId[] = EMPTY;

function defaultStorage(): FavoriteStorage | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

/** Parse a stored list, keeping only known tools once each. Anything malformed reads as no favorites. */
export function parseFavoriteTools(raw: string | null, known: (id: string) => boolean): readonly DrawingToolId[] {
  if (raw === null || raw.length > 4096) return EMPTY;
  let parsed: unknown;
  try { parsed = JSON.parse(raw); } catch { return EMPTY; }
  if (typeof parsed !== "object" || parsed === null || (parsed as { version?: unknown }).version !== 1) return EMPTY;
  const tools = (parsed as { tools?: unknown }).tools;
  if (!Array.isArray(tools as unknown)) return EMPTY;
  const result: DrawingToolId[] = [];
  for (const id of tools as unknown[]) {
    if (typeof id !== "string" || !known(id) || result.includes(id as DrawingToolId)) continue;
    result.push(id as DrawingToolId);
    if (result.length === MAX_FAVORITE_TOOLS) break;
  }
  return Object.freeze(result);
}

export function readFavoriteTools(known: (id: string) => boolean, storage: FavoriteStorage | null = defaultStorage()): readonly DrawingToolId[] {
  if (!storage) return EMPTY;
  let raw: string | null;
  try { raw = storage.getItem(FAVORITE_TOOLS_KEY); } catch { return EMPTY; }
  if (storage === defaultStorage() && raw === cachedRaw) return cachedTools;
  const tools = parseFavoriteTools(raw, known);
  if (storage === defaultStorage()) {
    cachedRaw = raw;
    cachedTools = tools;
  }
  return tools;
}

/** Star or unstar one tool. Returns the new list, or null when it could not be saved or the list is full. */
export function toggleFavoriteTool(
  id: DrawingToolId,
  known: (id: string) => boolean,
  storage: FavoriteStorage | null = defaultStorage(),
): readonly DrawingToolId[] | null {
  if (!storage || !known(id)) return null;
  const current = readFavoriteTools(known, storage);
  const next = current.includes(id) ? current.filter((tool) => tool !== id) : [...current, id];
  if (next.length > MAX_FAVORITE_TOOLS) return null;
  try {
    storage.setItem(FAVORITE_TOOLS_KEY, JSON.stringify({ version: 1, tools: next }));
  } catch {
    return null;
  }
  if (storage === defaultStorage() && typeof window !== "undefined") window.dispatchEvent(new Event(FAVORITE_TOOLS_EVENT));
  return Object.freeze(next);
}

function subscribe(listener: () => void): () => void {
  if (typeof window === "undefined") return () => {};
  const onStorage = (event: StorageEvent) => { if (event.key === null || event.key === FAVORITE_TOOLS_KEY) listener(); };
  window.addEventListener(FAVORITE_TOOLS_EVENT, listener);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener(FAVORITE_TOOLS_EVENT, listener);
    window.removeEventListener("storage", onStorage);
  };
}

/** The favorites, kept in step across toolbars and windows. */
export function useFavoriteTools(known: (id: string) => boolean): readonly DrawingToolId[] {
  const read = () => readFavoriteTools(known);
  return useSyncExternalStore(subscribe, read, read);
}

/** Alt+1…Alt+9 by physical key, so it works on keyboard layouts where Alt changes the character. */
export function favoriteShortcutIndex(event: Pick<KeyboardEvent, "altKey" | "ctrlKey" | "metaKey" | "shiftKey" | "code">): number | null {
  if (!event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return null;
  const match = /^(?:Digit|Numpad)([1-9])$/.exec(event.code);
  return match ? Number(match[1]) - 1 : null;
}
