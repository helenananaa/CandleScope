import { useSyncExternalStore } from "react";

/**
 * Phone layout: a window narrower than this is a phone held upright, where the header takes two
 * rows, side rails become bars along the bottom and their panels open as sheets above them. Keep
 * this width in step with the `@media (max-width: 640px)` blocks in the stylesheets.
 */
export const PHONE_LAYOUT_QUERY = "(max-width: 640px)";

function phoneQuery(): MediaQueryList | null {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    ? window.matchMedia(PHONE_LAYOUT_QUERY)
    : null;
}

export function isPhoneLayout(): boolean {
  return phoneQuery()?.matches ?? false;
}

function subscribe(onChange: () => void): () => void {
  const query = phoneQuery();
  if (!query) return () => undefined;
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

export function usePhoneLayout(): boolean {
  return useSyncExternalStore(subscribe, isPhoneLayout, isPhoneLayout);
}
