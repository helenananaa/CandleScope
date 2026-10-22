import { createServer } from "node:http";
import { randomBytes, timingSafeEqual } from "node:crypto";
import { mkdir, readFile, writeFile, unlink, chmod, lstat, rename } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { ControlFiles } from "./control-files.mjs";

const MAX_REQUEST_BYTES = 64 * 1024;
const MAX_REPLY_BYTES = 2 * 1024 * 1024;
const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,95}$/;
const terminalStates = new Set(["ready", "failed", "applied"]);

export class ControlError extends Error {
  constructor(code, message = code) { super(message); this.code = code; }
}

export class DesktopControlService {
  constructor({ manager, channels, edit = false, trust = false, live = false, maxRequests = 1024, requestTimeoutMs = 30_000, trackWindowLifecycle = true }) {
    this.manager = manager;
    this.trackWindowLifecycle = trackWindowLifecycle;
    this.channels = channels;
    this.edit = edit;
    this.trust = edit && trust;
    this.live = edit && live;
    this.maxRequests = maxRequests;
    this.requestTimeoutMs = requestTimeoutMs;
    this.readyWindows = new Set();
    this.trackedWindows = new WeakSet();
    this.pending = new Map();
    this.requests = new Map();
    this.sockets = new Set();
    this.instanceId = randomBytes(16).toString("hex");
    this.token = randomBytes(32).toString("hex");
    this.closed = false;
    this.files = new ControlFiles();
  }

  ready(windowId) {
    const window = this.allWindows().get(windowId);
    if (!window || this.readyWindows.has(windowId)) return;
    this.readyWindows.add(windowId);
    if (!this.trackWindowLifecycle || this.trackedWindows.has(window)) return;
    this.trackedWindows.add(window);
    window.webContents.on("did-start-loading", () => this.disconnect(windowId));
    window.once("closed", () => this.disconnect(windowId));
  }

  allWindows() { return new Map([...this.manager.windows, ...(this.manager.appWindows ?? [])]); }

  disconnect(windowId) {
    this.files.clear(windowId);
    this.readyWindows.delete(windowId);
    for (const [id, entry] of this.pending) {
      if (entry.windowId === windowId) {
        this.pending.delete(id); clearTimeout(entry.timer);
        entry.resolve(entry.lastResult?.state === "applied"
          ? { ...entry.lastResult, code: "WINDOW_UNAVAILABLE", readiness: "unverified" }
          : { state: "failed", code: entry.mutation ? "OUTCOME_UNKNOWN" : "WINDOW_UNAVAILABLE" });
      }
    }
  }

  acceptResult(windowId, payload) {
    if (!payload || typeof payload !== "object" || typeof payload.id !== "string" || payload.instanceId !== this.instanceId) return;
    const pending = this.pending.get(payload.id);
    if (!pending || pending.windowId !== windowId) return;
    if (typeof payload.final !== "boolean" || !payload.result || !terminalStates.has(payload.result.state)) return;
    if (Buffer.byteLength(JSON.stringify(payload.result)) > MAX_REPLY_BYTES) return;
    pending.progress(payload.result);
    pending.lastResult = payload.result;
    if (payload.final) {
      this.pending.delete(payload.id); clearTimeout(pending.timer); pending.resolve(payload.result);
    }
  }

  dispatch(windowId, method, params, progress = () => {}) {
    const window = this.allWindows().get(windowId);
    if (this.closed || !window || window.isDestroyed() || !this.readyWindows.has(windowId)
      || !this.manager.options || !this.manager.windowIdForContents(window.webContents)) {
      return Promise.reject(new ControlError("WINDOW_UNAVAILABLE"));
    }
    const mutation = method === "workspace.configure" || method === "app.execute";
    const id = mutation ? params.requestId : `read-${randomBytes(12).toString("hex")}`;
    return new Promise((resolve, reject) => {
      const complete = (result) => {
        const receipt = this.requests.get(id);
        if (mutation && receipt && !receipt.final) { receipt.result = result; receipt.final = true; }
        resolve(result);
      };
      const timer = setTimeout(() => {
        const entry = this.pending.get(id);
        this.pending.delete(id);
        complete(entry?.lastResult?.state === "applied"
          ? { ...entry.lastResult, code: "WINDOW_TIMEOUT", readiness: "unverified" }
          : { state: "failed", code: mutation ? "OUTCOME_UNKNOWN" : "WINDOW_TIMEOUT" });
      }, this.requestTimeoutMs);
      this.pending.set(id, { windowId, resolve: complete, progress, timer, mutation });
      try { window.webContents.send(this.channels.controlRequest, { id, instanceId: this.instanceId, method, params }); }
      catch (error) { this.pending.delete(id); clearTimeout(timer); reject(error); }
    });
  }

