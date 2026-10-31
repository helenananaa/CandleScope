import { useEffect, useId, useState } from "react";
import { useControlCommands } from "../../app-control/useControlCommands.js";
import { command as controlCommand } from "../../app-control/commandRegistry.js";
import { choice, empty, number, object, text } from "../../app-control/commandSchema.js";
import { t } from "../../../i18n/index.js";
import { nativeApi, type NativeResult } from "./nativeBacktestApi.js";
import { pollNativeReplay } from "./nativeReplayPolling.js";

export interface NativeReplayRecord {
  replay_id: string;
  run_id: string;
  state: string;
  method?: string;
  revision: number;
  cursor: number;
  total: number;
  result: NativeResult | null;
  snapshots: Array<{ snapshot_id: string; cursor: number }>;
  error: { message: string } | null;
}

export function NativeReplayControls({ runId, replay, onChange, hostAccount = false }: {
  runId: string; replay: NativeReplayRecord | null; onChange: (value: NativeReplayRecord | null) => void; hostAccount?: boolean;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [target, setTarget] = useState("0");
  const [history, setHistory] = useState<NativeReplayRecord[]>([]);
  useEffect(() => {
    const abort = new AbortController();
    void nativeApi<{ replays: NativeReplayRecord[] }>("/native/replays", undefined, undefined, abort.signal)
      .then((value) => setHistory(value.replays.filter((item) => item.run_id === runId)))
      .catch((reason) => { if (!abort.signal.aborted) setError(String(reason)); });
    return () => abort.abort();
  }, [runId]);
  useEffect(() => {
    if (!replay || replay.state !== "RUNNING") return;
    const abort = new AbortController();
    const timer = window.setTimeout(() => {
      void pollNativeReplay(replay, abort.signal)
        .then(onChange).catch((reason) => { if (!abort.signal.aborted) setError(String(reason)); });
    }, 500);
    return () => { window.clearTimeout(timer); abort.abort(); };
  }, [replay, onChange]);
  const command = async (action: string, extra: Record<string, unknown> = {}) => {
    setBusy(true); setError("");
    try {
      const value = await nativeApi<NativeReplayRecord>(replay ? `/native/replays/${replay.replay_id}/commands` : "/native/replays",
        replay ? { revision: replay.revision, action, ...extra } : { run_id: runId });
      onChange(value);
      setHistory((items) => [value, ...items.filter((item) => item.replay_id !== value.replay_id)]);
    } catch (reason) { setError(String(reason)); }
    finally { setBusy(false); }
  };
  const running = replay?.state === "RUNNING";
  const controlId = useId();
  useControlCommands(() => ({ id: `native-replay:${controlId}`, title: "Native strategy incremental replay", context: () => ({ runId, replayId: replay?.replay_id, revision: replay?.revision, busy }),
    snapshot: () => ({ runId, replay: replay ? { ...replay, result: undefined } : null, history: history.map(({ result, ...item }) => { void result; return item; }), busy, error, target }), commands: [
      controlCommand("create", "Create a native replay through the existing domain service.", empty, () => command("create"), { available: () => !replay && !busy }),
      controlCommand("advance", "Step or play the revision-bound replay.", object({ action: choice(["step", "play"]) }), ({ action }) => command(action), { available: () => !!replay && !busy && !running && replay.cursor < replay.total }),
      controlCommand("pause", "Pause the running replay.", empty, () => command("pause"), { available: () => !busy && !!running, interrupt: true }),
      controlCommand("snapshot", "Create a domain snapshot while paused.", empty, () => command("snapshot"), { available: () => !!replay && !busy && !running }),
      controlCommand("seek", "Seek within this replay's visible total.", object({ target: number(0, 1e9, true) }), ({ target }) => { if (!replay || target > replay.total) throw new Error("REPLAY_TARGET_INVALID"); setTarget(String(target)); return command("seek", { target }); }, { available: () => !!replay && !busy && !running }),
      controlCommand("restore", "Restore a listed replay snapshot.", object({ snapshotId: text(128) }), ({ snapshotId }) => { if (!replay?.snapshots.some((item) => item.snapshot_id === snapshotId)) throw new Error("SNAPSHOT_UNAVAILABLE"); return command("restore", { snapshot_id: snapshotId }); }, { available: () => !!replay && !busy && !running }),
      controlCommand("batch", "Return to the completed batch report.", empty, () => onChange(null), { available: () => !running && !busy }),
      controlCommand("resume", "Open a listed replay of this run.", object({ replayId: text(128) }), async ({ replayId }) => { if (!history.some((item) => item.replay_id === replayId)) throw new Error("REPLAY_UNAVAILABLE"); onChange(await nativeApi<NativeReplayRecord>(`/native/replays/${replayId}`)); }, { available: () => !replay && !busy }),
    ] }));
  const title = t(hostAccount || replay?.method === "HOST_ACCOUNT_CHECKPOINT" ? "report.replay" : "native.replay.title");
  return <section className="native-replay-controls" aria-label={title}>
    <strong>{title}</strong>
    {replay && <p>{t(replay.method === "HOST_ACCOUNT_CHECKPOINT" ? "native.replay.host" : replay.method === "FIXED_HORIZON_INCREMENTAL" ? "native.replay.incremental" : "native.replay.method")}</p>}
    {!replay ? <button disabled={busy} onClick={() => void command("create")}>{t("native.replay.start")}</button> : <>
      <p role="status">{replay.cursor} / {replay.total} · {replay.state}</p>
      <div className="native-toolbar">
        <button disabled={busy || running || replay.cursor >= replay.total} onClick={() => void command("step")}>{t("native.replay.step")}</button>
        <button disabled={busy || running || replay.cursor >= replay.total} onClick={() => void command("play")}>{t("native.replay.play")}</button>
        <button disabled={busy || !running} onClick={() => void command("pause")}>{t("native.replay.pause")}</button>
        <button disabled={busy || running} onClick={() => void command("snapshot")}>{t("native.replay.snapshot")}</button>
        <input type="number" min="0" max={replay.total} value={target} aria-label={t("native.replay.cursor")} onChange={(event) => setTarget(event.target.value)} />
        <button disabled={busy || running || !Number.isInteger(Number(target)) || Number(target) < 0 || Number(target) > replay.total} onClick={() => void command("seek", { target: Number(target) })}>{t("native.replay.seek")}</button>
        <button disabled={running || busy} onClick={() => onChange(null)}>{t("native.replay.batch")}</button>
      </div>
      {replay.snapshots.map((item) => <button key={item.snapshot_id} disabled={running || busy} onClick={() => void command("restore", { snapshot_id: item.snapshot_id })}>
        {t("native.replay.restore")} · {item.cursor}
      </button>)}
      {replay.error && <p role="alert">{replay.error.message}</p>}
    </>}
    {!replay && history.map((item) => <button key={item.replay_id} disabled={busy} onClick={() => {
      void nativeApi<NativeReplayRecord>(`/native/replays/${item.replay_id}`).then(onChange).catch((reason) => setError(String(reason)));
    }}>{t("native.replay.resume")} · {item.cursor} / {item.total}</button>)}
    {error && <p role="alert">{error}</p>}
  </section>;
}
