import { useCallback, useEffect, useRef, useState } from "react";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import { AccountApiError, getJournal, saveJournal, type JournalVersion } from "./accountApi.js";
import { JOURNAL_DRAFT_KEY as DRAFT_KEY, draftFromVersion, draftTags, draftSignature as signature, newJournalDraft as newDraft,
  parseJournalDraft, reconcileJournalDraft, type JournalDraft as Draft } from "./journalDraft.js";

function readDraft(): Draft {
  try {
    return parseJournalDraft(localStorage.getItem(DRAFT_KEY));
  } catch { /* The server journal remains authoritative. */ }
  return newDraft();
}
function localDateTime(ms: number): string {
  const date = new Date(ms);
  return new Date(ms - date.getTimezoneOffset() * 60_000).toISOString().slice(0, 16);
}

export default function AccountJournal({ fillId }: { fillId?: string }) {
  const locale = useLocale();
  const [draft, setDraft] = useState(readDraft);
  const [versions, setVersions] = useState<JournalVersion[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [storageError, setStorageError] = useState(false);
  const savingRef = useRef(false);
  const saved = signature(draft) === draft.savedSignature;
  const date = (ms: number) => new Date(ms).toLocaleString(locale);

  useEffect(() => {
    const controller = new AbortController();
    void getJournal(controller.signal).then((rows) => {
      if (controller.signal.aborted) return;
      setVersions(rows); setDraft((current) => reconcileJournalDraft(current, rows)); setLoaded(true);
    })
      .catch((failure: unknown) => { if (!controller.signal.aborted) setError(failure instanceof AccountApiError ? failure.code : "ACCOUNT_SYNC_FAILED"); });
    return () => controller.abort();
  }, []);
  useEffect(() => {
    if (fillId) setDraft((current) => ({ ...current, fillId }));
  }, [fillId]);
  useEffect(() => {
    try { localStorage.setItem(DRAFT_KEY, JSON.stringify(draft)); setStorageError(false); }
    catch { setStorageError(true); }
  }, [draft]);

  const save = useCallback(async () => {
    if (!loaded || savingRef.current || !draft.text.trim() || signature(draft) === draft.savedSignature) return;
    savingRef.current = true;
    setSaving(true);
    const pending = { baseVersion: draft.baseVersion, signature: signature(draft) };
    // Persist before the request so a response lost during exit is recoverable.
    try { localStorage.setItem(DRAFT_KEY, JSON.stringify({ ...draft, pending })); }
    catch { setStorageError(true); }
    setDraft((current) => ({ ...current, pending }));
    try {
      const result = await saveJournal({ noteId: draft.noteId, baseVersion: draft.baseVersion, text: draft.text,
        tags: draftTags(draft.tags), kind: draft.kind,
        eventMs: draft.eventMs, ...(draft.fillId ? { fillId: draft.fillId } : {}) });
      setVersions((current) => [result, ...current.filter((row) => row.noteId !== result.noteId || row.version !== result.version)]);
      setDraft((current) => current.noteId === draft.noteId
        ? reconcileJournalDraft(current, [result]) : current);
      setError(null);
    } catch (failure) {
      setError(failure instanceof AccountApiError ? failure.code : "ACCOUNT_SYNC_FAILED");
    } finally {
      savingRef.current = false;
      setSaving(false);
    }
  }, [draft, loaded]);
  useEffect(() => {
    if (!loaded || saving || saved || error || !draft.text.trim()) return;
    const timer = setTimeout(() => { void save(); }, 1000);
    return () => clearTimeout(timer);
  }, [draft.text, error, loaded, save, saved, saving]);

  const latest = versions.filter((row) => !versions.some((other) => other.noteId === row.noteId && other.version > row.version));
  const load = (row: JournalVersion) => {
    setDraft(draftFromVersion(row)); setError(null);
  };
  const reload = async () => {
    try {
      const rows = await getJournal(); setVersions(rows); setLoaded(true);
      const row = rows.filter((item) => item.noteId === draft.noteId).sort((a, b) => b.version - a.version)[0];
      if (row) load(row); else setError(null);
    } catch (failure) { setError(failure instanceof AccountApiError ? failure.code : "ACCOUNT_SYNC_FAILED"); }
  };

  return <section className="readonly-account-journal">
    <p className="readonly-account-help">{t("account.noteHelp", {}, locale)}</p>
    <button type="button" disabled={saving || Boolean(draft.text.trim() && !saved)} onClick={() => { setDraft(newDraft()); setError(null); }}>{t("account.newNote", {}, locale)}</button>
    <label>{t("account.journal", {}, locale)}<select value={draft.kind} onChange={(event) => setDraft({ ...draft, kind: event.target.value as Draft["kind"] })}>
      {(["plan", "note", "review"] as const).map((kind) => <option key={kind} value={kind}>{t(`account.${kind}`, {}, locale)}</option>)}
    </select></label>
    <label>{t("account.eventTime", {}, locale)}<input type="datetime-local" value={localDateTime(draft.eventMs)} onChange={(event) => {
      const value = new Date(event.target.value).getTime(); if (Number.isFinite(value)) setDraft({ ...draft, eventMs: value });
    }} /></label>
    {draft.fillId && <p className="readonly-account-help">{t("account.linkedFill", { id: draft.fillId }, locale)}</p>}
    <label>{t("account.noteText", {}, locale)}<textarea value={draft.text} maxLength={8000} rows={6} onChange={(event) => setDraft({ ...draft, text: event.target.value })} /></label>
    <label>{t("account.tags", {}, locale)}<input value={draft.tags} maxLength={800} onChange={(event) => setDraft({ ...draft, tags: event.target.value })} /></label>
    <div className="readonly-account-actions"><button type="button" disabled={saving || saved || !loaded || !draft.text.trim()} onClick={() => { void save(); }}>{t(saving ? "account.working" : "account.save", {}, locale)}</button>
      <span role="status">{t(saved ? "account.saved" : "account.unsaved", {}, locale)}</span></div>
    {storageError && <p role="alert">{t("account.draftStorageError", {}, locale)}</p>}
    {error && <div role="alert"><p>{t(error === "JOURNAL_VERSION_CONFLICT" ? "account.saveConflict" : "account.errorHelp", {}, locale)}</p><code>{error}</code><button type="button" onClick={() => { void reload(); }}>{t("account.restoreDraft", {}, locale)}</button></div>}
    {latest.map((row) => <details key={row.noteId} className="readonly-account-card">
      <summary>{t(`account.${row.payload.kind}`, {}, locale)} · {date(row.eventMs)} · {row.payload.text.slice(0, 48)}</summary>
      <button type="button" disabled={saving || Boolean(draft.text.trim() && !saved)} onClick={() => load(row)}>{t("account.restoreDraft", {}, locale)}</button>
      {versions.filter((item) => item.noteId === row.noteId).sort((a, b) => b.version - a.version).map((item) => <article key={item.version}>
        <strong>{t("account.version", { version: item.version }, locale)}</strong>
        <p className="readonly-account-help">{t("account.recordedTime", { time: date(item.recordedMs) }, locale)}</p>
        <p className="readonly-account-note-text">{item.payload.text}</p>
      </article>)}
    </details>)}
  </section>;
}
