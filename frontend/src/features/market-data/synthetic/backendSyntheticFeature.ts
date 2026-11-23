/** Backend computation is the default; 0 is an explicit rollout rollback. */
export function resolveBackendSyntheticEnabled(value: unknown): boolean {
  return value === undefined || value === true || value === 1 || value === "1";
}

export const BACKEND_SYNTHETIC_SERIES_ENABLED = resolveBackendSyntheticEnabled(
  import.meta.env?.VITE_BACKEND_SYNTHETIC_SERIES,
);
