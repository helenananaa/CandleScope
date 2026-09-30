import { spawn } from "node:child_process";
import { mkdir, open, readFile, rm } from "node:fs/promises";
import { dirname } from "node:path";
import { randomUUID } from "node:crypto";

export class SidecarStartupError extends Error {
  constructor(message, diagnostics) {
    super(message);
    this.name = "SidecarStartupError";
    this.code = "SIDECAR_STARTUP_FAILED";
    this.diagnostics = diagnostics;
  }
}

async function waitForHealthy(resolveUrl, child, timeoutMs, fetchImpl, instanceId, startupError) {
  const startedAt = Date.now();
  let lastError = null;
  while (Date.now() - startedAt < timeoutMs) {
    const spawnError = startupError();
    if (spawnError) throw new SidecarStartupError(spawnError.message, { spawnCode: spawnError.code });
    if (child.exitCode !== null || child.signalCode !== null) {
      throw new SidecarStartupError(`Sidecar exited before it became healthy (${child.exitCode})`, {
        exitCode: child.exitCode,
        signalCode: child.signalCode,
      });
    }
    try {
      const url = await resolveUrl();
      const response = url ? await fetchImpl(url, { signal: AbortSignal.timeout(1000) }) : null;
      if (response?.ok && (await response.json()).desktop_instance_id === instanceId
        && child.exitCode === null && child.signalCode === null) return Date.now() - startedAt;
      lastError = new Error(response ? `health endpoint returned ${response.status}` : "waiting for sidecar port");
    } catch (error) {
      lastError = error;
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new SidecarStartupError(`Sidecar health check timed out after ${timeoutMs} ms`, {
    cause: lastError instanceof Error ? lastError.message : String(lastError),
  });
}

export class SidecarSupervisor {
  constructor(options) {
    this.options = {
      fetchImpl: globalThis.fetch,
      healthTimeoutMs: 60_000,
      shutdownTimeoutMs: 10_000,
      ...options,
    };
    this.child = null;
    this.logHandle = null;
    this.startPromise = null;
    this.startedAt = null;
    this.readyMs = null;
    this.boundPort = null;
  }

  diagnostics() {
    return {
      pid: this.child?.pid ?? null,
      running: this.child !== null && this.child.exitCode === null,
      startedAt: this.startedAt,
      readyMs: this.readyMs,
      command: this.options.command,
      args: this.options.args,
      healthUrl: this.options.healthUrl,
      logPath: this.options.logPath,
    };
  }

  async start() {
    if (this.startPromise) return this.startPromise;
    if (this.child && this.child.exitCode === null && this.child.signalCode === null) return this.diagnostics();
    this.startPromise = this.startOnce().finally(() => {
      this.startPromise = null;
    });
    return this.startPromise;
  }

  async startOnce() {
    await mkdir(dirname(this.options.logPath), { recursive: true });
    this.logHandle = await open(this.options.logPath, "a");
    this.startedAt = new Date().toISOString();
    this.readyMs = null;
    const instanceId = randomUUID();
    const endpointFile = this.options.dynamicPort ? `${this.options.logPath}.${instanceId}.endpoint.json` : null;
    const child = spawn(this.options.command, this.options.args, {
      cwd: this.options.cwd,
      env: { ...process.env, ...this.options.env, CANDLESCOPE_DESKTOP_INSTANCE_ID: instanceId,
        CANDLESCOPE_DESKTOP_BOUND_PORT: this.boundPort === null ? "" : String(this.boundPort),
        CANDLESCOPE_DESKTOP_ENDPOINT_FILE: endpointFile || "" },
      windowsHide: true,
      detached: false,
      stdio: [this.options.gracefulStdin ? "pipe" : "ignore", this.logHandle.fd, this.logHandle.fd],
    });
    this.child = child;
    let spawnError = null;
    child.once("error", (error) => { spawnError = error; });
    // A child can exit while the parent is sending the shutdown command.
    child.stdin?.on("error", () => {});
    let endpointResolved = !endpointFile;
    const resolveUrl = async () => {
      if (!endpointResolved) {
        let endpoint;
        try { endpoint = JSON.parse(await readFile(endpointFile, "utf8")); }
        catch (error) { if (error.code === "ENOENT") return null; throw error; }
        if (endpoint.instanceId !== instanceId || !Number.isInteger(endpoint.port)
          || endpoint.port < 1 || endpoint.port > 65535) throw new Error("Invalid sidecar endpoint announcement");
        if (this.boundPort !== null && endpoint.port !== this.boundPort) {
          throw new Error("Sidecar restart changed the session endpoint");
        }
        this.options.healthUrl = `http://127.0.0.1:${endpoint.port}/health`;
        endpointResolved = true;
      }
      return this.options.healthUrl;
    };
    try {
      this.readyMs = await waitForHealthy(
        resolveUrl,
        child,
        this.options.healthTimeoutMs,
        this.options.fetchImpl,
        instanceId,
        () => spawnError,
      );
      // Existing renderers retain this endpoint. Restarts must bind it exactly.
      if (endpointFile) this.boundPort = Number(new URL(this.options.healthUrl).port);
      return this.diagnostics();
    } catch (error) {
      await this.stop();
      throw error;
    } finally {
      if (endpointFile) {
        await rm(endpointFile, { force: true });
        await rm(endpointFile.replace(/\.json$/, ".tmp"), { force: true });
      }
    }
  }

  async stop() {
    const child = this.child;
    this.child = null;
    if (child && child.exitCode === null) {
      let shutdownTimer;
      let onExit;
      try {
        await Promise.race([
          new Promise((resolve) => {
            onExit = resolve;
            child.once("exit", onExit);
            if (this.options.gracefulStdin && child.stdin?.writable) child.stdin.end("shutdown\n");
            else child.kill("SIGTERM");
          }),
          new Promise((resolve) => {
            shutdownTimer = setTimeout(resolve, this.options.shutdownTimeoutMs);
          }),
        ]);
      } finally {
        clearTimeout(shutdownTimer);
        child.off("exit", onExit);
      }
      if (child.exitCode === null) child.kill("SIGKILL");
    }
    if (this.logHandle) await this.logHandle.close();
    this.logHandle = null;
  }
}
