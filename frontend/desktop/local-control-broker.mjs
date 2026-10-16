import { randomUUID } from "node:crypto";

const validId = (value) => typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$/.test(value);
const fail = (code) => Object.assign(new Error(code), { code });

/** Dispatch only to the renderer that owns the caller's explicit target. */
export class LocalControlBroker {
  windows = new Map();
  pending = new Map();
  busy = new Set();

  register(windowId, send) {
    if (!validId(windowId) || typeof send !== "function") throw fail("INVALID_CONTROL_WINDOW");
    this.remove(windowId);
    this.windows.set(windowId, { send, views: [] });
  }

  publish(windowId, value) {
    const window = this.windows.get(windowId);
    if (!window) throw fail("CONTROL_WINDOW_CLOSED");
    if (!Array.isArray(value) || value.length > 64) throw fail("INVALID_CONTROL_VIEWS");
    const ids = new Set();
    const views = value.map((view) => {
      if (!view || !validId(view.viewId) || !validId(view.revision)
        || !["market", "replay", "research"].includes(view.kind)
        || ids.has(view.viewId)) throw fail("INVALID_CONTROL_VIEW");
      ids.add(view.viewId);
      return { windowId, viewId: view.viewId, revision: view.revision, kind: view.kind };
    });
    window.views = views;
  }

  list() { return { views: [...this.windows.values()].flatMap((window) => window.views) }; }

  remove(windowId) {
    this.windows.delete(windowId);
    for (const request of this.pending.values()) {
      if (request.windowId === windowId) request.reject(fail("CONTROL_WINDOW_CLOSED"));
    }
  }

  reply(windowId, value) {
    const request = this.pending.get(value?.requestId);
    if (!request || request.windowId !== windowId) return false;
    if (value.ok === true && value.result && typeof value.result === "object" && !Array.isArray(value.result)) {
      if (Buffer.byteLength(JSON.stringify(value.result)) > 2 * 1024 * 1024) request.reject(fail("CONTROL_RESULT_TOO_LARGE"));
      else request.resolve(value.result);
    } else request.reject(fail(typeof value.code === "string" && /^[A-Z0-9_]{1,80}$/.test(value.code) ? value.code : "CONTROL_REQUEST_FAILED"));
    return true;
  }

  async invoke(name, args, signal) {
    if (signal.aborted) throw fail("CONTROL_CANCELLED");
    if (name === "candlescope_list_views") return this.list();
    const window = this.windows.get(args.windowId);
    const view = window?.views.find((entry) => entry.viewId === args.viewId);
    if (!window || !view) throw fail("CONTROL_VIEW_NOT_FOUND");
    const mutation = name !== "candlescope_read_view";
    if (mutation && view.revision !== args.expectedRevision) throw fail("CONTROL_REVISION_CONFLICT");
    if (mutation && this.busy.has(args.windowId)) throw fail("CONTROL_WINDOW_BUSY");
    if (mutation) this.busy.add(args.windowId);
    const requestId = randomUUID();
    let abort;
    try {
      return await new Promise((resolve, reject) => {
        this.pending.set(requestId, { windowId: args.windowId, resolve, reject });
        abort = () => {
          try { window.send({ type: "cancel", requestId }); }
          catch { /* The renderer may have closed while cancellation was in flight. */ }
          reject(fail(mutation ? "CONTROL_OUTCOME_UNKNOWN_READ_VIEW" : "CONTROL_CANCELLED"));
        };
        signal.addEventListener("abort", abort, { once: true });
        if (signal.aborted) { abort(); return; }
        window.send({ type: "request", requestId, name, arguments: args });
      });
    } finally {
      if (abort) signal.removeEventListener("abort", abort);
      this.pending.delete(requestId);
      if (mutation) this.busy.delete(args.windowId);
    }
  }

  close() { for (const id of [...this.windows.keys()]) this.remove(id); }
}
