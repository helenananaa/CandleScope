import type * as React from "react";

export interface ExtensionManifest {
  schema: "candlescope.extension/1";
  id: string;
  name: string;
  version: string;
  apiVersion: 1;
  trust: "theme" | "full-trust";
  description?: string;
  internalApiVersion?: 1;
  entries?: { frontend?: string; backend?: string; desktop?: string };
  dependencies?: Record<string, string>;
  theme?: { base: "dark" | "light"; tokens: Record<string, string> };
  layout?: { page: string[]; workspace: string[] };
}

export interface ExtensionRecord {
  manifest: ExtensionManifest;
  digest: string;
  generation: number;
  enabled: boolean;
  history: string[];
  error: string | null;
  assetBase?: string;
}

export interface RunningExtension { id: string; version: string; digest: string; generation: number }
export interface ExtensionDiagnostics { safeMode: boolean; active: RunningExtension[]; errors: Record<string, string> }

export interface ExtensionCatalog {
  revision: number;
  plugins: ExtensionRecord[];
  theme: string | null;
  layout: string | null;
  safeMode: boolean;
  active?: ExtensionRecord[];
  backendErrors?: Record<string, string>;
  backendLoaded?: string[];
  backendActive?: RunningExtension[];
}

export type ExtensionSlot = React.ComponentType<{ fallback: React.ReactNode; slots?: Record<string, React.ReactNode> }>;
export type Dispose = () => void | Promise<void>;

/** Window-scoped API. Application background work belongs in a backend entry. */
export interface ExtensionContext {
  apiVersion: 1;
  id: string;
  React: typeof React;
  assetUrl(path: string): string;
  track(dispose: Dispose): void;
  ui: {
    replaceSlot(name: string, component: ExtensionSlot): void;
    stylesheet(css: string): void;
  };
  commands: { register(name: string, handler: (payload?: unknown) => unknown): void; execute(name: string, payload?: unknown): unknown };
  events: { on(name: string, listener: (payload: unknown) => void): void; emit(name: string, payload: unknown): void };
  services: { get<T = unknown>(name: string): T; register(name: string, value: unknown): void };
  internal?: { apiVersion: 1; get<T = unknown>(name: string): T };
}

export interface ExtensionModule {
  activate(context: ExtensionContext): void | Dispose | Promise<void | Dispose>;
  deactivate?: Dispose;
}
