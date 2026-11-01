/** Native downloads bypass navigation, without granting arbitrary URL access. */
export function downloadReplayPortfolio(sender, backendPort, runId) {
  if (!Number.isInteger(backendPort) || backendPort < 1 || backendPort > 65535) {
    throw new TypeError("Replay download backend is unavailable");
  }
  if (typeof runId !== "string" || runId.length < 1 || runId.length > 128
    || !/^[A-Za-z0-9]/.test(runId) || /[^A-Za-z0-9._:-]/.test(runId)) {
    throw new TypeError("Replay download run id is invalid");
  }
  if (sender.isDestroyed()) throw new Error("Replay download window is closed");
  const url = `http://127.0.0.1:${backendPort}/api/v1/replay/runs/${encodeURIComponent(runId)}/portfolio-equity/export`;
  sender.downloadURL(url);
  return { started: true };
}
