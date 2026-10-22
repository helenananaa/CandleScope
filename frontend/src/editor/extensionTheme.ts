import { useSyncExternalStore } from "react";
import type * as Monaco from "monaco-editor";
import { getExtensionState, subscribeExtensions } from "../features/extensions/state.js";

const registered = new WeakSet<typeof Monaco>();
export function bindExtensionEditorTheme(monaco: typeof Monaco): void {
  if (registered.has(monaco)) return;
  registered.add(monaco);
  const update = () => {
    const theme = getExtensionState().theme;
    monaco.editor.defineTheme("candlescope-extension", {
      base: theme?.base === "light" ? "vs" : "vs-dark", inherit: true, rules: [],
      colors: theme ? {
        ...(theme.tokens["bg-primary"] ? { "editor.background": theme.tokens["bg-primary"] } : {}),
        ...(theme.tokens["text-primary"] ? { "editor.foreground": theme.tokens["text-primary"] } : {}),
        ...(theme.tokens["text-muted"] ? { "editorLineNumber.foreground": theme.tokens["text-muted"] } : {}),
        ...(theme.tokens["accent-blue"] ? { "editorCursor.foreground": theme.tokens["accent-blue"] } : {}),
      } : {},
    });
    if (theme) monaco.editor.setTheme("candlescope-extension");
  };
  update();
  subscribeExtensions(update);
}

export function useExtensionEditorTheme(fallback: string): string {
  const theme = useSyncExternalStore(subscribeExtensions, () => getExtensionState().theme, () => null);
  return theme ? "candlescope-extension" : fallback;
}
