import assert from 'node:assert/strict';
import test from 'node:test';
import { compareField } from './numeric.mjs';

test('accepts the observed quote turnover rounding unit, retaining its magnitude', () => {
  const result = compareField(79060615711.7157, 79060615711.71571, 'quote_volume', '10007m');
  assert.equal(result.absolute, 0.0000152587890625);
  assert.ok(result.relative < 2e-16);
});
test('rejects an additive discrepancy beyond the bounded rounding allowance', () => {
  assert.throws(() => compareField(79060615711.70, 79060615711.71571, 'quote_volume', '10007m'));
});
test('keeps OHLC, timestamps and integer counts exact', () => {
  for (const field of ['open', 'high', 'low', 'close', 'time', 'trades']) {
    assert.throws(() => compareField(1, 1 + Number.EPSILON, field, field));
  }
});
test('preserves missingness and rejects nonfinite additive values', () => {
  assert.equal(compareField(undefined, null, 'quote_volume', 'missing'), null);
  assert.throws(() => compareField(0, null, 'quote_volume', 'missing'));
  assert.throws(() => compareField(Infinity, 1, 'quote_volume', 'infinite'));
  assert.throws(() => compareField(Infinity, Infinity, 'quote_volume', 'infinite equal'));
  assert.throws(() => compareField(NaN, 1, 'quote_volume', 'nan'));
});
