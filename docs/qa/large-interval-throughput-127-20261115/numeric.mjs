import assert from 'node:assert/strict';

const ADDITIVE_FIELDS = new Set(['volume', 'quote_volume', 'taker_buy_base', 'taker_buy_quote']);

export function compareField(actual, expected, field, context) {
  actual ??= null;
  expected ??= null;
  if (ADDITIVE_FIELDS.has(field) && actual !== null && expected !== null) {
    assert.ok(Number.isFinite(actual) && Number.isFinite(expected), context + ': finite additive values');
  }
  if (actual === expected) return null;
  if (!ADDITIVE_FIELDS.has(field) || actual === null || expected === null) {
    assert.equal(actual, expected, context);
  }
  assert.ok(Number.isFinite(actual) && Number.isFinite(expected), context + ': finite additive values');
  // K130 permits 1e-8 absolute / 1e-12 relative for different groupings.
  // Use a tighter relative allowance: four double-precision rounding units.
  const absolute = Math.abs(actual - expected);
  const scale = Math.max(Math.abs(actual), Math.abs(expected));
  const tolerance = Math.max(1e-8, 4 * Number.EPSILON * scale);
  assert.ok(absolute <= tolerance, `${context}: ${actual} != ${expected} (tolerance ${tolerance})`);
  return { absolute, relative: scale ? absolute / scale : 0, tolerance };
}
