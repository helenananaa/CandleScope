export interface UnifiedIdentity { pluginId: string; version: string; packageSha256: string; generation: number }
export interface UnifiedManifest {
  schema: "candlescope.unified-plugin/1"; id: string; name: string; version: string;
  trust: "restricted" | "full-trust"; hostApiVersion: 1;
  entries: {id: string; kind: string; path: string; runtime?: string; startup?: string[]}[];
  dependencies?: Record<string, string>; permissions?: string[];
}
export interface UnifiedItem {
  pluginId: string; entry: UnifiedManifest["entries"][number]; identity: UnifiedIdentity;
  instanceId: string; manifest: UnifiedManifest; assetBase: string;
  state: string; root?: string; files?: Record<string,string>;
}
export interface UnifiedPlan { sessionId: string; hostInstance: string; safeMode?: boolean; entries: UnifiedItem[]; errors?: Record<string,string> }
export interface UnifiedOwned { context: {track(cleanup: () => void | Promise<void>): void}; dispose(): unknown }
export class UnifiedEntryLifecycle {
  constructor(options: {
    load(item: UnifiedItem): unknown;
    createContext(item: UnifiedItem, guard: () => void): UnifiedOwned;
    report(plan: UnifiedPlan, item: UnifiedItem, state: string, error?: string): Promise<unknown>;
    timeoutMs?: number; changed?(): void;
  });
  restartRequired: boolean;
  errors: Record<string,string>;
  reconcile(plan: UnifiedPlan): Promise<void>;
  current(item: UnifiedItem): boolean;
  diagnostics(): {restartRequired: boolean; errors: Record<string,string>; active: {pluginId:string; entryId:string; identity:UnifiedIdentity; instanceId:string}[]};
  stop(): Promise<void>;
}
