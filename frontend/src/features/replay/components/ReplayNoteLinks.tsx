import { useEffect, useState } from "react";
import { t } from "../../../i18n/index.js";
import { replayNoteLinkField, replayNoteSelectedLinks, sameReplayNoteContext,
  type ReplayNoteContext, type ReplayNoteLink } from "../replayNotes.js";
import type { ReplayV2ApiClient } from "../replayV2Api.js";

const label = (link: ReplayNoteLink) => `${t(link.kind === "FILL" ? "replay.notes.fillLink" : "replay.notes.tradeLink")} ${link.id} · ${t(link.side === "BUY" ? "replay.shell.buy" : "replay.shell.sell")} ${link.quantity} @ ${link.price}`;

export function ReplayNoteLinks({ links, formatTime }: { links: readonly ReplayNoteLink[]; formatTime(ms: number): string }) {
  return links.length > 0 ? <ul className="replay-note-links" data-testid="replay-note-links">
    {links.map(link => <li key={link.kind + ":" + link.id}>{label(link)} · {formatTime(link.eventTimeMs)}</li>)}
  </ul> : null;
}

function LinkOptions({ api, context, kind, selected, full, disabled, onToggle }: {
  api: Pick<ReplayV2ApiClient, "noteLinkOptionsRun">; context: ReplayNoteContext; kind: ReplayNoteLink["kind"];
  selected: readonly string[]; full: boolean; disabled: boolean; onToggle(id: string): void;
}) {
  const [before, setBefore] = useState<string | undefined>(undefined);
  const [attempt, setAttempt] = useState(0);
  const [page, setPage] = useState<{ links: ReplayNoteLink[]; next: string | null; request: string | null; error: boolean }>(
    { links: [], next: null, request: null, error: false });
  const request = JSON.stringify([before, attempt]), loading = page.request !== request;
  useEffect(() => {
    const controller = new AbortController();
    api.noteLinkOptionsRun(context.runId, context.trackId, { kind, ...(before ? { beforeId: before } : {}) }, controller.signal).then(result => {
      if (controller.signal.aborted) return;
      if (!sameReplayNoteContext(result.context, context)) throw new TypeError("Replay note reference context changed");
      setPage({ links: result.links, next: result.nextBeforeId, request, error: false });
    }).catch(() => { if (!controller.signal.aborted) setPage(previous => ({ ...previous, request, error: true })); });
    return () => controller.abort();
  }, [api, context, kind, before, request]);
  return <div className="replay-note-link-options" data-testid="replay-note-link-options">
    {page.links.map(link => <label key={link.id}><input type="checkbox" checked={selected.includes(link.id)}
      disabled={disabled || (full && !selected.includes(link.id))} onChange={() => onToggle(link.id)} />{label(link)}</label>)}
    {loading && <p role="status">{t("replay.notes.linksLoading")}</p>}
    {!loading && page.error && <><p role="alert">{t("replay.notes.linksFailed")}</p>
      <button type="button" onClick={() => setAttempt(value => value + 1)}>{t("replay.notes.refresh")}</button></>}
    {!loading && !page.error && page.links.length === 0 && <p>{t("replay.notes.linksEmpty")}</p>}
    {!loading && !page.error && page.next && <button type="button" onClick={() => setBefore(page.next!)}>{t("replay.notes.moreLinks")}</button>}
  </div>;
}

export function ReplayNoteLinkPicker({ api, context, fields, disabled, onChange }: {
  api: Pick<ReplayV2ApiClient, "noteLinkOptionsRun">; context: ReplayNoteContext; fields: Record<string, string>;
  disabled: boolean; onChange(fields: Record<string, string>): void;
}) {
  const [kind, setKind] = useState<ReplayNoteLink["kind"] | null>(null);
  let fills: string[] = [], trades: string[] = [], valid = true;
  try { fills = replayNoteSelectedLinks(fields, "FILL"); trades = replayNoteSelectedLinks(fields, "TRADE"); }
  catch { valid = false; }
  const toggle = (selectionKind: ReplayNoteLink["kind"], id: string) => {
    if (!valid || disabled) return;
    const selected = selectionKind === "FILL" ? fills : trades;
    const next = selected.includes(id) ? selected.filter(value => value !== id) : [...selected, id];
    if (next.length + (selectionKind === "FILL" ? trades.length : fills.length) > 8) return;
    onChange({ ...fields, [replayNoteLinkField(selectionKind)]: JSON.stringify(next) });
  };
  return <div className="replay-note-link-picker">
    <p>{t("replay.notes.linksHint")}</p>
    {!valid && <p role="alert">{t("replay.notes.linksFailed")}</p>}
    <div className="replay-note-actions">
      {(["FILL", "TRADE"] as const).map(value => <button type="button" key={value} disabled={disabled || !valid}
        aria-expanded={kind === value} onClick={() => setKind(current => current === value ? null : value)}>
        {t(value === "FILL" ? "replay.notes.chooseFills" : "replay.notes.chooseTrades")}</button>)}
    </div>
    {([...fills.map(id => ({ kind: "FILL" as const, id })), ...trades.map(id => ({ kind: "TRADE" as const, id }))]).map(link =>
      <button type="button" key={link.kind + ":" + link.id} disabled={disabled || !valid} onClick={() => toggle(link.kind, link.id)}>
        {t("replay.notes.removeLink", { id: link.id })}</button>)}
    {kind && valid && <LinkOptions key={kind} api={api} context={context} kind={kind}
      selected={kind === "FILL" ? fills : trades} full={fills.length + trades.length >= 8} disabled={disabled}
      onToggle={id => toggle(kind, id)} />}
  </div>;
}
