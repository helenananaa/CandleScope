/** Retry an explicitly temporary source failure without replacing its identity.
 * Corrupt/missing revisions and undeclared gaps remain immediate errors.
 */
export function replayHistoryRetryDelay(error: unknown, attempt: number, delays: readonly number[]): number | undefined {
  if (!error || typeof error !== "object" || !("code" in error)) return undefined;
  if (error.code === "HISTORY_DOWNLOAD_PENDING") return delays[attempt];
  if (error.code !== "HISTORY_SOURCE_UNAVAILABLE" || attempt >= 2 || !("details" in error)) return undefined;
  const details = error.details;
  return details && typeof details === "object" && "retryable" in details && details.retryable === true
    ? delays[attempt] : undefined;
}
