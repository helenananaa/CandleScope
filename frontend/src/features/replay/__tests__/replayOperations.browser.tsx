import { StrictMode, act, useEffect, useLayoutEffect } from "react";
import { createRoot } from "react-dom/client";
import { ReplayDataProvider } from "../ReplayDataProvider.js";
import { useReplayOperations } from "../useReplayOperations.js";
import { useReplayDataManager } from "../replayDataContext.js";
import type { ReplayDataManager, ReplayOperationLease } from "../replayDataManager.js";

const assert = (condition: unknown, message: string) => { if (!condition) throw new Error(message); };

export async function checkReplayRunOperations() {
  const host = document.createElement("div"); document.body.append(host);
  const root = createRoot(host);
  let manager: ReplayDataManager | null = null, lease: ReplayOperationLease | null = null;
  const pending: Array<{ signal: AbortSignal; complete(value: number): void }> = [];
  const frames: Array<() => void> = [];
  let stopped = 0, publications = 0, cancellations = 0, received = 0;
  function Probe({ runId, sessionId }: { runId: string; sessionId: string }) {
    const { operations } = useReplayOperations(runId, "viewer");
    const rootManager = useReplayDataManager();
    useLayoutEffect(() => { lease = operations; manager = rootManager!.replay; });
    useEffect(() => {
      void operations.request(signal => new Promise<number>(complete => { pending.push({ signal, complete }); }))
        .then(() => { publications++; }, (error: unknown) => {
          if (error instanceof DOMException && error.name === "AbortError") cancellations++;
          else throw error;
        });
      const stream = operations.openResource(current => {
        frames.push(() => { if (current()) received++; });
        return {};
      }, () => { stopped++; });
      return () => stream.release();
    }, [operations]);
    return <span>{sessionId}</span>;
  }
  const render = (runId: string, sessionId: string) => root.render(
    <StrictMode><ReplayDataProvider><Probe runId={runId} sessionId={sessionId} /></ReplayDataProvider></StrictMode>,
  );
  try {
    await act(async () => render("run-a", "adapter-a"));
    const activeManager = manager as ReplayDataManager | null;
    assert(activeManager !== null, "provider did not create the manager");
    assert(activeManager!.diagnostics().activeOperations === 1 && activeManager!.diagnostics().streams === 1,
      "StrictMode retained a duplicate operation/stream");
    const original = lease, count = pending.length;
    await act(async () => render("run-a", "adapter-b"));
    assert(lease === original && pending.length === count && !pending.at(-1)!.signal.aborted,
      "selecting another chart canceled the run's in-flight command");
    await act(async () => render("run-b", "adapter-c"));
    assert(lease !== original && pending[count - 1]!.signal.aborted, "run change failed to cancel old work");
    await act(async () => {
      for (const item of pending.slice(0, -1)) item.complete(1);
      frames.forEach(frame => frame());
    });
    assert(publications === 0 && received === 1, "old run/StrictMode work published after release");
    await act(async () => pending.at(-1)!.complete(2));
    assert(publications === 1, "current run could not publish");
    await act(async () => root.unmount());
    frames.forEach(frame => frame());
    assert(received === 1 && activeManager!.diagnostics().activeOperations === 0,
      "final unmount retained callbacks or manager entries");
    assert(!Object.hasOwn(window, "__CANDLESCOPE_REPLAY_DATA__"), "provider diagnostic handle leaked");
    return { name: "run operations survive chart selection and fence StrictMode/run change/unmount", status: "PASS",
      cancellations, stopped, publications, requests: pending.length };
  } finally { await act(async () => root.unmount()); host.remove(); }
}
