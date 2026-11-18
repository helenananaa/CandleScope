export function activate(context) {
  const onFocus = () => {};
  context.electron.app.on("browser-window-focus", onFocus);
  context.track(() => context.electron.app.removeListener("browser-window-focus", onFocus));
}