  capabilities() {
    return { schema: "candlescope.control/1", instanceId: this.instanceId,
      scopes: this.edit ? ["observe", "workspace.edit", "app.edit", ...(this.trust ? ["app.trust"] : []), ...(this.live ? ["app.live"] : [])] : ["observe"],
      windows: [...this.allWindows().keys()].map((windowId) => ({ windowId, ready: this.readyWindows.has(windowId) })),
      commands: ["app.capabilities", "workspace.inspect", "app.commands", "app.query", "chart.capture", "request.get", "file.read", ...(this.edit ? ["workspace.configure", "app.execute", "app.open", "file.begin", "file.write", "file.commit", "file.remove"] : [])],
      files: { maxFileBytes: 33554432, maxTotalBytes: 134217728, chunkBytes: 32768, lifetime: "30 minutes idle, window reload/close, or process exit", windowBound: true },
      configuration: { layouts: ["single", "split-vertical", "split-horizontal", "quad"],
        exchanges: ["binance", "okx"], marketTypes: ["spot", "futures"], indicators: ["MA", "EMA", "RSI"],
        maxCharts: 4, maxIndicatorsPerChart: 8, periodRange: [1, 5000],
        replacesIndicators: true, configuredChartsBecomeUnlinked: true, undoScope: "layout",
        receipts: "Session-local; request IDs are retained until application exit. Inspect after an unknown outcome or restart." } };
  }

