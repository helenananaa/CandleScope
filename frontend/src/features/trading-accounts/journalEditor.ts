import type { JournalEntry } from "./tradingTypes.js";

type Fields = Record<string, string>;
type StoragePort = Pick<Storage, "getItem" | "setItem" | "removeItem">;
interface JournalSubmission {
  entryId: string | null;
  clientEntryId: string;
  expectedRevision: number | null;
  fields: Fields;
}
export interface JournalDraft {
  version: 1;
  stamp: string;
  entryId: string | null;
  clientEntryId: string;
  expectedRevision: number | null;
  fields: Fields;
  quickText: string;
  quickClientId: string;
  quickPending?: { text: string; clientEntryId: string };
  pendingSave?: JournalSubmission;
}
export interface JournalEditorState {
  ready: boolean;
  fields: Fields;
  quickText: string;
  note: JournalEntry | null;
  status: "idle" | "saving" | "saved" | "failed";
  recovered: boolean;
  error: unknown;
}
export class JournalDraftError extends Error {
  constructor(public readonly reason: "storage" | "changed") { super(reason); }
}
const equal = (a: Fields, b: Fields) => {
  const keys = (fields: Fields) => Object.keys(fields).filter((key) => fields[key]?.trim());
  return keys(a).length === keys(b).length && keys(a).every((key) => a[key] === b[key]);
};
export const journalClientId = () => `je_${crypto.randomUUID().replaceAll("-", "").slice(0, 20)}`;

