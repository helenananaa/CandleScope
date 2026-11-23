import type { ExtensionManifest, ExtensionSlot, RunningExtension } from "./contracts.js";

const listeners = new Set<() => void>();
export interface ExtensionState {
  revision: number;
  theme: ExtensionManifest["theme"] | null;
  layout: ExtensionManifest["layout"] | null;
  slots: ReadonlyMap<string, ExtensionSlot>;
  errors: Record<string, string>;
  reloadRequired: boolean;
  running: RunningExtension[];
  /** The registry says extensions are off for this launch (desktop recovery mode). */
  safeMode: boolean;
}
let state: ExtensionState = { revision: 0, theme: null, layout: null, slots: new Map(), errors: {}, reloadRequired: false, running: [], safeMode: false };
export const getExtensionState = (): ExtensionState => state;
export const subscribeExtensions = (listener: () => void): (() => void) => {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
};
export function publishExtensions(update: Partial<ExtensionState>): void {
  state = { ...state, ...update, revision: state.revision + 1 };
  for (const listener of listeners) listener();
}

const services = new Map<string, unknown>();
const hostEvents = new Map<string, Set<(payload: unknown) => void>>();
export function subscribeHostEvent(name: string, listener: (payload: unknown) => void): () => void {
  const listeners = hostEvents.get(name) ?? new Set();
  hostEvents.set(name, listeners);
  listeners.add(listener);
  return () => { listeners.delete(listener); if (!listeners.size) hostEvents.delete(name); };
}
export function emitHostEvent(name: string, payload: unknown): void {
  for (const listener of hostEvents.get(name) ?? []) listener(payload);
}
export function getHostService<T = unknown>(name: string): T {
  if (!services.has(name)) throw new Error(`Host service is not mounted: ${name}`);
  return services.get(name) as T;
}
export function bindHostService(name: string, value: unknown): () => void {
  services.set(name, value);
  emitHostEvent(`${name}.changed`, value);
  return () => { if (services.get(name) === value) services.delete(name); };
}

export function extensionSafeMode(): boolean {
  return typeof location !== "undefined" && new URLSearchParams(location.search).get("extensions") === "off";
}

/**
 * Colour names of the candlescope.theme/1 contract (backend plugin_lifecycle/appearance.py) that the
 * stylesheets know by their design-token names. A theme keeps its names; each value is written as the
 * token it stands for, so it colours every surface and border.
 */
export const THEME_CONTRACT_TOKENS: Readonly<Record<string, string>> = {
  "bg-primary": "surface-0",
  "bg-secondary": "surface-1",
  "bg-tertiary": "surface-2",
  "bg-hover": "surface-hover",
  "border-color": "border-subtle",
};

export function extensionThemeDeclarations(tokens: Readonly<Record<string, string>>): string {
  return Object.entries(tokens)
    .map(([name, value]) => `--${THEME_CONTRACT_TOKENS[name] ?? name}:${value} !important;`)
    .join("");
}

export function applyExtensionTheme(theme: ExtensionState["theme"]): void {
  if (typeof document === "undefined") return;
  document.getElementById("candlescope-extension-theme")?.remove();
  if (!theme) { delete document.documentElement.dataset.extensionTheme; return; }
  document.documentElement.dataset.extensionTheme = theme.base;
  const style = document.createElement("style");
  style.id = "candlescope-extension-theme";
  // The features layer keeps theme rules competing with feature CSS by specificity, as before layers.
  style.textContent = `@layer features {
    :root{${extensionThemeDeclarations(theme.tokens)}}
    :root[data-extension-theme] .app-layout button { border-radius:var(--radius-sm); }
    :root[data-extension-theme] :is(.plugin-center, .extension-manager) :is(button, select) { min-height:var(--control-height, 32px); }
    :root[data-extension-theme] :is(.pc-engines article, .extension-item, .extension-review) { border-radius:var(--radius-md); box-shadow:var(--panel-shadow, none); }
    :root[data-extension-theme] .extension-actions { gap:var(--panel-gap, 8px); }
  }`;
  document.head.append(style);
}
