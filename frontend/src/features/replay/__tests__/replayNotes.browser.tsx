import { createRoot } from "react-dom/client";
import { flushSync } from "react-dom";
import ReplayNotesPanel from "../components/ReplayNotesPanel.js";
import { ReplayV2ApiClient } from "../replayV2Api.js";
import { ReplayDataManager } from "../replayDataManager.js";
import { managedReplayRunApi } from "../managedReplayTransport.js";
import { setLocale } from "../../../i18n/index.js";
import type { ReplayNoteContext } from "../replayNotes.js";

const assert = (value: unknown, message: string) => { if (!value) throw new Error(message); };
async function until(check: () => unknown, timeout = 10_000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) { const result = check(); if (result) return result; await new Promise(resolve => setTimeout(resolve, 20)); }
  throw new Error("Replay note browser fixture timed out");
}
interface State { pid: number; context: ReplayNoteContext; snapshot: unknown; network: { blocked_attempts: number } }

export async function checkReplayNotesBrowser() {
  setLocale("zh-CN");
  const backend = new URL(new URLSearchParams(location.search).get("backend") ?? "");
  assert(backend.hostname === "127.0.0.1", "Only an explicit loopback fixture backend is permitted");
  const call = async (path: string, method = "GET"): Promise<State> => {
    const response = await fetch(new URL(path, backend), { method });
    assert(response.ok, "Fixture backend failed: " + response.status); return await response.json() as State;
  };
  let state = await call("/fixture/state");
  const manager = new ReplayDataManager();
  const lease = manager.createOperations({ runId: state.context.runId, purpose: "review" });
  const release = lease.retain();
  let loseNextNoteReply = false;
  const api = managedReplayRunApi(lease, new ReplayV2ApiClient({ basePath: new URL("/api/v1/replay", backend).href,
    fetcher: async (url, options) => {
      const response = await fetch(url, options);
      if (loseNextNoteReply && options?.method === "POST" && String(url).endsWith("/notes")) {
        loseNextNoteReply = false;
        assert(response.ok, "Uncertain submission was not committed by the real backend");
        await response.text(); // Discard an actual committed response, keeping the product editor unchanged.
        throw new TypeError("QA controlled loss after authoritative HTTP commit");
      }
      return response;
    } }));
  const host = document.createElement("main"); host.style.cssText = "width:420px;margin:30px;"; document.body.append(host);
  let root = createRoot(host);
  const render = () => flushSync(() => root.render(<ReplayNotesPanel api={api} runId={state.context.runId}
    trackId={state.context.trackId} generationKey={state.context.dataEpoch} reviewId={state.context.reviewId}
    reviewRevision={state.context.reviewRevision} cursorMs={state.context.virtualTimeMs}
    revisionKey={JSON.stringify(state.context)} formatTime={time => String(time)} embedded />));
  const button = (name: string) => [...host.querySelectorAll<HTMLButtonElement>("button")].find(value => value.textContent === name);
  const click = async (name: string) => { await until(() => button(name) && !button(name)!.disabled); button(name)!.click(); };
  const input = async (text: string) => {
    await until(() => host.querySelector("textarea"));
    const area = host.querySelector("textarea")!;
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!;
    setter.call(area, text); area.dispatchEvent(new Event("input", { bubbles: true }));
    await until(() => area.value === text);
  };
  const checks: string[] = [];
  const capture = async (name: string) => {
    const target = window as Window & { __replayNoteCapture?: string | null };
    target.__replayNoteCapture = name;
    await until(() => target.__replayNoteCapture === null, 20_000);
  };
  try {
    render(); await click("新增笔记"); await input("事前计划，保存不改变运行"); await capture("original-editor"); await click("保存并关闭");
    await until(() => !host.querySelector("textarea") && host.textContent?.includes("事前计划，保存不改变运行"));
    const saved = await call("/fixture/state");
    assert(JSON.stringify(saved.snapshot) === JSON.stringify(state.snapshot), "Note save changed the replay/financial snapshot");
    checks.push("actual UI note save traversed parsed HTTP/manager/SQLite without changing snapshot");
    state = await call("/fixture/marker", "POST"); render();
    await click("编辑"); await input("同一毫秒后一个事件修改的计划"); await click("保存并关闭");
    await until(() => !host.querySelector("textarea") && host.textContent?.includes("同一毫秒后一个事件修改的计划"));
    state = await call("/fixture/advance", "POST"); render();
    await click("新增笔记"); await input("未来创建的笔记"); await click("保存并关闭");
    await until(() => !host.querySelector("textarea") && host.textContent?.includes("未来创建的笔记"));
    await click("新增笔记"); await input("未来未保存草稿");
    await until(() => Object.keys(localStorage).some(key => key.startsWith("candlescope.replay-note-draft.v1:")));
    state = await call("/fixture/review-first", "POST"); render();
    await until(() => host.textContent?.includes("事前计划，保存不改变运行") && !host.querySelector("textarea"));
    for (const text of ["同一毫秒后一个事件修改的计划", "未来创建的笔记", "未来未保存草稿"])
      assert(!host.textContent?.includes(text), "Backward UI leaked future text: " + text);
    await capture("earlier-event-visible-original");
    checks.push("earlier event hides same-time edits, future creation and future draft text");
    const before = await call("/fixture/state");
    await click("新增复盘补记"); await input("回退后的补记，保留实际写入时间"); await click("保存并关闭");
    await until(() => !host.querySelector("textarea") && host.textContent?.includes("回退后的补记，保留实际写入时间"));
    assert(host.textContent?.includes("复盘补记") && host.textContent?.includes("实际保存时间"), "Supplement timing/label missing");
    const after = await call("/fixture/state");
    assert(JSON.stringify(before.snapshot) === JSON.stringify(after.snapshot), "Review note changed live account/cursor");
    assert(after.network.blocked_attempts === 0, "A public network attempt was made by the controlled backend");
    await capture("review-supplement");
    checks.push("review UI supplement remains separate from original plan and financial state");

    await click("新增复盘补记"); await input("已提交但响应丢失的笔记");
    loseNextNoteReply = true; await click("保存");
    await until(() => host.querySelector('[role="alert"]'));
    const authoritative = await api.notesRun(state.context.runId, state.context.trackId, state.context.virtualTimeMs);
    const uncertain = authoritative.notes.find(note => note.fields.entryBasis === "已提交但响应丢失的笔记");
    assert(uncertain?.revisionCount === 1, "Lost response was not authoritatively stored");
    root.unmount(); root = createRoot(host); render();
    await until(() => [...host.querySelectorAll<HTMLButtonElement>("button")].some(value => value.textContent?.startsWith("恢复草稿")));
    [...host.querySelectorAll<HTMLButtonElement>("button")].find(value => value.textContent?.startsWith("恢复草稿"))!.click();
    await until(() => host.querySelector("textarea")?.value === "已提交但响应丢失的笔记");
    await click("保存并关闭"); await until(() => !host.querySelector("textarea"));
    const retried = await api.notesRun(state.context.runId, state.context.trackId, state.context.virtualTimeMs);
    assert(retried.notes.length === authoritative.notes.length && retried.notes.find(note => note.id === uncertain!.id)?.revisionCount === 1,
      "Uncertain retry duplicated or advanced the saved version");
    checks.push("real committed HTTP response loss retains original draft and remounted editor retries the same version exactly once");

    await click("新增复盘补记"); await input("显式另存的旧视图草稿");
    const sourceKey = Object.keys(localStorage).find(key => key.startsWith("candlescope.replay-note-draft.v1:")
      && localStorage.getItem(key)?.includes("显式另存的旧视图草稿"));
    assert(sourceKey, "Original draft was not persisted");
    const sourceDraft = localStorage.getItem(sourceKey!);
    state = await call("/fixture/review-last", "POST"); render();
    await click("另存为当前时刻的新笔记"); await until(() => host.querySelector("textarea")?.value === "显式另存的旧视图草稿");
    await click("保存并关闭"); await until(() => !host.querySelector("textarea"));
    const copied = await api.notesRun(state.context.runId, state.context.trackId, state.context.virtualTimeMs);
    const copiedNote = copied.notes.find(note => note.fields.entryBasis === "显式另存的旧视图草稿");
    assert(copiedNote?.reviewNote && copiedNote.marketTimeMs === state.context.virtualTimeMs,
      "Explicit copy did not become a new current-time review supplement");
    assert(localStorage.getItem(sourceKey!) === sourceDraft, "Explicit copy erased the original recovery data");
    checks.push("explicit current-time copy is a new review supplement and preserves the old-context draft");
    const final = await call("/fixture/state");
    assert(JSON.stringify(final.snapshot) === JSON.stringify(before.snapshot), "Retry/copy changed live financial state");
    assert(final.network.blocked_attempts === 0, "Recovery attempted an external connection");
    await capture("recovered-review-notes");
    root.unmount(); release(); manager.dispose(); host.remove();
    assert(manager.diagnostics().requests === 0 && manager.diagnostics().activeOperations === 0, "Note view leaked manager ownership");
    return { status: "PASS", scope: "Production React + actual loopback router/SQLite with explicit fixture candles; not native acceptance",
      checks, backendPid: final.pid, blockedExternalAttempts: final.network.blocked_attempts };
  } finally { root.unmount(); release(); manager.dispose(); host.remove(); }
}
