// Contract fixture only: lifecycle/IPC integration is a later delivery.
export function activate(context) {
  context.track(() => {});
}
