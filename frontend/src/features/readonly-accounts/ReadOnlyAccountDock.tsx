import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { t, type MessageKey } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import AccountJournal from "./AccountJournal.js";
import { accountErrorHelp } from "./accountErrors.js";
import type { LinkedNoteRequest } from "./journalDraft.js";
import { AccountApiError, accountSession, connectAccount, disconnectAccount, getAccountFacts,
  getAccountStatus, record, resyncAccount, type AccountStatus, type Fact, type FactKind, type FactPage } from "./accountApi.js";
import "./readonlyAccount.css";

type Tab = "overview" | FactKind | "journal";
const TABS: Tab[] = ["overview", "fills", "orders", "bills", "journal"];
function scalar(value: unknown): string { return typeof value === "string" || typeof value === "number" ? String(value) : "—"; }
function unit(value: unknown): string { return typeof value === "string" ? value : ""; }
function rows(value: unknown): Fact[] { return Array.isArray(value) ? value.filter(record) : []; }

export default function ReadOnlyAccountDock({ height, onRequestClose }: { height: number; onRequestClose: () => void }) {
  const locale = useLocale();
  const [status, setStatus] = useState<AccountStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [readError, setReadError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [tab, setTab] = useState<Tab>("overview");
  const [credentialsOpen, setCredentialsOpen] = useState(false);
  const [page, setPage] = useState<FactPage>({ items: [], next: null });
  const [loadingFacts, setLoadingFacts] = useState(false);
  const [newNoteRequest, setNewNoteRequest] = useState<LinkedNoteRequest | undefined>();
  const noteRequestHandled = useCallback(() => setNewNoteRequest(undefined), []);
  const factRequest = useRef(0);
  const available = accountSession() !== null;
  const date = (ms: number | null | undefined) => typeof ms === "number" && Number.isFinite(ms) ? new Date(ms).toLocaleString(locale) : t("account.unknown", {}, locale);
  const refresh = useCallback(async () => { setStatus(await getAccountStatus()); }, []);

  useEffect(() => {
    if (!available) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    const read = async () => {
      try { const value = await getAccountStatus(controller.signal); if (!controller.signal.aborted) { setStatus(value); setReadError(null); } }
      catch (failure) { if (!controller.signal.aborted) setReadError(failure instanceof AccountApiError ? failure.code : "ACCOUNT_UNAVAILABLE"); }
      finally { if (!controller.signal.aborted) timer = setTimeout(() => { void read(); }, 5000); }
    };
    void read();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [available]);
  useEffect(() => {
    factRequest.current += 1;
    if (tab === "overview" || tab === "journal" || !available) return;
    const controller = new AbortController();
    setPage({ items: [], next: null }); setLoadingFacts(true);
    void getAccountFacts(tab, null, controller.signal).then((value) => { if (!controller.signal.aborted) setPage(value); })
      .catch((failure: unknown) => { if (!controller.signal.aborted) setError(failure instanceof AccountApiError ? failure.code : "ACCOUNT_UNAVAILABLE"); })
      .finally(() => { if (!controller.signal.aborted) setLoadingFacts(false); });
    return () => controller.abort();
  }, [available, tab]);

  const action = async (operation: () => Promise<void>) => {
    if (busy) return;
    setBusy(true); setError(null);
    try { await operation(); await refresh(); }
    catch (failure) { setError(failure instanceof AccountApiError ? failure.code : "ACCOUNT_UNAVAILABLE"); }
    finally { setBusy(false); }
  };
  const connect = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const credentials = { apiKey: String(data.get("apiKey") ?? ""), secret: String(data.get("secret") ?? ""), password: String(data.get("password") ?? "") };
    form.reset();
    void action(async () => {
      try { await connectAccount(credentials); setCredentialsOpen(false); }
      finally { credentials.apiKey = credentials.secret = credentials.password = ""; }
    });
  };
  const loadFacts = async (more: boolean) => {
    if (tab === "overview" || tab === "journal" || loadingFacts) return;
    setLoadingFacts(true);
    const requestId = ++factRequest.current;
    try {
      const value = await getAccountFacts(tab, more ? page.next : null);
      if (requestId === factRequest.current) setPage({ items: more ? [...page.items, ...value.items] : value.items, next: value.next });
    } catch (failure) { if (requestId === factRequest.current) setError(failure instanceof AccountApiError ? failure.code : "ACCOUNT_UNAVAILABLE"); }
    finally { if (requestId === factRequest.current) setLoadingFacts(false); }
  };
  const positionsSnapshot = status?.snapshots.positions;
  const positionData = record(positionsSnapshot?.data) ? rows(positionsSnapshot.data.positions) : [];
  const openOrders = rows(status?.snapshots.open_orders?.data).map((item) => record(item.order) ? item.order : {});
  const balances = rows(status?.snapshots.balances?.data).flatMap((item) => rows(item.details));
  const stateKey: MessageKey = !status?.account ? "account.unconnected"
    : status.account.status === "synced" ? "account.synced"
      : status.account.status === "syncing" ? "account.syncing"
        : status.account.status === "disconnected" ? "account.disconnected" : "account.error";
  const failure = error ?? readError ?? status?.serviceError ?? status?.account?.error_code ?? null;
  const pair = (label: MessageKey, value: unknown, suffix = "") => <><dt>{t(label, {}, locale)}</dt><dd>{scalar(value)}{suffix && ` ${suffix}`}</dd></>;
  const leg = (value: unknown) => value === "long" || value === "short" ? t(`account.${value}`, {}, locale) : t("account.unknown", {}, locale);

  return <section className="readonly-account-dock" style={{ height }} aria-label={t("account.title", {}, locale)}>
    <header>
      <div className="readonly-account-heading"><strong>{t("account.title", {}, locale)}</strong><button type="button" aria-label={t("account.closePanel", {}, locale)} onClick={onRequestClose}>×</button></div>
      <p className="readonly-account-scope">{t("account.scope", {}, locale)}</p>
      <div className="readonly-account-identity">
        <span role="status">{t(stateKey, {}, locale)}</span>
        {status?.account && <span>UID {status.account.venue_uid}</span>}
      </div>
    </header>
    <div className="readonly-account-body">
      <p className="readonly-account-help">{t("account.boundary", {}, locale)}</p>
      {!available || status?.available === false ? <p>{t("account.desktopRequired", {}, locale)}</p> : <>
        {status?.account && <p className="readonly-account-help">{t("account.lastRead", { time: date(status.account.last_success_ms) }, locale)}</p>}
        {failure && <div className="readonly-account-error" role="alert"><p>{t(accountErrorHelp(failure), {}, locale)}</p><code>{failure}</code></div>}
        <div className="readonly-account-actions">
          <button type="button" disabled={busy} onClick={() => setCredentialsOpen(!credentialsOpen)}>{t(status?.account ? "account.rotate" : "account.connect", {}, locale)}</button>
          {status?.account && <><button type="button" disabled={busy} onClick={() => { void action(resyncAccount); }}>{t("account.sync", {}, locale)}</button>
            <button type="button" disabled={busy || !status.account.enabled} onClick={() => { void action(() => disconnectAccount(false)); }}>{t("account.pause", {}, locale)}</button></>}
        </div>
        {credentialsOpen && <form onSubmit={connect} autoComplete="off">
          <p className="readonly-account-help">{t("account.credentialsHelp", {}, locale)}</p>
          {([ ["apiKey", "account.key"], ["secret", "account.secret"], ["password", "account.passphrase"] ] as const).map(([name, label]) => <label key={name}>{t(label, {}, locale)}<input name={name} type="password" autoComplete="off" spellCheck={false} required maxLength={256} disabled={busy} /></label>)}
          <button type="submit" disabled={busy}>{t(busy ? "account.working" : "account.connect", {}, locale)}</button>
          {status?.account && <><p className="readonly-account-help">{t("account.forgetHelp", {}, locale)}</p><button type="button" disabled={busy} onClick={() => { void action(() => disconnectAccount(true)); }}>{t("account.forget", {}, locale)}</button></>}
        </form>}
        <nav aria-label={t("account.title", {}, locale)}>{TABS.map((id) => <button type="button" key={id} aria-pressed={tab === id} onClick={() => setTab(id)}>{t(`account.${id}`, {}, locale)}</button>)}</nav>
        {tab === "overview" && <>
          <p className="readonly-account-help">{t("account.reconciliation", {}, locale)}</p>
          <h4>{t("account.positions", {}, locale)}</h4>
          <p className="readonly-account-help">{t("account.snapshotTime", { time: date(positionsSnapshot?.receivedMs) }, locale)}</p>
          {!positionData.length && <p>{t("account.empty", {}, locale)}</p>}
          {positionData.map((item, index) => <article className="readonly-account-card" key={`${scalar(item.positionId)}:${index}`}><strong>{scalar(item.instrument)} · {leg(item.positionSide)}</strong><dl>
            {pair("account.contracts", item.contracts)}{pair("account.entry", item.entryPrice)}{pair("account.mark", item.markPrice)}{pair("account.pnl", item.unrealizedPnl, unit(item.settleCurrency))}</dl></article>)}
          <h4>{t("account.openOrders", {}, locale)}</h4>
          <p className="readonly-account-help">{t("account.snapshotTime", { time: date(status?.snapshots.open_orders?.receivedMs) }, locale)}</p>
          {!openOrders.length && <p>{t("account.empty", {}, locale)}</p>}
          {openOrders.map((item, index) => <article className="readonly-account-card" key={`${scalar(item.orderId)}:${index}`}><strong>{scalar(item.instrument)} · {leg(item.positionSide)}</strong><dl>{pair("account.contracts", item.contracts)}{pair("account.price", item.price)}</dl></article>)}
          <h4>{t("account.balance", {}, locale)}</h4><p className="readonly-account-help">{t("account.balanceHelp", {}, locale)}</p>
          <p className="readonly-account-help">{t("account.snapshotTime", { time: date(status?.snapshots.balances?.receivedMs) }, locale)}</p>
          {balances.map((item, index) => <article className="readonly-account-card" key={`${scalar(item.ccy)}:${index}`}><strong>{scalar(item.ccy)}</strong><dl>{pair("account.equity", item.eq)}{pair("account.cash", item.cashBal)}</dl></article>)}
          <details><summary>{t("account.coverage", {}, locale)}</summary><p className="readonly-account-help">{t("account.coverageHelp", {}, locale)}</p>
            {status?.scans.map((scan) => <p key={scan.kind}>{t(`account.${scan.kind as FactKind}`, {}, locale)} · {date(scan.start_ms)} – {date(scan.end_ms)}<br />{t(scan.complete ? "account.queryComplete" : "account.queryPending", { pages: scan.pages }, locale)}</p>)}
            {status?.gaps.map((gap, index) => <p key={index}>{t("account.gap", {}, locale)} · {scalar(gap.kind)}<br />{date(gap.start_ms)} – {date(gap.end_ms)}</p>)}
          </details>
          <p className="readonly-account-help">{t("account.lastEvent", { time: date(status?.stream.lastReceivedMs) }, locale)}</p>
          {status?.stream.error && <p>{t(accountErrorHelp(status.stream.error), {}, locale)} <code>{status.stream.error}</code></p>}
        </>}
        {tab !== "overview" && tab !== "journal" && <>
          <button type="button" disabled={loadingFacts} onClick={() => { void loadFacts(false); }}>{t(loadingFacts ? "account.loading" : "account.refresh", {}, locale)}</button>
          {tab === "bills" && <p className="readonly-account-help">{t("account.unassignedFunding", {}, locale)}</p>}
          {!loadingFacts && !page.items.length && <p>{t("account.empty", {}, locale)}</p>}
          {page.items.map((item, index) => <article key={`${scalar(item.fillId ?? item.orderId ?? item.billId)}:${index}`} className="readonly-account-card">
            <strong>{scalar(item.instrument)} {leg(item.positionSide)}</strong><p>{date(typeof item.eventTimeMs === "number" ? item.eventTimeMs : null)}</p><dl>
              {tab === "bills" ? pair("account.amount", item.cashChange, unit(item.currency)) : <>{pair("account.contracts", item.contracts)}{pair("account.price", item.price)}</>}
              {item.feeCashChange !== undefined && pair("account.fee", item.feeCashChange, unit(item.feeCurrency ?? item.currency))}
            </dl>
            {tab === "fills" && <><p>{item.effect === "open" || item.effect === "close" ? t(`account.${item.effect}`, {}, locale) : "—"}</p><button type="button" onClick={() => { setNewNoteRequest({ id: crypto.randomUUID(), fillId: scalar(item.fillId) }); setTab("journal"); }}>{t("account.linkFill", {}, locale)}</button></>}
            {tab === "bills" && item.inSelectedScope === false && <p className="readonly-account-help">{t("account.otherScope", {}, locale)}</p>}
          </article>)}
          {page.next && <button type="button" disabled={loadingFacts} onClick={() => { void loadFacts(true); }}>{t("account.more", {}, locale)}</button>}
        </>}
        {tab === "journal" && <AccountJournal {...(newNoteRequest ? { newNoteRequest } : {})} onRequestHandled={noteRequestHandled} />}
      </>}
    </div>
  </section>;
}
