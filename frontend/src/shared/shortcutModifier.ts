/** The UI hints match handlers that accept either Ctrl or Meta. */
export function shortcutModifier(platform = typeof navigator === "undefined" ? "" : navigator.platform): string {
  return /Mac|iPhone|iPad|iPod/.test(platform) ? "⌘" : "Ctrl";
}
