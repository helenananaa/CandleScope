import { LocalControlBroker } from "./local-control-broker.mjs";
import { startLocalMcpServer } from "./local-mcp-server.mjs";

/** Ephemeral, opt-in access; restarting never restores a prior grant. */
export class LocalMcpHost {
  constructor({ workflow = null } = {}) { this.workflow = workflow; }
  broker = new LocalControlBroker();
  server = null;
  audit = [];
  queue = Promise.resolve();
  status() {
    return { mode: this.server?.mode ?? "off", endpoint: this.server?.endpoint ?? null,
      token: this.server?.token ?? null, views: this.broker.list().views,
      audit: this.audit.slice(-50).reverse(), workflow: this.workflow?.status() ?? null };
  }
  setMode(mode, workflows = false) {
    if (!["off", "read", "control"].includes(mode) || typeof workflows !== "boolean") return Promise.reject(new Error("INVALID_CONTROL_MODE"));
    const operation = this.queue.then(async () => {
      // Also rotate when selecting the existing mode. Old sessions are revoked.
      const previous = this.server; this.server = null;
      await previous?.close();
      await this.workflow?.close();
      try {
        if (mode !== "off" && workflows) await this.workflow?.start(mode);
        if (mode !== "off") this.server = await startLocalMcpServer({ mode,
          invoke: (name, args, signal) => this.broker.invoke(name, args, signal),
          onAudit: (event) => { this.audit.push({ ...event, at: new Date().toISOString() }); this.audit = this.audit.slice(-50); },
        });
      } catch (error) { await this.workflow?.close(); throw error; }
      return this.status();
    });
    this.queue = operation.catch(() => {});
    return operation;
  }
  async close() { await this.setMode("off"); this.broker.close(); }
}
