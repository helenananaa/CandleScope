import type { TransportKlineResponse } from "../../../services/apiPayloadParsers.js";
import type { HistoryAvailabilityState, HistoryExcludedRange, HistoryMissingRange, KlineFetchResult } from "../klineContracts.js";
import { toEpochSeconds, type KlineBar } from "../marketDataTypes.js";
import type { KlineEndpoint } from "../quality/klineQualityPolicy.js";

function optionalBoolean(value: unknown, field: string): boolean | undefined {
  if (value === undefined) return undefined;
  if (typeof value !== "boolean") throw new TypeError(`${field} must be a boolean`);
  return value;
}

function optionalNullableString(value: unknown, field: string): string | null | undefined {
  if (value === undefined) return undefined;
  if (value === null) return null;
  if (typeof value !== "string") throw new TypeError(`${field} must be a string or null`);
  return value;
}

function optionalNullableNonNegativeNumber(
  value: unknown,
  field: string,
): number | null | undefined {
  if (value === undefined) return undefined;
  if (value === null) return null;
  if (typeof value !== "number" || !Number.isFinite(value) || value < 0) {
    throw new TypeError(`${field} must be a non-negative finite number or null`);
  }
  return value;
}

function optionalHistoryState(value: unknown): HistoryAvailabilityState | undefined {
  if (value === undefined) return undefined;
  if (value === "ready" || value === "pending" || value === "exhausted") return value;
  throw new TypeError("history_state must be ready, pending, or exhausted");
}

function optionalExcludedRanges(value: unknown): HistoryExcludedRange[] | undefined {
  if (value === undefined) return undefined;
  if (!Array.isArray(value)) throw new TypeError("excluded_ranges must be an array");
  return value.map((item, index) => {
    if (!item || typeof item !== "object" || Array.isArray(item)) {
      throw new TypeError(`excluded_ranges[${index}] must be an object`);
    }
    const record = item as Record<string, unknown>;
    const startMs = optionalNullableNonNegativeNumber(
      record.start_ms,
      `excluded_ranges[${index}].start_ms`,
    );
    const endMs = optionalNullableNonNegativeNumber(
      record.end_ms,
      `excluded_ranges[${index}].end_ms`,
    );
    if (startMs == null || endMs == null || endMs < startMs) {
      throw new TypeError(`excluded_ranges[${index}] must contain a valid start_ms/end_ms range`);
    }
    const reason = optionalNullableString(record.reason, `excluded_ranges[${index}].reason`);
    const retryAtMs = optionalNullableNonNegativeNumber(
      record.retry_at_ms,
      `excluded_ranges[${index}].retry_at_ms`,
    );
    return {
      ...record,
      start_ms: startMs,
      end_ms: endMs,
      ...(reason == null ? {} : { reason }),
      ...(retryAtMs === undefined ? {} : { retry_at_ms: retryAtMs }),
    };
  });
}

function optionalMissingRanges(value: unknown): HistoryMissingRange[] | undefined {
  if (value === undefined) return undefined;
  if (!Array.isArray(value)) throw new TypeError("missing_ranges must be an array");
  return value.map((item, index) => {
    if (!item || typeof item !== "object" || Array.isArray(item)) {
      throw new TypeError(`missing_ranges[${index}] must be an object`);
    }
    const record = item as Record<string, unknown>;
    const startMs = optionalNullableNonNegativeNumber(
      record.start_ms,
      `missing_ranges[${index}].start_ms`,
    );
    const endMs = optionalNullableNonNegativeNumber(
      record.end_ms,
      `missing_ranges[${index}].end_ms`,
    );
    if (startMs == null || endMs == null || endMs < startMs) {
      throw new TypeError(`missing_ranges[${index}] must contain a valid start_ms/end_ms range`);
    }
    const reason = optionalNullableString(record.reason, `missing_ranges[${index}].reason`);
    return {
      ...record,
      start_ms: startMs,
      end_ms: endMs,
      ...(reason == null ? {} : { reason }),
    };
  });
}

export function decodeKlineResult(result: TransportKlineResponse, endpoint: KlineEndpoint): KlineFetchResult {
  // Absence means unknown; an explicitly malformed proof is not absence.
  for (const field of ["all_rows_final", "has_tail_gap", "truncated", "has_more"] as const) {
    optionalBoolean(result[field], field);
  }
  const data: KlineBar[] = result.data.map((row) => {
    const time = toEpochSeconds(row.time);
    if (time === null) throw new TypeError("Validated kline time could not be converted to EpochSeconds");
    return { ...row, time };
  });
  const historyState = optionalHistoryState(result.history_state);
  const complete = optionalBoolean(result.complete, "complete");
  const retryable = optionalBoolean(result.retryable, "retryable");
  const terminalReason = optionalNullableString(result.terminal_reason, "terminal_reason");
  const earliestAvailableMs = optionalNullableNonNegativeNumber(
    result.earliest_available_ms,
    "earliest_available_ms",
  );
  const nextBeforeMs = optionalNullableNonNegativeNumber(result.next_before_ms, "next_before_ms");
  const availabilityRevision = optionalNullableString(
    result.availability_revision,
    "availability_revision",
  );
  const retryAtMs = optionalNullableNonNegativeNumber(result.retry_at_ms, "retry_at_ms");
  const excludedRanges = optionalExcludedRanges(result.excluded_ranges);
  const missingRanges = optionalMissingRanges(result.missing_ranges);
  const verifiedContiguous = optionalBoolean(result.verified_contiguous, "verified_contiguous");
  return {
    ...result,
    endpoint,
    data,
    ...(historyState === undefined ? {} : { history_state: historyState }),
    ...(complete === undefined ? {} : { complete }),
    ...(retryable === undefined ? {} : { retryable }),
    ...(terminalReason === undefined ? {} : { terminal_reason: terminalReason }),
    ...(earliestAvailableMs === undefined ? {} : { earliest_available_ms: earliestAvailableMs }),
    ...(nextBeforeMs === undefined ? {} : { next_before_ms: nextBeforeMs }),
    ...(availabilityRevision === undefined ? {} : { availability_revision: availabilityRevision }),
    ...(retryAtMs === undefined ? {} : { retry_at_ms: retryAtMs }),
    ...(excludedRanges === undefined ? {} : { excluded_ranges: excludedRanges }),
    ...(missingRanges === undefined ? {} : { missing_ranges: missingRanges }),
    ...(verifiedContiguous === undefined ? {} : { verified_contiguous: verifiedContiguous }),
  };
}

