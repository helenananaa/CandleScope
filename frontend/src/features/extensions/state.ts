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
}
let state: ExtensionState = { revision: 0, theme: null, layout: null, slots: new Map(), errors: {}, reloadRequired: false, running: [] };
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

export function applyExtensionTheme(theme: ExtensionState["theme"]): void {
  if (typeof document === "undefined") return;
  document.getElementById("candlescope-extension-theme")?.remove();
  if (!theme) { delete document.documentElement.dataset.extensionTheme; return; }
  document.documentElement.dataset.extensionTheme = theme.base;
  const style = document.createElement("style");
  style.id = "candlescope-extension-theme";
  style.textContent = `:root{${Object.entries(theme.tokens).map(([name, value]) => `--${name}:${value} !important;`).join("")}}
    :root[data-extension-theme] .app-layout button { border-radius:var(--radius-sm); }
    :root[data-extension-theme] :is(.plugin-center, .extension-manager) :is(button, select) { min-height:var(--control-height, 32px); }
    :root[data-extension-theme] :is(.pc-engines article, .extension-item, .extension-review) { border-radius:var(--radius-md); box-shadow:var(--panel-shadow, none); }
    :root[data-extension-theme] .extension-actions { gap:var(--panel-gap, 8px); }
  `;
  document.head.append(style);
}
