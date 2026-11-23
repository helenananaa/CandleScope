/**
 * Strategy drafts stored in the backend (ADR-BACKTEST-015 P3a).
 *
 * Drafts used to live in browser storage (or the desktop profile's strategy storage),
 * which a new web origin or a changed desktop UI port could not see. The backend now
 * keeps them. Existing drafts are imported once; the originals are left untouched.
 */
import { API_BASE } from "../../../services/apiConfig.js";
import {
  STRATEGY_DRAFT_SCHEMA_VERSION, STRATEGY_DRAFT_STORAGE_KEY,
  type StrategyDraftRecord, type StrategyDraftStorageLike, type StrategyDraftStoreAdapter,
} from "./StrategyDraftStore.js";

/** Set in the legacy storage once its drafts are in the backend. The drafts themselves stay. */
export const STRATEGY_DRAFT_IMPORT_MARKER = `${STRATEGY_DRAFT_STORAGE_KEY}:imported-to-backend`;
const IMPORT_BATCH = 200;
const IMPORT_BATCH_BYTES = 24 * 1024 * 1024;

interface DraftWire {
  draft_id: string;
  revision: number;
  display_name: string;
  language: "pine" | "python";
  source: string;
  cursor: { line: number; column: number } | null;
  created_at_ms: number;
  updated_at_ms: number;
}

export class StrategyDraftConflictError extends Error {
  constructor(readonly currentRevision: number | null) {
    super("The draft changed in another window");
    this.name = "StrategyDraftConflictError";
  }
}

export interface StrategyDraftClient {
  get(id: string): Promise<StrategyDraftRecord | null>;
  list(limit: number): Promise<StrategyDraftRecord[]>;
  /** Store `record` if the backend holds `expectedRevision` (null: no draft yet). */
  put(record: StrategyDraftRecord, expectedRevision: number | null): Promise<StrategyDraftRecord>;
  remove(id: string): Promise<void>;
  importDrafts(records: StrategyDraftRecord[]): Promise<{ imported: string[]; kept: string[] }>;
}

function toWire(record: StrategyDraftRecord): DraftWire {
  return { draft_id: record.id, revision: record.revision, display_name: record.displayName, language: record.language,
    source: record.source, cursor: record.cursor, created_at_ms: record.createdAt, updated_at_ms: record.updatedAt };
}

function fromWire(wire: DraftWire): StrategyDraftRecord {
  return { schemaVersion: STRATEGY_DRAFT_SCHEMA_VERSION, id: wire.draft_id, revision: wire.revision,
    displayName: wire.display_name, language: wire.language, source: wire.source, cursor: wire.cursor,
    createdAt: wire.created_at_ms, updatedAt: wire.updated_at_ms };
}

async function failure(response: Response): Promise<never> {
  const body = await response.json().catch(() => null) as { error?: { code?: string; message?: string; details?: { current_revision?: number | null } } } | null;
  if (body?.error?.code === "DRAFT_REVISION_CONFLICT") throw new StrategyDraftConflictError(body.error.details?.current_revision ?? null);
  throw new Error(body?.error?.message ?? `Strategy draft request failed (HTTP ${response.status})`);
}

export function createStrategyDraftClient(base = `${API_BASE}/strategy-drafts`): StrategyDraftClient {
  const json = { "Content-Type": "application/json" };
  return {
    async get(id) {
      const response = await fetch(`${base}/${encodeURIComponent(id)}`);
      if (response.status === 404) return null;
      if (!response.ok) return failure(response);
      return fromWire(await response.json() as DraftWire);
    },
    async list(limit) {
      const response = await fetch(`${base}?limit=${limit}`);
      if (!response.ok) return failure(response);
      return ((await response.json() as { drafts: DraftWire[] }).drafts).map(fromWire);
    },
    async put(record, expectedRevision) {
      const response = await fetch(`${base}/${encodeURIComponent(record.id)}`, {
        method: "PUT", headers: json, body: JSON.stringify({ expected_revision: expectedRevision, draft: toWire(record) }),
      });
      if (!response.ok) return failure(response);
      return fromWire(await response.json() as DraftWire);
    },
    async remove(id) {
      const response = await fetch(`${base}/${encodeURIComponent(id)}`, { method: "DELETE" });
      if (!response.ok) await failure(response);
    },
    async importDrafts(records) {
      const response = await fetch(`${base}/import`, { method: "POST", headers: json,
        body: JSON.stringify({ drafts: records.map(toWire) }) });
      if (!response.ok) return failure(response);
      return response.json() as Promise<{ imported: string[]; kept: string[] }>;
    },
  };
}

