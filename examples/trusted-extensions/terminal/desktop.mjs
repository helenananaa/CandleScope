export function activate(context) {
  const { app } = context.electron;
  // A native app lifecycle hook; owned listeners are removed on shutdown.
  const onActivate = () => { context.host.manager?.diagnostics?.(); };
  app.on("activate", onActivate);
  context.track(() => app.removeListener("activate", onActivate));
}
