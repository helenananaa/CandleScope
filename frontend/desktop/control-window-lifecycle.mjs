/** Sandboxed indicator frames navigate independently of the trusted document. */
export function trackControlWindowLifecycle(contents, disconnect) {
  contents.on("did-start-navigation", (_event, _url, isInPlace, isMainFrame) => {
    if (isMainFrame && !isInPlace) disconnect();
  });
  contents.once("destroyed", disconnect);
}
