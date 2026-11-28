import { useEffect, useRef } from "react";

/** Alt+G, outside text fields and dialogs: the Go to date shortcut. */
export function isGoToDateShortcut(event: Pick<KeyboardEvent, "defaultPrevented" | "repeat" | "isComposing"
  | "altKey" | "ctrlKey" | "metaKey" | "shiftKey" | "code" | "target">): boolean {
  if (event.defaultPrevented || event.repeat || event.isComposing || !event.altKey
    || event.ctrlKey || event.metaKey || event.shiftKey || event.code !== "KeyG") return false;
  const element = typeof Element !== "undefined" && event.target instanceof Element ? event.target : null;
  return !element?.closest("input,textarea,select,[contenteditable=true],[role=dialog]");
}

/** Opens Go to date on Alt+G while `enabled`; shared by chart cells and the replays. */
export function useGoToDateHotkey(enabled: boolean, open: () => void): void {
  const latest = useRef(open);
  useEffect(() => { latest.current = open; });
  useEffect(() => {
    if (!enabled) return undefined;
    const keydown = (event: KeyboardEvent) => {
      if (!isGoToDateShortcut(event)) return;
      event.preventDefault();
      latest.current();
    };
    window.addEventListener("keydown", keydown);
    return () => window.removeEventListener("keydown", keydown);
  }, [enabled]);
}