  async call(method, params = {}) {
    if (this.closed) throw new ControlError("CONTROL_CLOSED");
    if (!params || typeof params !== "object" || Array.isArray(params)) throw new ControlError("INVALID_PARAMS");
    if (method.startsWith("file.")) {
      const { windowId, ...input } = params;
      return this.fileCall(windowId, method.slice(5), input);
    }
    if (method === "app.capabilities") {
      this.onlyKeys(params, []); return this.capabilities();
    }
    if (method === "request.get") {
      this.onlyKeys(params, ["requestId"]);
      if (!ID.test(params.requestId ?? "")) throw new ControlError("INVALID_PARAMS");
      const entry = this.requests.get(params.requestId);
      if (!entry) throw new ControlError("REQUEST_NOT_FOUND");
      return { requestId: params.requestId, instanceId: this.instanceId, ...entry.result, final: entry.final };
    }
    if (!["workspace.inspect", "workspace.configure", "app.commands", "app.query", "app.execute", "app.open", "chart.capture"].includes(method)) throw new ControlError("UNKNOWN_METHOD");
    if (typeof params.windowId !== "string" || !ID.test(params.windowId)) throw new ControlError("INVALID_PARAMS", "windowId is required");
    if (method === "workspace.inspect") {
      this.onlyKeys(params, ["windowId"]); return this.dispatch(params.windowId, method, params);
    }
    if (method === "app.commands") {
      this.onlyKeys(params, ["windowId"]); return this.dispatch(params.windowId, method, params);
    }
    if (method === "app.query") {
      this.onlyKeys(params, ["windowId", "groupId", "command", "args"]); return this.dispatch(params.windowId, method, params);
    }
    if (method === "chart.capture") {
      this.onlyKeys(params, ["windowId", "maxSide"]);
      const maxSide = params.maxSide ?? 1024;
      if (!Number.isInteger(maxSide) || maxSide < 64 || maxSide > 1600) throw new ControlError("INVALID_PARAMS");
      const window = this.allWindows().get(params.windowId);
      if (!window || window.isDestroyed() || !this.readyWindows.has(params.windowId)) throw new ControlError("WINDOW_UNAVAILABLE");
      const bounds = window.getContentBounds();
      if (bounds.width * bounds.height > 16_777_216) throw new ControlError("CAPTURE_LIMIT");
      let captureTimer;
      const image = await Promise.race([window.webContents.capturePage(), new Promise((_resolve, reject) => {
        captureTimer = setTimeout(() => reject(new ControlError("CAPTURE_TIMEOUT")), 5000);
      })]).finally(() => clearTimeout(captureTimer));
      const size = image.getSize();
      if (!size.width || !size.height || size.width * size.height > 16_777_216) throw new ControlError("CAPTURE_LIMIT");
      const ratio = Math.min(1, maxSide / Math.max(size.width, size.height));
      const png = image.resize({ width: Math.max(1, Math.round(size.width * ratio)), height: Math.max(1, Math.round(size.height * ratio)) }).toPNG();
      if (png.length > 1_400_000) throw new ControlError("CAPTURE_LIMIT");
      return { mimeType: "image/png", data: png.toString("base64"), windowId: params.windowId, instanceId: this.instanceId };
    }
    if (!this.edit) throw new ControlError("SCOPE_DENIED", "Editing was not granted for this session");
    this.onlyKeys(params, method === "app.execute" ? ["requestId", "windowId", "groupId", "command", "args", "expectedContext"]
      : method === "app.open" ? ["requestId", "windowId", "page", "search"]
        : ["requestId", "workspaceId", "windowId", "expectedRevision", "layout", "charts"]);
    if (!ID.test(params.requestId ?? "") || typeof params.requestId !== "string") throw new ControlError("INVALID_PARAMS");
    const fingerprint = JSON.stringify({ method, params });
    const prior = this.requests.get(params.requestId);
    if (prior) {
      if (prior.fingerprint !== fingerprint) throw new ControlError("REQUEST_ID_CONFLICT");
      return { requestId: params.requestId, instanceId: this.instanceId, ...prior.result, final: prior.final };
    }
    if (this.requests.size >= this.maxRequests) throw new ControlError("REQUEST_LIMIT", "Session request budget exhausted; receipts have not been evicted");
    if ([...this.requests.values()].some((entry) => !entry.final && (method !== "app.execute" || entry.method !== "app.execute"))) throw new ControlError("CONTROL_BUSY", "Wait for the current configuration request");
    const entry = { method, fingerprint, final: false, result: { state: "accepted" } };
    this.requests.set(params.requestId, entry);
    const run = async () => {
      if (method !== "app.open") return this.dispatch(params.windowId, method, structuredClone(params), (result) => { entry.result = result; });
      const pages = { market: "index.html", strategy: "strategy.html", backtest: "backtest.html", replay: "replay.html", local: "local.html" };
      if (!Object.hasOwn(pages, params.page) || (params.search !== undefined && (typeof params.search !== "string" || params.search.length > 2048))) throw new ControlError("INVALID_PARAMS");
      if (!this.allWindows().has(params.windowId) || !this.readyWindows.has(params.windowId)) throw new ControlError("WINDOW_UNAVAILABLE");
      const target = new URL(pages[params.page], this.manager.options.appUrl);
      target.search = params.search ?? "";
      return { state: "applied", readiness: "command-acknowledged", output: await this.manager.openAppPage(target.href) };
    };
    void run()
      .then((result) => { entry.result = result; entry.final = true; })
      .catch((error) => { entry.result = { state: "failed", code: error.code ?? "CONTROL_ERROR", message: error.message }; entry.final = true; });
    return { requestId: params.requestId, instanceId: this.instanceId, state: "accepted", final: false };
  }

  onlyKeys(params, keys) {
    if (Object.keys(params).some((key) => !keys.includes(key))) throw new ControlError("INVALID_PARAMS", "Unknown parameter");
  }

  fileCall(windowId, operation, input) {
    if (this.closed || !this.readyWindows.has(windowId) || !this.allWindows().has(windowId)) throw new ControlError("WINDOW_UNAVAILABLE");
    return this.files.call(windowId, operation, input, this.edit);
  }

