export function activate(host) {
  const h = host.React.createElement;
  function TopBar({ fallback }) {
    return h("div", { className: "terminal-extension-header" },
      h("div", { className: "terminal-extension-label" }, "CANDLE / TERMINAL", h("span", null, "WORKSPACE ONLINE")),
      fallback);
  }
  host.ui.replaceSlot("topBar", TopBar);
  host.ui.stylesheet(`
    .terminal-extension-header { flex-shrink:0; }
    .terminal-extension-label { display:flex; justify-content:space-between; padding:7px 14px; background:var(--bg-tertiary); color:var(--accent-blue); font:11px var(--font-mono); letter-spacing:2px; border-bottom:1px solid var(--border-color); }
    .terminal-extension-label span { font-size:9px; opacity:.65; }
    .app-layout button { border-radius:0; }
  `);
  host.commands.register("workspace", () => host.services.get("workspace").view);
  host.services.register("status", { mode: "terminal", version: "1.0.0" });
}
