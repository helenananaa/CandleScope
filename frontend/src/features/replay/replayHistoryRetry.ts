/** Retry an explicitly temporary source failure or cache admission pressure.
 * Corrupt/missing revisions and undeclared gaps remain immediate errors.
 */
export function replayHistoryRetryDelay(error: unknown, attempt: number, delays: readonly number[]): number | undefined {
  if (!error || typeof error !== "object" || !("code" in error)) return undefined;
  if (error.code === "HISTORY_DOWNLOAD_PENDING") return delays[attempt];
  const temporarySource = error.code === "HISTORY_SOURCE_UNAVAILABLE" || error.code === "HISTORY_CACHE_BUSY";
  if (!temporarySource || attempt >= 2 || !("details" in error)) return undefined;
  const details = error.details;
  return details && typeof details === "object" && "retryable" in details && details.retryable === true
    ? delays[attempt] : undefined;
}
