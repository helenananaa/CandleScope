// Contract fixture only: the production host does not load unified packages yet.
export function activate(context) {
  context.track(() => {});
}
