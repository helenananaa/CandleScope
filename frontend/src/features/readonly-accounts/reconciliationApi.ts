import { AccountApiError, accountRequest, record } from './accountApi.js';

export const reconciliationReasons = ['historyUnavailable', 'unsupportedPosition', 'openingUnknown', 'coverageGap',
  'currencyMismatch', 'ambiguousOrder', 'ambiguousHistory', 'amountMismatch', 'missingAmount',
  'noUniquePosition', 'settlementBoundary', 'fundingDifference', 'missingBill', 'missingFill',
  'identityMismatch', 'cashDifference', 'missingBills', 'missingSnapshot'] as const;
export type ReconciliationReason = typeof reconciliationReasons[number];
type Result = 'matched' | 'partial';
export interface Reconciliation {
  schemaVersion: 1; status: Result; generatedMs: number; lastReadMs: number | null;
  historyReady: boolean; current: boolean; truncated: boolean; contractKinds: string[];
  counts: { positions: number; matchedPositions: number; unmatchedFills: number; funding: number; assignedFunding: number; cash: number };
  fees: { status: Result; checked: number; total: number; issueCount: number; issues: { id: string; reason: ReconciliationReason }[] };
  cash: { currency: string; status: Result; count: number; breaks: number; openingDerived: string | null; change: string | null;
    closing: string | null; snapshot: string | null; difference: string | null; reason: ReconciliationReason | null; snapshotMs: number | null }[];
  positions: { id: string; instrument: string; positionSide: 'long' | 'short'; marginMode: string; currency: string; status: Result;
    reason: ReconciliationReason | null; startMs: number | null; endMs: number | null; fillCount: number; computedPnl: string | null;
    exchangePnl: string | null; pnlDifference: string | null; tolerance: string | null; fee: string | null; funding: string | null; net: string | null; fundingCount: number }[];
  funding: { billId: string; instrument: string; currency: string; eventTimeMs: number; amount: string; positionSide: 'long' | 'short' | null;
    positionId: string | null; reason: ReconciliationReason | null }[];
}
const str = (v: unknown) => typeof v === 'string' && v.length <= 128;
const count = (v: unknown) => typeof v === 'number' && Number.isSafeInteger(v) && v >= 0;
const time = (v: unknown) => v === null || count(v);
const amount = (v: unknown) => v === null || (typeof v === 'string' && v.length <= 200 && /^-?\d+(\.\d+)?$/.test(v));
const result = (v: unknown) => v === 'matched' || v === 'partial';
const reason = (v: unknown) => v === null || reconciliationReasons.includes(v as ReconciliationReason);
const list = (v: unknown, check: (r: Record<string, unknown>) => boolean) => Array.isArray(v) && v.length <= 500 && v.every((r: unknown) => record(r) && check(r));
const fields = (r: Record<string, unknown>, keys: string[], check: (v: unknown) => boolean) => keys.every(k => check(r[k]));

export function parseReconciliation(v: unknown): Reconciliation {
  if (!record(v) || v.schemaVersion !== 1 || !result(v.status) || !count(v.generatedMs) || !time(v.lastReadMs)
    || !fields(v, ['historyReady', 'current', 'truncated'], value => typeof value === 'boolean')
    || !Array.isArray(v.contractKinds) || !v.contractKinds.every(k => k === 'linear' || k === 'inverse')
    || !record(v.counts) || !fields(v.counts, ['positions','matchedPositions','unmatchedFills','funding','assignedFunding','cash'], count)
    || !record(v.fees) || !result(v.fees.status) || !fields(v.fees, ['checked','total','issueCount'], count)
    || !list(v.fees.issues, r => str(r.id) && r.reason !== null && reason(r.reason))
    || !list(v.cash, r => str(r.currency) && result(r.status) && count(r.count) && count(r.breaks) && reason(r.reason) && time(r.snapshotMs)
      && fields(r, ['openingDerived','change','closing','snapshot','difference'], amount))
    || !list(v.positions, r => fields(r, ['id','instrument','marginMode','currency'], str) && (r.positionSide === 'long' || r.positionSide === 'short')
      && result(r.status) && reason(r.reason) && time(r.startMs) && time(r.endMs) && count(r.fillCount) && count(r.fundingCount)
      && fields(r, ['computedPnl','exchangePnl','pnlDifference','tolerance','fee','funding','net'], amount))
    || !list(v.funding, r => fields(r, ['billId','instrument','currency'], str) && count(r.eventTimeMs) && r.amount !== null && amount(r.amount)
      && (r.positionSide === null || r.positionSide === 'long' || r.positionSide === 'short') && (r.positionId === null || str(r.positionId)) && reason(r.reason))) {
    throw new AccountApiError('ACCOUNT_RESPONSE_INVALID');
  }
  return v as unknown as Reconciliation;
}
export async function getReconciliation(signal?: AbortSignal): Promise<Reconciliation> {
  return parseReconciliation(await accountRequest('/reconciliation', 'GET', undefined, signal));
}
