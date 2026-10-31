import { validateKlineDomain } from "../../../utils/klineDomainPolicy.js";
import type { KlineFetchResult } from "../klineContracts.js";
import type { KlineBar } from "../marketDataTypes.js";

export type KlineEndpoint = "history" | "before" | "range" | "latest" | "seed";
export interface KlineQualityEvidence {
  /** Evidence describes this response only, never the entire merged window. */
  scope: "response";
  rowCount: number;
  firstTime: number | null;
  lastTime: number | null;
  endpoint: KlineEndpoint;
  coverage: "verified" | "incomplete" | "unknown";
  finality: "final" | "forming" | "unknown";
  availability: "ready" | "pending" | "exhausted" | "unknown";
  complete: boolean;
  repairPending: boolean;
  reasons: string[];
}

/** Terminal availability may stop retries without proving complete coverage. */
export function isKlineResultRepairPending(result: KlineFetchResult | null | undefined): boolean {
  if (!result) return true;
  if (result.history_state === "exhausted" && result.retryable === false) return false;
  return Boolean(result.history_state === "pending" || result.complete === false || result.retryable === true
    || result.verified_contiguous === false || result.has_tail_gap === true || result.truncated === true
    || (result.missing_ranges?.length ?? 0) > 0 || (!result.data?.length && result.has_more === true));
}

export function assessKlineQuality(result: KlineFetchResult | null | undefined, endpoint: KlineEndpoint): KlineQualityEvidence {
  const reasons: string[] = [];
  if (!result) return { scope: "response", rowCount: 0, firstTime: null, lastTime: null, endpoint, coverage: "unknown", finality: "unknown", availability: "unknown",
    complete: false, repairPending: true, reasons: ["missing-response"] };
  const rows = result.data ?? [];
  const forming = rows.some((row) => row.is_closed === false);
  if (result.all_rows_final === true && forming) reasons.push("finality-contradiction");
  const gaps = (result.missing_ranges?.length ?? 0) > 0;
  if (result.complete === true && (gaps || result.verified_contiguous === false || result.has_tail_gap === true
    || result.truncated === true || result.history_state === "pending" || result.retryable === true)) reasons.push("completion-contradiction");
  const incomplete = gaps || result.verified_contiguous === false || result.has_tail_gap === true || result.truncated === true;
  const coverage = incomplete ? "incomplete" : result.verified_contiguous === true
    && Array.isArray(result.missing_ranges) && result.has_tail_gap === false ? "verified" : "unknown";
  // History/before historically omit truncated on an uncapped response. Strict
  // range recovery requires explicit false; latest and seed prove no history.
  const truncationProven = endpoint === "range" ? result.truncated === false : result.truncated !== true;
  const finality = forming ? "forming" : result.all_rows_final === true ? "final" : "unknown";
  const complete = endpoint !== "latest" && endpoint !== "seed" && reasons.length === 0
    && result.complete === true && result.retryable === false
    && (result.history_state === "ready" || result.history_state === "exhausted")
    && coverage === "verified" && finality === "final" && truncationProven;
  if (!complete && !reasons.length) reasons.push(endpoint === "seed" || endpoint === "latest" ? "not-history-proof" : "incomplete-or-unknown-proof");
  return { scope: "response", rowCount: rows.length, firstTime: rows[0]?.time ?? null, lastTime: rows.at(-1)?.time ?? null, endpoint, coverage, finality, availability: result.history_state ?? "unknown", complete,
    repairPending: isKlineResultRepairPending(result), reasons };
}

/** A forming snapshot cannot reopen a known final row; final amendments can. */
export function preserveFinalRow<T extends Record<string, unknown>>(incoming: T, held: T | null | undefined): T {
  return held?.is_closed === true && incoming.is_closed === false ? held : incoming;
}

export function assessRealtimeEffect(row: KlineBar, eventType: unknown, held: KlineBar | null | undefined, latestTime: number | null) {
  const amendment = eventType === "bar.amended";
  const invalid = validateKlineDomain(row);
  const accepted = !invalid && preserveFinalRow(row, held) === row;
  const current = latestTime === null || row.time >= latestTime;
  const changed = held && ["open", "high", "low", "close", "volume", "is_closed"].some((field) => row[field] !== held[field]);
  return { accepted, updatesQuote: accepted && current && !amendment,
    updatesFreshness: accepted && current && !amendment,
    requiresReadback: accepted && amendment && Boolean(changed),
    reason: invalid ? "invalid-row" : !accepted ? "forming-after-final" : amendment ? "historical-amendment" : current ? "current-row" : "historical-row" };
}

/** Legacy HTTP/WS have no comparable source revision; opaque fields do not outrank a request fence. */
export function chooseHttpRow(row: KlineBar, mutation: { row: KlineBar; authoritative: boolean; version: number } | undefined,
  requestVersion: number, trustedFinalResponse: boolean): "http" | "realtime" | "promote-http" {
  if (!mutation) return "http";
  if (mutation.authoritative) return "realtime";
  if (trustedFinalResponse && row.is_closed === true) return "promote-http";
  return mutation.version > requestVersion ? "realtime" : "http";
}

/** Continuity recovery may include a forming tail; it is not final-history proof. */
export function hasVerifiedCoverage(result: KlineFetchResult, endpoint: KlineEndpoint): boolean {
  const quality = assessKlineQuality(result, endpoint);
  return endpoint !== "latest" && endpoint !== "seed"
    && result.complete === true && result.retryable === false
    && (endpoint === "range" ? result.truncated === false : result.truncated !== true)
    && (quality.availability === "ready" || quality.availability === "exhausted")
    && quality.coverage === "verified" && !quality.reasons.includes("completion-contradiction")
    && !quality.reasons.includes("finality-contradiction");
}

export function hasVerifiedRangeCoverage(result: KlineFetchResult): boolean {
  return hasVerifiedCoverage(result, "range");
}

export function hasFinalityEvidence(result: KlineFetchResult): boolean {
  return result.all_rows_final === true && !(result.data ?? []).some((row) => row.is_closed === false);
}

/** Capped parents own only retained rows; children must prove every missing range. */
export function hasRetainedFinalRangeProof(result: KlineFetchResult): boolean {
  return hasFinalityEvidence(result) && result.has_tail_gap === false && Array.isArray(result.missing_ranges);
}

export function isKlineTailFresh(result: KlineFetchResult | null | undefined): boolean {
  if (!result) return false;
  const quality = assessKlineQuality(result, result.endpoint ?? "history");
  return quality.coverage === "verified" && result.complete === true && result.retryable === false
    && quality.availability === "ready" && !quality.repairPending
    && !quality.reasons.includes("finality-contradiction") && !quality.reasons.includes("completion-contradiction");
}

/** Declared unavailability stops automatic retry, without proving recovered data. */
export function recoveryRetryDecision(result: KlineFetchResult, now: number): { retryAt: number; reason: string } | null {
  if (result.retryable !== false) return null;
  const stoppedCursor = result.pagination_stop_reason === "missing-cursor" || result.pagination_stop_reason === "stalled-cursor";
  const reason = stoppedCursor ? `pagination_${result.pagination_stop_reason}`
    : result.terminal_reason || (result.history_state === "exhausted" ? "history_exhausted_unverified" : null);
  if (!reason) return null;
  const retryAt = result.retry_at_ms;
  return { reason, retryAt: !stoppedCursor && typeof retryAt === "number" && Number.isFinite(retryAt) && retryAt > now
    ? retryAt : Number.POSITIVE_INFINITY };
}
