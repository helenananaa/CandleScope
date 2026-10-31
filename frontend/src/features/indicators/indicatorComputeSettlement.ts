/** Publish independent successes before reporting a sibling's failure. A
 * fail-fast aggregate would permanently mark unfinished browser scripts with
 * an unrelated HTTP error. Cancellation still belongs to each job's signal. */
export async function awaitIndicatorComputations<T extends readonly unknown[]>(pending: T) {
  await Promise.allSettled(pending);
  return Promise.all(pending);
}
