import { useCallback, useEffect, useState } from 'react';
import { t, type MessageKey } from '../../i18n/index.js';
import { useLocale } from '../../i18n/useLocale.js';
import { AccountApiError } from './accountApi.js';
import { accountErrorHelp } from './accountErrors.js';
import { getReconciliation, type Reconciliation } from './reconciliationApi.js';

export default function AccountReconciliation() {
  const locale = useLocale();
  const [report, setReport] = useState<Reconciliation | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const read = useCallback(async (signal?: AbortSignal) => {
    setBusy(true); setError(null);
    try { const value = await getReconciliation(signal); if (!signal?.aborted) setReport(value); }
    catch (e) { if (!signal?.aborted) setError(e instanceof AccountApiError ? e.code : 'ACCOUNT_UNAVAILABLE'); }
    finally { if (!signal?.aborted) setBusy(false); }
  }, []);
  useEffect(() => { const abort = new AbortController(); void read(abort.signal); return () => abort.abort(); }, [read]);
  const label = (key: MessageKey) => t(key, {}, locale);
  const date = (ms: number | null) => ms === null ? label('account.unknown') : new Date(ms).toLocaleString(locale);
  const pair = (key: MessageKey, value: string | number | null, currency = '') => <><dt>{label(key)}</dt><dd>{value ?? '—'} {currency}</dd></>;
  return <div aria-label={label('account.reconcile')}>
    <p className="readonly-account-help">{label('account.reconcileHelp')}</p>
    <button type="button" disabled={busy} onClick={() => { void read(); }}>{label(busy ? 'account.loading' : 'account.refresh')}</button>
    {error && <p role="alert">{label(accountErrorHelp(error))} <code>{error}</code></p>}
    {report && <>
      <p role="status">{label(`account.check.${report.status}`)} · {date(report.generatedMs)}</p>
      {(!report.current || !report.historyReady) && <p>{label('account.check.historyUnavailable')}</p>}
      {report.truncated && <p>{label('account.check.truncated')}</p>}
      <p>{label('account.check.fillFees')}: {report.fees.checked} / {report.fees.total} · {label(`account.check.${report.fees.status}`)}</p>
      {report.fees.issues.map((row, i) => <p key={i}>{row.id} · {label(`account.check.${row.reason}`)}</p>)}
      <p>{label('account.check.closedPositions')}: {report.counts.matchedPositions} / {report.counts.positions} · {label('account.check.unmatchedFills')}: {report.counts.unmatchedFills}</p>
      <p>{label('account.check.fundingAssigned')}: {report.counts.assignedFunding} / {report.counts.funding}</p>
      <h4>{label('account.check.cashChain')}</h4>
      <p className="readonly-account-help">{label('account.check.openingHelp')}</p>
      {report.cash.map(row => <article className="readonly-account-card" key={row.currency}><strong>{row.currency} · {label(`account.check.${row.status}`)}</strong>
        {row.reason && <p>{label(`account.check.${row.reason}`)}</p>}<dl>
          {pair('account.check.openingDerived', row.openingDerived)}{pair('account.amount', row.change)}{pair('account.check.closing', row.closing)}
          {pair('account.cash', row.snapshot)}{pair('account.check.difference', row.difference)}{pair('account.check.tolerance', row.tolerance)}{pair('account.check.breaks', row.breaks)}
        </dl><p>{t('account.snapshotTime', { time: date(row.snapshotMs) }, locale)}</p></article>)}
      <h4>{label('account.check.closedPositions')}</h4>
      {report.positions.map((row, i) => <article className="readonly-account-card" key={`${row.id}:${i}`}>
        <strong>{row.instrument} · {label(`account.${row.positionSide}`)} · {label(`account.check.${row.status}`)}</strong>
        <p>{date(row.startMs)} – {date(row.endMs)}</p>
        {row.reason && <p>{label(`account.check.${row.reason}`)}</p>}<dl>
          {pair('account.check.computedPnl', row.computedPnl, row.currency)}{pair('account.check.exchangePnl', row.exchangePnl, row.currency)}
          {pair('account.check.difference', row.pnlDifference, row.currency)}{pair('account.check.tolerance', row.tolerance, row.currency)}
          {pair('account.fee', row.fee, row.currency)}{pair('account.check.funding', row.funding, row.currency)}{pair('account.check.net', row.net, row.currency)}
        </dl><p>{label('account.check.positionSource')}: {row.id}</p>
      </article>)}
      <h4>{label('account.check.fundingAssigned')}</h4>
      <p className="readonly-account-help">{label('account.check.attributionHelp')}</p>
      {report.funding.map(row => <article className="readonly-account-card" key={row.billId}>
        <strong>{row.instrument} · {row.positionSide ? label(`account.${row.positionSide}`) : label('account.unknown')}</strong>
        <p>{date(row.eventTimeMs)} · {row.amount} {row.currency}</p>
        <p>{row.reason ? label(`account.check.${row.reason}`) : `${label('account.check.positionSource')}: ${row.positionId}`}</p>
        <small>{row.billId}</small>
      </article>)}
    </>}
  </div>;
}
