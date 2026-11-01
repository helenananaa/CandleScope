interface NativePortfolioDownloader {
  downloadReplayPortfolio?(runId: string): Promise<{ started: true }>;
}

/** Browser anchors stream directly; the native shell owns its restricted download. */
export function requestNativePortfolioDownload(
  runId: string,
  bridge: NativePortfolioDownloader | undefined = globalThis.window?.candlescopeDesktop,
): Promise<{ started: true }> | null {
  const download = bridge?.downloadReplayPortfolio;
  return download ? Promise.resolve().then(() => download.call(bridge, runId)) : null;
}