/** One mounted editor owns its save queue. Drafts are synchronous and profile-local. */
export class JournalEditor {
  private state: JournalEditorState = {
    ready: false, fields: {}, quickText: "", note: null, status: "idle", recovered: false, error: null,
  };
  private listeners = new Set<() => void>();
  private draft: JournalDraft | null = null;
  private savedFields: Fields = {};
  private dirty = false;
  private saving: Promise<boolean> | null = null;
  private quickSaving: Promise<boolean> | null = null;
  private disposed = false;
  constructor(private options: {
    key: string;
    storage: () => StoragePort;
    create: (fields: Fields, clientEntryId: string) => Promise<JournalEntry>;
    save: (id: string, fields: Fields, expectedRevision: number) => Promise<JournalEntry>;
    quick: (body: string, clientEntryId: string) => Promise<unknown>;
    newId?: () => string;
  }) {}
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
  getSnapshot = () => this.state;
  private publish(update: Partial<JournalEditorState>) {
    this.state = { ...this.state, ...update };
    this.listeners.forEach((listener) => listener());
  }
  private newId() { return (this.options.newId ?? journalClientId)(); }
  initialize(note: JournalEntry | null, defaults: Fields = {}) {
    if (this.state.ready) return;
    let recovered: JournalDraft | null = null;
    try {
      const raw = this.options.storage().getItem(this.options.key);
      if (raw) {
        const value = JSON.parse(raw) as JournalDraft;
        if (value.version !== 1 || !value.fields || typeof value.fields !== "object"
            || Array.isArray(value.fields) || Object.values(value.fields).some((v) => typeof v !== "string")
            || typeof value.quickText !== "string" || typeof value.clientEntryId !== "string"
            || typeof value.quickClientId !== "string" || typeof value.stamp !== "string"
            || !(value.entryId === null || typeof value.entryId === "string")
            || !(value.expectedRevision === null || Number.isInteger(value.expectedRevision))) {
          throw new Error("Invalid draft");
        }
        recovered = value;
      }
    } catch {
      this.publish({ error: new JournalDraftError("storage"), status: "failed" });
      return; // Never replace unreadable recovery data with an empty draft.
    }
    this.savedFields = note?.fields ?? {};
    this.draft = recovered ?? {
      version: 1, stamp: "", entryId: note?.id ?? null, clientEntryId: this.newId(),
      expectedRevision: note?.revisionCount ?? null, fields: note?.fields ?? defaults,
      quickText: "", quickClientId: this.newId(),
    };
    this.dirty = Boolean(this.draft.pendingSave) || !equal(this.draft.fields, this.savedFields);
    if (recovered && note && recovered.entryId !== null && recovered.entryId !== note.id) {
      this.publish({ error: new JournalDraftError("changed"), status: "failed" });
      return;
    }
    if (note && !this.dirty) {
      this.draft.entryId = note.id;
      this.draft.expectedRevision = note.revisionCount;
    }
    this.publish({ ready: true, fields: this.draft.fields, quickText: this.draft.quickText,
      note, recovered: recovered !== null });
  }
  /** Do not let a late response from a closed editor erase a reopened draft. */
  private persist(): boolean {
    if (!this.draft || this.disposed) return false;
    try {
      const storage = this.options.storage();
      const raw = storage.getItem(this.options.key);
      if (raw && (JSON.parse(raw) as JournalDraft).stamp !== this.draft.stamp) throw new JournalDraftError("changed");
      if (!this.dirty && !this.draft.quickText && !this.draft.quickPending) {
        storage.removeItem(this.options.key);
        return true;
      }
      const next = { ...this.draft, stamp: this.newId() };
      storage.setItem(this.options.key, JSON.stringify(next));
      this.draft = next;
      return true;
    } catch (error) {
      this.publish({ status: "failed", error: error instanceof JournalDraftError ? error : new JournalDraftError("storage") });
      return false;
    }
  }
  edit(fields: Fields) {
    if (!this.draft || !this.state.ready) return;
    this.draft = { ...this.draft, fields: { ...fields } };
    this.dirty = Boolean(this.draft.pendingSave) || !equal(fields, this.savedFields);
    this.publish({ fields: this.draft.fields, status: "idle", error: null });
    this.persist();
  }
  editQuick(quickText: string) {
    if (!this.draft || !this.state.ready) return;
    this.draft = { ...this.draft, quickText };
    this.publish({ quickText });
    this.persist();
  }
  flush = (): Promise<boolean> => {
    if (this.saving) return this.saving;
    if (!this.state.ready || this.disposed || !this.draft) return Promise.resolve(false);
    this.saving = this.saveLoop().finally(() => { this.saving = null; });
    return this.saving;
  };
  private async saveLoop(): Promise<boolean> {
    if (!this.persist()) return false;
    try {
      while (this.dirty && this.draft && !this.disposed) {
        // Retry an uncertain write first, even when the user has since reverted
        // to the old text. Otherwise a delayed old request could win after close.
        const current = this.draft.pendingSave ?? {
          entryId: this.draft.entryId, clientEntryId: this.draft.clientEntryId,
          expectedRevision: this.draft.expectedRevision, fields: this.draft.fields,
        };
        this.draft = { ...this.draft, pendingSave: current };
        if (!this.persist()) return false;
        this.publish({ status: "saving", error: null });
        const saved = current.entryId
          ? await this.options.save(current.entryId, current.fields, current.expectedRevision!)
          : await this.options.create(current.fields, current.clientEntryId);
        if (this.disposed) return false;
        this.savedFields = saved.fields;
        this.draft = { ...this.draft, entryId: saved.id, expectedRevision: saved.revisionCount };
        delete this.draft.pendingSave;
        this.dirty = !equal(this.draft.fields, this.savedFields);
        this.publish({ note: saved });
        if (!this.persist()) return false;
      }
      this.publish({ status: "saved", error: null });
      return !this.disposed;
    } catch (error) {
      this.publish({ status: "failed", error });
      return false;
    }
  }
  saveQuick = (): Promise<boolean> => {
    if (this.quickSaving) return this.quickSaving;
    if (!this.draft || (!this.draft.quickText.trim() && !this.draft.quickPending)) return Promise.resolve(false);
    const pending = this.draft.quickPending ?? { text: this.draft.quickText, clientEntryId: this.draft.quickClientId };
    this.draft = { ...this.draft, quickPending: pending };
    if (!this.persist()) return Promise.resolve(false);
    this.quickSaving = this.options.quick(pending.text.trim(), pending.clientEntryId).then(() => {
      if (this.disposed || !this.draft) return false;
      const quickText = this.draft.quickText === pending.text ? "" : this.draft.quickText;
      this.draft = { ...this.draft, quickText, quickClientId: this.newId() };
      delete this.draft.quickPending;
      this.publish({ quickText, error: null });
      return this.persist();
    }).catch((error: unknown) => { this.publish({ error, status: "failed" }); return false; })
      .finally(() => { this.quickSaving = null; });
    return this.quickSaving;
  };
  adopt(note: JournalEntry) {
    if (!this.draft || this.dirty) return;
    this.savedFields = note.fields;
    this.draft = { ...this.draft, entryId: note.id, expectedRevision: note.revisionCount, fields: note.fields };
    this.publish({ note, fields: note.fields });
    this.persist();
  }
  activate() { this.disposed = false; }
  dispose() { this.disposed = true; }
}
