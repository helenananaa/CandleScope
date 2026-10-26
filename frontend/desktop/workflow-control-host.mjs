import { existsSync } from "node:fs";
import { DesktopControlService } from "./control-service.mjs";

/** Session-owned workflow access, enabled separately from the four chart tools. */
export class WorkflowControlHost {
  constructor({ manager, channels, directory, adapter, executable, trust = false, live = false }) {
    Object.assign(this, { manager, channels, directory, adapter, executable, trust, live });
    this.readyWindows = new Set();
    this.service = null;
  }
  ready(windowId) {
    this.readyWindows.add(windowId);
    this.service?.ready(windowId);
  }
  disconnect(windowId) {
    this.readyWindows.delete(windowId);
    this.service?.disconnect(windowId);
  }
  async start(mode) {
    const service = new DesktopControlService({ manager: this.manager, channels: this.channels,
      edit: mode === "control", trust: this.trust, live: this.live, trackWindowLifecycle: false });
    try {
      await service.start(this.directory);
      for (const windowId of this.readyWindows) service.ready(windowId);
      this.service = service;
    } catch (error) { await service.close(); throw error; }
  }
  status() {
    return { enabled: !!this.service, adapterAvailable: existsSync(this.adapter),
      scopes: this.service?.capabilities().scopes ?? [],
      config: this.service ? { mcpServers: { candlescope: { command: this.executable,
        args: [this.adapter, "mcp", "--connection", this.service.connectionFile],
        env: { ELECTRON_RUN_AS_NODE: "1" } } } } : null };
  }
  async close() {
    const previous = this.service;
    this.service = null;
    await previous?.close();
  }
}
