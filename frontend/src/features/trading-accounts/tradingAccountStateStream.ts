import { API_BASE } from "../../services/apiConfig.js";
import type { AccountSummary, Trade, JournalEntry } from "./tradingTypes.js";

export interface TradingAccountSnapshot {
  cursor: { epoch: string; sequence: number };
  summary: AccountSummary;
  trades: Trade[];
  entries: JournalEntry[] | null;
  journalError?: string | null;
}
const record = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === "object" && !Array.isArray(v);
const epoch = (v: unknown): v is string => typeof v === "string" && /^[a-f0-9]{32}$/.test(v);
const sequence = (v: unknown): v is number => typeof v === "number" && Number.isSafeInteger(v) && v >= 0;
const money = (v: unknown): v is string => typeof v === "string" && /^-?\d+(?:\.\d+)?$/.test(v);
function invalid(): never { throw new Error("Invalid trading account stream response"); }

function snapshot(value: unknown, accountId: string): TradingAccountSnapshot {
  if (!record(value) || !record(value.cursor) || !epoch(value.cursor.epoch) || !sequence(value.cursor.sequence)
    || !record(value.summary) || !record(value.summary.account) || value.summary.account.id !== accountId
    || !["practice", "manual"].includes(String(value.summary.account.kind))) return invalid();
  const summary = value.summary;
  for (const key of ["balance", "equity", "unrealizedPnl", "usedMargin", "available"]) if (!money(summary[key])) invalid();
  for (const key of ["positions", "workingOrders", "feeds"]) if (!Array.isArray(summary[key])) invalid();
  if (!Array.isArray(value.trades) || !sequence(summary.closedTrades)
    || (value.entries === null ? typeof value.journalError !== "string" : !Array.isArray(value.entries))) invalid();
  if (value.journalError != null && typeof value.journalError !== "string") invalid();
  const entries: unknown[] = Array.isArray(value.entries) ? value.entries : [];
  for (const rows of [summary.positions, summary.workingOrders, value.trades, value.entries ?? []]) {
    if (!Array.isArray(rows) || rows.some(row => !record(row) || row.accountId !== accountId || typeof row.id !== "string")) invalid();
  }
  const trades: unknown[] = value.trades;
  for (const row of (summary.positions as unknown[]).concat(trades)) {
    if (!record(row) || !Array.isArray(row.legs) || !["long", "short"].includes(String(row.direction))
      || !["open", "closed"].includes(String(row.status))) invalid();
    for (const key of ["openQty", "maxQty", "entryQty", "exitQty", "realizedPnl", "fees", "netPnl"]) if (!money(row[key])) invalid();
    for (const key of ["markPrice", "unrealizedPnl", "avgEntryPrice", "avgExitPrice"]) if (row[key] !== null && !money(row[key])) invalid();
  }
  for (const entry of entries) if (!record(entry) || !Array.isArray(entry.tags) || !record(entry.fields)
    || !Array.isArray(entry.snapshots) || !record(entry.fieldTiming) || typeof entry.body !== "string") invalid();
  return value as unknown as TradingAccountSnapshot;
}

/** Full replacement on every connection. Ledger revision is persistent;
 * connection sequence also orders unflushed valuation observations. */
export async function streamTradingAccountState(accountId: string, parentSignal: AbortSignal,
  update: (value: TradingAccountSnapshot) => void): Promise<void> {
  const deadline = new AbortController();
  const signal = AbortSignal.any([parentSignal, deadline.signal]);
  let timer: ReturnType<typeof setTimeout>;
  const resetDeadline = () => {
    clearTimeout(timer);
    timer = setTimeout(() => deadline.abort(new Error("Trading account stream timed out")), 30_000);
  };
  resetDeadline();
  try {
  signal.throwIfAborted();
  const response = await fetch(`${API_BASE}/trading/accounts/${encodeURIComponent(accountId)}/events`,
    { signal, credentials: "omit", cache: "no-store", redirect: "error" });
  if (signal.aborted) { await response.body?.cancel().catch(() => {}); signal.throwIfAborted(); }
  if (!response.ok || !response.body || !response.headers.get("content-type")?.startsWith("application/x-ndjson")) {
    await response.body?.cancel().catch(() => {});
    throw new Error("Trading account stream unavailable");
  }
  const reader=response.body.getReader(), decoder=new TextDecoder("utf-8", { fatal:true });
  let buffer="", connection: string | null=null, ledger: string | null=null, frameSequence=0, revision=-1, previous="";
  const abort=()=>{void reader.cancel().catch(()=>{});};
  signal.addEventListener("abort",abort,{once:true});
  function frame(line: string) {
    const raw: unknown=JSON.parse(line);
    if (!record(raw) || raw.schema!=="candlescope.trading-account-state/1") invalid();
    if (raw.type==="heartbeat") { if (connection===null) invalid(); resetDeadline(); return; }
    if (raw.type==="error" && record(raw.error)) throw new Error(typeof raw.error.message === "string" ? raw.error.message : "Trading account stream failed");
    if (raw.type!=="snapshot" || raw.replacement!==true || !record(raw.identity)
      || raw.identity.accountId!==accountId || !epoch(raw.connectionEpoch) || !sequence(raw.sequence)
      || raw.sequence<1 || (connection!==null && connection!==raw.connectionEpoch)) invalid();
    const state=snapshot(raw.state,accountId);
    if (raw.identity.ledgerEpoch!==state.cursor.epoch || (ledger!==null && ledger!==state.cursor.epoch)
      || state.cursor.sequence<revision || raw.sequence<frameSequence) invalid();
    if (raw.sequence===frameSequence) { if (line!==previous) invalid(); resetDeadline(); return; }
    connection=raw.connectionEpoch;ledger=state.cursor.epoch;revision=state.cursor.sequence;
    frameSequence=raw.sequence;previous=line;resetDeadline();update(state);
  }
  try {
    while (true) {
      const {value,done}=await reader.read();signal.throwIfAborted();
      buffer+=done?decoder.decode():decoder.decode(value,{stream:true});
      let index;
      while ((index=buffer.indexOf("\n"))>=0) {
        if (index>8*1024*1024) invalid();
        const line=buffer.slice(0,index);buffer=buffer.slice(index+1);
        if (line.trim()) frame(line);
        signal.throwIfAborted();
      }
      if (buffer.length>8*1024*1024) invalid();
      if (done) throw new Error("Trading account stream ended");
    }
  } finally { signal.removeEventListener("abort",abort);await reader.cancel().catch(()=>{});reader.releaseLock(); }
  } finally { clearTimeout(timer!); }
}