  async start(directory) {
    await mkdir(directory, { recursive: true, mode: 0o700 });
    if ((await lstat(directory)).isSymbolicLink()) throw new Error("Control directory must not be a link");
    if (process.platform === "win32") {
      const identity = spawnSync("whoami.exe", ["/user", "/fo", "csv", "/nh"], { encoding: "utf8", windowsHide: true });
      const sid = identity.stdout?.match(/S-1-5-[0-9-]+/)?.[0];
      if (identity.status !== 0 || !sid) throw new Error("Could not resolve the control credential owner");
      const reset = spawnSync("icacls.exe", [directory, "/reset"], { encoding: "utf8", windowsHide: true });
      if (reset.status !== 0) throw new Error("Could not reset the control credential directory permissions");
      const acl = spawnSync("icacls.exe", [directory, "/inheritance:r", "/grant:r", `*${sid}:(OI)(CI)F`], { encoding: "utf8", windowsHide: true });
      if (acl.status !== 0) throw new Error("Could not protect the control credential directory");
    } else await chmod(directory, 0o700);
    this.server = createServer((request, response) => { void this.handleHttp(request, response); });
    this.server.requestTimeout = 5000;
    this.server.headersTimeout = 5000;
    this.server.maxConnections = 16;
    this.server.on("connection", (socket) => { this.sockets.add(socket); socket.once("close", () => this.sockets.delete(socket)); });
    await new Promise((resolve, reject) => { this.server.once("error", reject); this.server.listen(0, "127.0.0.1", resolve); });
    this.endpoint = `http://127.0.0.1:${this.server.address().port}`;
    this.connectionFile = path.join(directory, "connection.json");
    try {
      try { if ((await lstat(this.connectionFile)).isSymbolicLink()) throw new Error("Control connection file must not be a link"); }
      catch (error) { if (error.code !== "ENOENT") throw error; }
      const temporaryFile = path.join(directory, `${this.instanceId}.json`);
      try {
        await writeFile(temporaryFile, JSON.stringify({ schema: "candlescope.control-connection/1",
          endpoint: this.endpoint, token: this.token, instanceId: this.instanceId, pid: process.pid }, null, 2), { mode: 0o600, flag: "wx" });
        await rename(temporaryFile, this.connectionFile);
      } finally { await unlink(temporaryFile).catch((error) => { if (error.code !== "ENOENT") throw error; }); }
      if (process.platform !== "win32") await chmod(this.connectionFile, 0o600);
    } catch (error) { await this.close(); throw error; }
    return this.connectionFile;
  }

  async handleHttp(request, response) {
    const reply = (status, body) => {
      if (response.destroyed) return;
      let data = JSON.stringify(body);
      if (Buffer.byteLength(data) > MAX_REPLY_BYTES) { status = 413; data = JSON.stringify({ ok: false, code: "REPLY_LIMIT" }); }
      response.writeHead(status, { "Content-Type": "application/json", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" });
      response.end(data);
    };
    const expectedHost = new URL(this.endpoint).host;
    const supplied = request.headers.authorization;
    const credential = typeof supplied === "string" ? Buffer.from(supplied) : Buffer.alloc(0);
    const expected = Buffer.from(`Bearer ${this.token}`);
    if (request.headers.origin !== undefined || request.headers.host !== expectedHost
      || credential.length !== expected.length || !timingSafeEqual(credential, expected)) {
      reply(403, { ok: false, code: "UNAUTHORIZED" }); request.resume(); return;
    }
    if (request.method !== "POST" || request.url !== "/call") { reply(404, { ok: false, code: "NOT_FOUND" }); request.resume(); return; }
    if (request.headers["content-type"]?.split(";")[0] !== "application/json") { reply(415, { ok: false, code: "CONTENT_TYPE" }); request.resume(); return; }
    try {
      let size = 0; const chunks = [];
      for await (const chunk of request) {
        size += chunk.length;
        if (size > MAX_REQUEST_BYTES) { reply(413, { ok: false, code: "REQUEST_LIMIT" }); request.resume(); return; }
        chunks.push(chunk);
      }
      const body = JSON.parse(Buffer.concat(chunks).toString("utf8"));
      if (!body || typeof body.method !== "string" || Object.keys(body).some((key) => !["method", "params"].includes(key))) throw new ControlError("INVALID_PARAMS");
      reply(200, { ok: true, result: await this.call(body.method, body.params) });
    } catch (error) { reply(400, { ok: false, code: error.code ?? "INVALID_REQUEST", message: error.message }); }
  }

  async close() {
    this.files.clear();
    this.closed = true;
    for (const windowId of [...this.readyWindows]) this.disconnect(windowId);
    for (const socket of this.sockets) socket.destroy();
    if (this.server?.listening) await new Promise((resolve) => this.server.close(resolve));
    if (this.connectionFile) {
      try {
        const connection = JSON.parse(await readFile(this.connectionFile, "utf8"));
        if (connection.instanceId === this.instanceId) await unlink(this.connectionFile);
      } catch (error) { if (error.code !== "ENOENT") throw error; }
    }
  }
}
