import assert from 'node:assert/strict';
import test from 'node:test';
import { parseReconciliation } from './reconciliationApi.js';
const base = { schemaVersion: 1, status: 'partial', generatedMs: 1, lastReadMs: null, historyReady: false, current: false, truncated: false,
  contractKinds: [], counts: { positions: 0, matchedPositions: 0, unmatchedFills: 0, funding: 1, assignedFunding: 0, cash: 0 },
  fees: { status: 'partial', checked: 0, total: 0, issueCount: 0, issues: [] }, cash: [], positions: [],
  funding: [{ billId: '1', instrument: 'BTC-USD-SWAP', currency: 'BTC', eventTimeMs: 1, amount: '-0.00000000000001', positionSide: null, positionId: null, reason: 'noUniquePosition' }] };
test('reconciliation preserves exact amounts and an unassigned leg', () => {
  const parsed = parseReconciliation(base);
  assert.equal(parsed.funding[0]?.amount, '-0.00000000000001');
  assert.equal(parsed.funding[0]?.positionSide, null);
});
test('reconciliation rejects float amounts, nonfinite dates, unknown reasons and oversized details', () => {
  for (const value of [
    { ...base, funding: [{ ...base.funding[0], amount: 0.1 }] },
    { ...base, generatedMs: Infinity },
    { ...base, funding: [{ ...base.funding[0], reason: 'RAW_SECRET_MESSAGE' }] },
    { ...base, funding: Array(501).fill(base.funding[0]) },
    { ...base, counts: { ...base.counts, assignedFunding: -1 } },
  ]) assert.throws(() => parseReconciliation(value), /ACCOUNT_RESPONSE_INVALID/);
});