function importBatches(records: StrategyDraftRecord[]): StrategyDraftRecord[][] {
  const batches: StrategyDraftRecord[][] = [];
  let current: StrategyDraftRecord[] = [], bytes = 0;
  for (const record of records) {
    const size = record.source.length * 3 + 1024;
    if (current.length && (current.length >= IMPORT_BATCH || bytes + size > IMPORT_BATCH_BYTES)) {
      batches.push(current); current = []; bytes = 0;
    }
    current.push(record); bytes += size;
  }
  if (current.length) batches.push(current);
  return batches;
}

/**
 * The store's adapter over the backend. Until the one-time import has succeeded, drafts
 * only the legacy storage holds stay readable from it, so nothing disappears if the
 * backend is briefly unreachable; after the import the backend alone is authoritative.
 */
export function createBackendStrategyDraftAdapter(client: StrategyDraftClient, legacy?: {
  adapter: StrategyDraftStoreAdapter;
  storage: StrategyDraftStorageLike;
} | null): StrategyDraftStoreAdapter & { imported(): Promise<boolean> } {
  // The revision the backend last confirmed for each draft: the expected revision of the next save.
  const confirmed = new Map<string, number>();
  const remember = (record: StrategyDraftRecord | null) => { if (record) confirmed.set(record.id, record.revision); return record; };
  let importing: Promise<boolean> | null = null;
  const imported = (): Promise<boolean> => {
    if (!legacy) return Promise.resolve(true);
    if (legacy.storage.getItem(STRATEGY_DRAFT_IMPORT_MARKER) !== null) return Promise.resolve(true);
    importing ??= (async () => {
      try {
        const records = (await legacy.adapter.list()) as StrategyDraftRecord[];
        let count = 0;
        for (const batch of importBatches(records)) count += (await client.importDrafts(batch)).imported.length;
        await legacy.storage.setItem(STRATEGY_DRAFT_IMPORT_MARKER, JSON.stringify({ at: Date.now(), drafts: records.length, imported: count }));
        return true;
      } catch {
        importing = null;  // try again on the next use
        return false;
      }
    })();
    return importing;
  };
  const legacyRecord = async (id: string, done: boolean) => (!done && legacy ? (await legacy.adapter.load(id)) as StrategyDraftRecord | null : null);
  return {
    imported,
    async load(id) {
      const done = await imported();
      try {
        return remember(await client.get(id)) ?? await legacyRecord(id, done);
      } catch (error) {
        const fallback = await legacyRecord(id, done);
        if (fallback) return fallback;
        throw error;
      }
    },
    async list() {
      const done = await imported();
      let records: StrategyDraftRecord[] = [];
      try {
        records = (await client.list(200)).map((record) => remember(record)!);
      } catch (error) {
        if (done || !legacy) throw error;
      }
      if (done || !legacy) return records;
      const merged = new Map(((await legacy.adapter.list()) as StrategyDraftRecord[]).map((record) => [record.id, record]));
      for (const record of records) {
        const other = merged.get(record.id);
        if (!other || record.revision >= other.revision) merged.set(record.id, record);
      }
      return [...merged.values()];
    },
    async save(record) {
      await imported();
      const draft = record as StrategyDraftRecord;
      try {
        return remember(await client.put(draft, confirmed.get(draft.id) ?? null));
      } catch (error) {
        if (!(error instanceof StrategyDraftConflictError)) throw error;
        // Another window saved first. As with browser storage, the latest save wins, on top of its revision.
        const current = await client.get(draft.id);
        const next = { ...draft, revision: Math.max(draft.revision, (current?.revision ?? -1) + 1) };
        return remember(await client.put(next, current?.revision ?? null));
      }
    },
    async remove(id) {
      await imported();
      await client.remove(id);
      confirmed.delete(id);
    },
  };
}
