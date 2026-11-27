import assert from "node:assert/strict";
import test from "node:test";
import type { AccountStatus } from "./accountApi.js";
import { ACCOUNT_STALE_AFTER_MS, accountFreshness, formatAccountAge } from "./accountFreshness.js";

const NOW = 1_800_000_000_000;

function state(patch: { account?: Partial<NonNullable<AccountStatus["account"]>> | null; serviceError?: string | null;
  snapshots?: Record<string, number> }): AccountStatus {
  const account = patch.account === null ? null : { status: "synced", error_code: null, venue_uid: "1", last_success_ms: NOW, enabled: 1, ...patch.account };
  const ages = patch.snapshots ?? { positions: 5_000, open_orders: 5_000, balances: 5_000 };
  return {
    available: true, serviceError: patch.serviceError ?? null, account, counts: {}, scans: [], coverage: [], gaps: [],
    snapshots: Object.fromEntries(Object.entries(ages).map(([kind, age]) => [kind, { receivedMs: NOW - age, data: [] }])),
    stream: { state: "observed", lastReceivedMs: NOW, error: null }, reconciliation: "not_verified",
  };
}

test("a running sync with recent snapshots is not out of date", () => {
  const freshness = accountFreshness(state({}), null, NOW)!;
  assert.equal(freshness.stale, false);
  assert.equal(freshness.reason, null);
  assert.equal(freshness.ageMs, 5_000);
  assert.equal(freshness.snapshots.positions.stale, false);
});

test("no connected account has no freshness to show", () => {
  assert.equal(accountFreshness(state({ account: null }), null, NOW), null);
  assert.equal(accountFreshness(null, null, NOW), null);
});

test("values that can no longer update are out of date at once, with the reason", () => {
  assert.equal(accountFreshness(state({ account: { enabled: 0, status: "disconnected" } }), null, NOW)!.reason, "paused");
  assert.equal(accountFreshness(state({ serviceError: "ACCOUNT_RESOURCE_CLEANUP_FAILED" }), null, NOW)!.reason, "service");
  const lost = accountFreshness(state({}), "ACCOUNT_STATE_STREAM_ENDED", NOW)!;
  assert.equal(lost.stale, true);
  assert.equal(lost.reason, "localService");
  assert.deepEqual(Object.values(lost.snapshots).map((item) => item.stale), [true, true, true]);
});

test("the local connection outranks paused, and paused outranks a sync error", () => {
  const paused = state({ account: { enabled: 0, status: "error", error_code: "ACCOUNT_NETWORK_UNAVAILABLE" } });
  assert.equal(accountFreshness(paused, "ACCOUNT_NETWORK_UNAVAILABLE", NOW)!.reason, "localService");
  assert.equal(accountFreshness(paused, null, NOW)!.reason, "paused");
});

test("a sync error or a slow sync marks only the snapshots past the limit", () => {
  const ages = { positions: ACCOUNT_STALE_AFTER_MS + 1, open_orders: 5_000, balances: ACCOUNT_STALE_AFTER_MS };
  const failed = accountFreshness(state({ account: { status: "error", error_code: "ACCOUNT_RATE_LIMITED" }, snapshots: ages }), null, NOW)!;
  assert.equal(failed.reason, "error");
  assert.deepEqual([failed.snapshots.positions.stale, failed.snapshots.open_orders.stale, failed.snapshots.balances.stale], [true, false, false]);
  assert.equal(failed.ageMs, ACCOUNT_STALE_AFTER_MS + 1);
  const slow = accountFreshness(state({ snapshots: ages }), null, NOW)!;
  assert.equal(slow.reason, "slow");
  // A recent failure with fresh values is shown as an error, not as stale data.
  const recent = accountFreshness(state({ account: { status: "error", error_code: "ACCOUNT_RATE_LIMITED" } }), null, NOW)!;
  assert.equal(recent.stale, false);
  assert.equal(recent.reason, null);
});

test("missing snapshots are never out of date and do not set the age", () => {
  const freshness = accountFreshness(state({ account: { enabled: 0, status: "disconnected" }, snapshots: {} }), null, NOW)!;
  assert.equal(freshness.stale, false);
  assert.equal(freshness.ageMs, null);
  assert.equal(freshness.snapshots.balances.receivedMs, null);
});

test("ages read as elapsed time in the panel's language", () => {
  assert.equal(formatAccountAge(4_000, "en"), "now");
  assert.equal(formatAccountAge(37_000, "en"), "30 seconds ago");
  assert.equal(formatAccountAge(150_000, "en"), "2 minutes ago");
  assert.equal(formatAccountAge(3 * 3_600_000 + 1, "en"), "3 hours ago");
  assert.equal(formatAccountAge(86_400_000 + 1, "en"), "1 day ago");
  assert.equal(formatAccountAge(150_000, "zh-CN"), "2分钟前");
});
