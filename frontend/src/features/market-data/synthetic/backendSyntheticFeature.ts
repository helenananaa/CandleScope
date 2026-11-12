/** Candidate rollout. Enable only in a backend-matched acceptance build. */
export function resolveBackendSyntheticEnabled(value: unknown): boolean {
  return value === true || value === 1 || value === "1";
}

export const BACKEND_SYNTHETIC_SERIES_ENABLED = resolveBackendSyntheticEnabled(
  import.meta.env?.VITE_BACKEND_SYNTHETIC_SERIES,
);
