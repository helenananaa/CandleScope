import { createRoot } from "react-dom/client";
import { flushSync } from "react-dom";
import { captureReplayNoteChart } from "../replayNoteChartCapture.js";
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
  let loseNextCaptureReply = false, failNextCaptureBeforeSend = false;
  const captureSubmissions = new Map<string, string>();
  let holdNextHistory = false;
  let releaseHistory: (() => void) | null = null;
  const api = managedReplayRunApi(lease, new ReplayV2ApiClient({ basePath: new URL("/api/v1/replay", backend).href,
    fetcher: async (url, options) => {
      const pathname = new URL(String(url), backend).pathname;
      const isCapture = options?.method === "POST" && pathname.endsWith("/note-captures");
      if (isCapture) {
        const body = JSON.parse(String(options.body)) as { id: string; image: string };
        captureSubmissions.set(body.id, body.image);
        if (failNextCaptureBeforeSend) { failNextCaptureBeforeSend = false; throw new TypeError("QA controlled failure before PNG upload"); }
      }
      const response = await fetch(url, options);
      if (isCapture && loseNextCaptureReply) {
        loseNextCaptureReply = false; assert(response.ok, "PNG was not committed before its reply was lost");
        await response.text(); throw new TypeError("QA loss after actual immutable PNG commit");
      }
      if (loseNextNoteReply && options?.method === "POST" && pathname.endsWith("/notes")) {
        loseNextNoteReply = false;
        assert(response.ok, "Uncertain submission was not committed by the real backend");
        await response.text(); // Discard an actual committed response, keeping the product editor unchanged.
        throw new TypeError("QA controlled loss after authoritative HTTP commit");
      }
      if (holdNextHistory && String(url).includes("/versions?")) {
        holdNextHistory = false;
        const text = await response.text();
        // Let the production manager/body parser own cancellation after actual HTTP completed.
        const delayed = new Response(null, { status: response.status });
        delayed.text = () => new Promise(resolve => { releaseHistory = () => resolve(text); });
        return delayed;
      }
      return response;
    } }));
  const chartHost = document.createElement("div"); chartHost.style.cssText = "width:400px;height:180px;margin:30px;";
  const canvas = document.createElement("canvas"); canvas.width = 400; canvas.height = 180; canvas.style.cssText = "display:block;width:400px;height:180px";
  chartHost.append(canvas); document.body.append(chartHost);
  const draw = () => { const paint = canvas.getContext("2d")!;
    paint.fillStyle = `rgb(${state.context.timelineSequence * 31 % 255},40,100)`; paint.fillRect(0,0,400,180);
    paint.fillStyle = "white"; paint.fillText(`Explicit fixture canvas event ${state.context.timelineSequence}`, 10, 50);
  };
  const captureChart = async (context: ReplayNoteContext) => captureReplayNoteChart({ prepareExport: async () => null,
    getExportSnapshot: () => ({ rootElement: chartHost, sourceWindow: { seriesKey: "explicit-loopback-fixture", version: state.context.timelineSequence, current: true } }) },
    context, () => ({ ready: true, seriesKey: "explicit-loopback-fixture", sourceVersion: state.context.timelineSequence, interval: "1m", chartType: "candles",
      contextKey: JSON.stringify(state.context) }));
  const host = document.createElement("main"); host.style.cssText = "width:420px;margin:30px;"; document.body.append(host);
  let root = createRoot(host);
  const render = () => { draw(); flushSync(() => root.render(<ReplayNotesPanel api={api} runId={state.context.runId}
    trackId={state.context.trackId} generationKey={state.context.dataEpoch} reviewId={state.context.reviewId}
    reviewRevision={state.context.reviewRevision} cursorMs={state.context.virtualTimeMs}
    revisionKey={JSON.stringify(state.context)} formatTime={time => String(time)} captureChart={captureChart} embedded />)); };
  const button = (name: string) => [...host.querySelectorAll<HTMLButtonElement>("button")].find(value => value.textContent === name || value.textContent?.startsWith(name + " ·"));
  let lastAction = "initial";
  const click = async (name: string) => { lastAction = name; await until(() => button(name) && !button(name)!.disabled); button(name)!.click(); };
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
    render(); await click("新增笔记"); await input("事前计划，保存不改变运行"); await capture("original-editor"); await click("截取当前图表"); await click("保存并关闭");
    await until(() => !host.querySelector("textarea") && host.textContent?.includes("事前计划，保存不改变运行"));
    const originalWithImage = await api.notesRun(state.context.runId, state.context.trackId, state.context.virtualTimeMs);
    const originalImage = originalWithImage.notes[0]!.screenshots![0]!;
    assert(originalImage, "Original note did not bind its PNG");
    const saved = await call("/fixture/state");
    assert(JSON.stringify(saved.snapshot) === JSON.stringify(state.snapshot), "Note save changed the replay/financial snapshot");
    checks.push("actual UI note save traversed parsed HTTP/manager/SQLite without changing snapshot");
    state = await call("/fixture/marker", "POST");
    state = await call("/fixture/buy", "POST"); render();
    await click("编辑"); await input("同一毫秒后一个事件修改的计划");
    await click("选择成交");
    await until(() => host.querySelector<HTMLInputElement>('input[type="checkbox"]'));
    host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click();
    await click("截取当前图表");
    await until(() => button("移除截图 2")); await click("移除截图 1");
    await click("保存并关闭");
    await until(() => !host.querySelector("textarea") && host.textContent?.includes("同一毫秒后一个事件修改的计划"));
    const currentWithImage = await api.notesRun(state.context.runId, state.context.trackId, state.context.virtualTimeMs);
    const updatedImage = currentWithImage.notes[0]!.screenshots![0]!;
    assert(updatedImage.id !== originalImage.id, "Editing reused the old screenshot instead of a new capture");
    const firstPixels = await api.noteScreenshotRun(state.context.runId, state.context.trackId, currentWithImage.notes[0]!.id, 1, originalImage.id);
    const laterPixels = await api.noteScreenshotRun(state.context.runId, state.context.trackId, currentWithImage.notes[0]!.id, 2, updatedImage.id);
    assert(firstPixels.image === captureSubmissions.get(originalImage.id) && laterPixels.image === captureSubmissions.get(updatedImage.id)
      && firstPixels.image !== laterPixels.image, "Version image bytes were replaced by another event's pixels");
    await click("查看截图 1");
    await until(() => host.querySelector<HTMLImageElement>('dialog img')?.naturalWidth === 400);
    await capture("current-version-screenshot");
    host.querySelector<HTMLDialogElement>('dialog')!.querySelector<HTMLButtonElement>('button')!.click();
    checks.push("actual PNG export/upload/view keeps different fixture canvas pixels bound to v1/v2");
    await click("版本历史");
    await until(() => host.querySelectorAll("[data-note-version]").length === 2);
    assert(host.querySelector('[data-note-version="1"]')?.textContent?.includes("事前计划，保存不改变运行"), "Original version is missing from history");
    state = await call("/fixture/close", "POST"); render();
    await click("编辑"); await click("选择交易");
    await until(() => host.querySelector<HTMLInputElement>('input[type="checkbox"]'));
    host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click();
    await click("保存并关闭");
    await until(() => !host.querySelector("textarea"));
    const paged = await api.notesRun(state.context.runId, state.context.trackId, state.context.virtualTimeMs);
    assert(paged.notes[0]!.links?.length === 2, "UI fill and closed-trade choices were not frozen together");
    assert(paged.notes[0]!.links?.every(link => link.eventTimeMs <= paged.asOfMs), "Linked detail exceeds the view clock");
    checks.push("actual UI links a committed fill and closed trade; each version retains its own immutable selection");
    const planId = paged.notes[0]!.id;
    for (let revision = paged.notes[0]!.revisionCount; revision < 25; revision++) await api.saveNoteRun(state.context.runId, state.context.trackId,
      { id: planId, fields: { ...paged.notes[0]!.fields, entryBasis: `同一事件计划版本 ${revision + 1}` }, expectedRevision: revision, context: paged.context });
    await click("刷新");
    await until(() => host.querySelectorAll("[data-note-version]").length === 20
      && host.querySelector('[data-note-version="25"]'));
    await click("加载更早版本");
    await until(() => host.querySelectorAll("[data-note-version]").length === 25);
    assert(new Set([...host.querySelectorAll("[data-note-version]")].map(value => value.getAttribute("data-note-version"))).size === 25,
      "Version pagination repeated or omitted a page");
    assert(!button("加载更早版本"), "Exhausted version history retained a continuation");
    await capture("version-history-pages");
    checks.push("actual history UI paginates 25 authoritative versions in 20+5 rows without duplication");
    await click("版本历史");
    state = await call("/fixture/advance", "POST"); render();
    await click("新增笔记"); await input("未来创建的笔记"); await click("保存并关闭");
    await until(() => !host.querySelector("textarea") && host.textContent?.includes("未来创建的笔记"));
    await click("新增笔记"); await input("未来未保存草稿");
    await until(() => Object.keys(localStorage).some(key => key.startsWith("candlescope.replay-note-draft.v1:")));
    state = await call("/fixture/review-first", "POST"); render();
    await until(() => button("新增复盘补记") && host.textContent?.includes("此时刻没有可见笔记。"));
    assert(!host.textContent?.includes("事前计划，保存不改变运行"), "The event revealed a note saved after it");
    state = await call("/fixture/review-marker", "POST"); render();
    await until(() => host.textContent?.includes("事前计划，保存不改变运行") && !host.querySelector("textarea"));
    for (const text of ["同一毫秒后一个事件修改的计划", "同一事件计划版本 25", "未来创建的笔记", "未来未保存草稿"])
      assert(!host.textContent?.includes(text), "Backward UI leaked future text: " + text);
    await click("版本历史");
    await until(() => host.querySelectorAll("[data-note-version]").length === 1);
    assert(host.querySelector('[data-note-version="1"]') && !host.querySelector('[data-note-version="2"]'),
      "Earlier same-time event history revealed later revisions");
    assert(!host.querySelector('[data-testid="replay-note-links"]'), "Earlier note history leaked future linked financial records");
    const blockedImage = await fetch(new URL(`/api/v1/replay/runs/${state.context.runId}/tracks/${state.context.trackId}/notes/${planId}/versions/2/screenshots/${updatedImage.id}`, backend));
    assert(blockedImage.status === 404, "Earlier same-time event could fetch a later note's PNG");
    const visibleImages = await api.noteCapturesRun(state.context.runId, state.context.trackId);
    assert(visibleImages.captures.every(image => image.id !== updatedImage.id), "Image chooser leaked a future-event capture");
    await capture("earlier-event-visible-original");
    await click("版本历史");
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


    await click("新增复盘补记"); await input("PNG已提交但响应丢失的草稿");
    loseNextCaptureReply = true; await click("截取当前图表");
    await until(() => host.querySelector('[role="alert"]'));
    assert(button("保存并关闭")!.disabled, "Pending PNG could be silently omitted from a note save");
    const committedCaptures = await api.noteCapturesRun(state.context.runId, state.context.trackId);
    const material = [...Object.keys(localStorage)].map(key => localStorage.getItem(key)).find(raw => raw?.includes('"image":"data:image/png;base64,'));
    assert(material, "Lost PNG reply erased its durable request material");
    root.unmount(); root = createRoot(host); render();
    await until(() => [...host.querySelectorAll<HTMLButtonElement>("button")].some(value => value.textContent?.startsWith("恢复草稿")));
    [...host.querySelectorAll<HTMLButtonElement>("button")].find(value => value.textContent?.startsWith("恢复草稿"))!.click();
    await until(() => host.querySelector("textarea")?.value === "PNG已提交但响应丢失的草稿");
    await click("重试截图提交"); await click("保存并关闭"); await until(() => !host.querySelector("textarea"));
    const recoveredImageNote = await api.notesRun(state.context.runId, state.context.trackId, state.context.virtualTimeMs);
    assert(recoveredImageNote.notes.some(note => note.fields.entryBasis === "PNG已提交但响应丢失的草稿" && note.screenshots?.length === 1), "PNG recovery did not bind the retained image");
    assert((await api.noteCapturesRun(state.context.runId, state.context.trackId)).captures.length === committedCaptures.captures.length, "PNG retry duplicated immutable images");
    checks.push("actual committed PNG reply loss retains material and remounted editor retries the exact image before saving");
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
    failNextCaptureBeforeSend = true; await click("截取当前图表");
    await until(() => host.querySelector('[role="alert"]'));
    const oldMaterialKey = Object.keys(localStorage).find(key => key.startsWith("candlescope.replay-note-capture-draft.v1:"));
    assert(oldMaterialKey, "Unsubmitted capture bytes were not retained");
    const oldMaterial = localStorage.getItem(oldMaterialKey!), oldCapturedTime = state.context.virtualTimeMs;
    const sourceKey = Object.keys(localStorage).find(key => key.startsWith("candlescope.replay-note-draft.v1:")
      && localStorage.getItem(key)?.includes("显式另存的旧视图草稿"));
    assert(sourceKey, "Original draft was not persisted");
    const sourceDraft = localStorage.getItem(sourceKey!);
    state = await call("/fixture/review-last", "POST"); render();
    await click("另存为当前时刻的新笔记"); await until(() => host.querySelector("textarea")?.value === "显式另存的旧视图草稿");
    await click("重试截图提交"); await click("保存并关闭"); await until(() => !host.querySelector("textarea"));
    const copied = await api.notesRun(state.context.runId, state.context.trackId, state.context.virtualTimeMs);
    const copiedNote = copied.notes.find(note => note.fields.entryBasis === "显式另存的旧视图草稿");
    assert(copiedNote?.reviewNote && copiedNote.marketTimeMs === state.context.virtualTimeMs,
      "Explicit copy did not become a new current-time review supplement");
    assert(localStorage.getItem(sourceKey!) === sourceDraft, "Explicit copy erased the original recovery data");
    assert(localStorage.getItem(oldMaterialKey!) === oldMaterial, "Explicit copy erased the original PNG request");
    assert(copiedNote?.screenshots?.[0]?.marketTimeMs === oldCapturedTime, "Explicit copy relabeled old pixels as a new capture time");
    checks.push("explicit current-time copy is a new review supplement and preserves the old-context draft");
    await until(() => host.textContent?.includes("显式另存的旧视图草稿") && !host.querySelector("textarea"));
    if (button("版本历史")?.getAttribute("aria-expanded") === "true") await click("版本历史");
    holdNextHistory = true; await click("版本历史");
    await until(() => releaseHistory);
    state = await call("/fixture/review-marker", "POST"); render();
    await until(() => host.querySelectorAll("[data-note-version]").length === 1
      && !host.textContent?.includes("同一事件计划版本 25"));
    releaseHistory!(); await new Promise(resolve => setTimeout(resolve, 100));
    assert(!host.textContent?.includes("同一事件计划版本 25") && !host.querySelector('[data-note-version="25"]'),
      "Late body of an old history request leaked future revisions into the earlier view");
    checks.push("actual delayed history body is cancelled on review rewind; the earlier same-time event keeps only version 1");
    const final = await call("/fixture/state");
    assert(JSON.stringify(final.snapshot) === JSON.stringify(before.snapshot), "Retry/copy changed live financial state");
    assert(final.network.blocked_attempts === 0, "Recovery attempted an external connection");
    await capture("recovered-review-notes");
    root.unmount(); release(); manager.dispose(); host.remove(); chartHost.remove();
    assert(manager.diagnostics().requests === 0 && manager.diagnostics().activeOperations === 0, "Note view leaked manager ownership");
    return { status: "PASS", scope: "Production React + actual loopback router/SQLite with explicit fixture candles; not native acceptance",
      checks, backendPid: final.pid, blockedExternalAttempts: final.network.blocked_attempts };
  } catch (error) {
    const diagnostic = `Action: ${lastAction}; UI: ${host.innerText.slice(-4000)}`;
    await capture("failure"); throw new Error(String(error) + "\n" + diagnostic);
  } finally { root.unmount(); release(); manager.dispose(); host.remove(); chartHost.remove(); }
}
