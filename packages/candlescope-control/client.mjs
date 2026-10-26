import { readFile } from "node:fs/promises";
import path from "node:path";
import os from "node:os";

export function defaultConnectionFile() {
  if (process.env.CANDLESCOPE_CONTROL_FILE) return process.env.CANDLESCOPE_CONTROL_FILE;
  const base = process.platform === "win32" ? process.env.APPDATA
    : process.platform === "darwin" ? path.join(os.homedir(), "Library", "Application Support")
      : process.env.XDG_CONFIG_HOME ?? path.join(os.homedir(), ".config");
  if (!base) throw new Error("Use --connection to select the desktop connection file");
  return path.join(base, "CandleScope", "control", "connection.json");
}

export class ControlClient {
  constructor(connectionFile = defaultConnectionFile()) { this.connectionFile = connectionFile; }
  async connect() {
    let raw;
    try { raw = await readFile(this.connectionFile, "utf8"); }
    catch (cause) {
      if (cause.code !== "ENOENT") throw cause;
      const error = new Error("CandleScope AI control is offline. Open the desktop app, choose Settings > AI connection, enable desktop workflow tools and read/control access, then reconnect this MCP client.");
      error.code = "CONTROL_APP_OFFLINE";
      throw error;
    }
    if (Buffer.byteLength(raw) > 4096) throw new Error("Invalid connection file");
    const descriptor = JSON.parse(raw);
    const url = new URL(descriptor.endpoint);
    if (descriptor.schema !== "candlescope.control-connection/1" || url.protocol !== "http:"
      || url.hostname !== "127.0.0.1" || !url.port || url.username || url.password || url.pathname !== "/"
      || url.search || url.hash || !/^[a-f0-9]{64}$/.test(descriptor.token) || !/^[a-f0-9]{32}$/.test(descriptor.instanceId)) {
      throw new Error("Invalid local control connection file");
    }
    this.connection = descriptor;
    const result = await this.call("app.capabilities");
    if (result.instanceId !== descriptor.instanceId) throw new Error("Control instance changed; reconnect explicitly");
    return result;
  }
  async call(method, params = {}) {
    if (!this.connection) throw new Error("Connect to the running desktop instance first");
    const body = JSON.stringify({ method, params });
    if (Buffer.byteLength(body) > 64 * 1024) throw new Error("Control request exceeds 64 KiB");
    const response = await fetch(`${this.connection.endpoint}/call`, { method: "POST", redirect: "error",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${this.connection.token}` },
      body, signal: AbortSignal.timeout(35_000) });
    const reader = response.body?.getReader();
    if (!reader) throw new Error("Missing control response");
    const chunks = []; let size = 0;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.length;
      if (size > 2 * 1024 * 1024) { await reader.cancel(); throw new Error("Control response exceeds 2 MiB"); }
      chunks.push(Buffer.from(value));
    }
    const result = JSON.parse(Buffer.concat(chunks).toString("utf8"));
    if (!response.ok || !result.ok) {
      const error = new Error(`${result.code ?? "CONTROL_ERROR"}: ${result.message ?? "Control request failed"}`);
      error.code = result.code; throw error;
    }
    return result.result;
  }
}
