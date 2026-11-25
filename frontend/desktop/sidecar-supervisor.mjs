import { spawn } from "node:child_process";
import { EventEmitter } from "node:events";
import { mkdir, open, readFile, rm } from "node:fs/promises";
import { dirname } from "node:path";
import { randomUUID } from "node:crypto";

/** Waits before each automatic restart after an unexpected exit. Its length is the try budget. */
export const SIDECAR_RESTART_DELAYS_MS = Object.freeze([1_000, 3_000, 10_000]);

export class SidecarStartupError extends Error {
  constructor(message, diagnostics) {
    super(message);
    this.name = "SidecarStartupError";
    this.code = "SIDECAR_STARTUP_FAILED";
    this.diagnostics = diagnostics;
  }
}

function cancelledStart() {
  return new SidecarStartupError("Sidecar start was cancelled", { cancelled: true });
}

const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

/** The cause the backend recorded before it stopped (`app.core.startup_failure`), if any. */
export async function readBackendFailure(file) {
  if (!file) return null;
  try {
    const value = JSON.parse(await readFile(file, "utf8"));
    if (!value || typeof value.message !== "string" || !value.message.trim()) return null;
    return {
      code: typeof value.code === "string" && value.code ? value.code.slice(0, 120) : null,
      message: value.message.trim().slice(0, 2000),
    };
  } catch {
    return null;
  }
}

export function describeBackendFailure(failure) {
  return `The backend stopped while starting: ${failure.message}${failure.code ? ` (${failure.code})` : ""}`;
}

async function waitForHealthy(resolveUrl, child, timeoutMs, fetchImpl, instanceId, startupError, cancelled, backendFailure) {
  const startedAt = Date.now();
  let lastError = null;
  while (Date.now() - startedAt < timeoutMs) {
    if (cancelled()) throw cancelledStart();
    const spawnError = startupError();
    if (spawnError) throw new SidecarStartupError(spawnError.message, { spawnCode: spawnError.code });
    if (child.exitCode !== null || child.signalCode !== null) {
      const failure = await backendFailure();
      throw new SidecarStartupError(
        failure ? describeBackendFailure(failure) : `Sidecar exited before it became healthy (${child.exitCode})`,
        { exitCode: child.exitCode, signalCode: child.signalCode, backendFailure: failure },
      );
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
    await delay(100);
  }
  const failure = await backendFailure();
  throw new SidecarStartupError(
    failure ? describeBackendFailure(failure) : `Sidecar health check timed out after ${timeoutMs} ms`,
    { cause: lastError instanceof Error ? lastError.message : String(lastError), backendFailure: failure },
  );
}

function signalProcessGroup(pid, signal) {
  try {
    process.kill(-pid, signal);
    return true;
  } catch (error) {
    if (error?.code === "ESRCH" || error?.code === "EPERM") return false;
    throw error;
  }
}

/**
 * Owns the backend sidecar process.
 *
 * Emits "status" whenever the backend phase changes:
 * - running: healthy; `generation` counts healthy starts.
 * - restarting: the backend stopped and an attempt is scheduled (`retryAt`) or in progress.
 * - failed: the restart budget is used up, or a requested restart failed.
 * - stopped: stopped on purpose (by `stop()`), so no restart follows.
 * An unexpected exit after a healthy start is restarted automatically, once per
 * `restartDelaysMs` entry, on the same session endpoint. `stop()` and `beginQuit()`
 * never restart.
 */
export class SidecarSupervisor extends EventEmitter {
  constructor(options) {
    super();
    this.options = {
      fetchImpl: globalThis.fetch,
      healthTimeoutMs: 60_000,
      shutdownTimeoutMs: 10_000,
      restartDelaysMs: SIDECAR_RESTART_DELAYS_MS,
      // A sidecar that exits sooner than this after a restart uses up the same tries.
      stableAfterMs: 60_000,
      orphanGraceMs: 2_000,
      // A POSIX process group lets the host reclaim workers a killed sidecar leaves behind.
      processGroup: process.platform !== "win32",
      ...options,
    };
    this.child = null;
    this.logHandle = null;
    this.startPromise = null;
    this.startedAt = null;
    this.readyMs = null;
    this.boundPort = null;
    this.epoch = 0;
    this.quitting = false;
    this.recovery = null;
    this.recoveryRun = null;
    this.recoveryTimer = null;
    this.wakeRecovery = null;
    this.restartCount = 0;
    this.attemptsUsed = 0;
    this.healthyAt = null;
    this.state = {
      phase: "stopped", generation: 0, attempt: 0,
      maxAttempts: this.options.restartDelaysMs.length,
      retryAt: null, exit: null, error: null,
    };
  }

  get running() {
    return this.child !== null && this.child.exitCode === null && this.child.signalCode === null;
  }

  diagnostics() {
    return {
      pid: this.child?.pid ?? null,
      running: this.running,
      phase: this.state.phase,
      generation: this.state.generation,
      restarts: this.restartCount,
      startedAt: this.startedAt,
      readyMs: this.readyMs,
      command: this.options.command,
      args: this.options.args,
      healthUrl: this.options.healthUrl,
      logPath: this.options.logPath,
    };
  }

  status() {
    return { ...this.state, exit: this.state.exit && { ...this.state.exit } };
  }

  publish(patch) {
    this.state = { ...this.state, ...patch };
    this.emit("status", this.status());
  }

  async start() {
    if (this.quitting) throw cancelledStart();
    if (this.startPromise) return this.startPromise;
    if (this.running) return this.diagnostics();
    const epoch = this.epoch;
    this.startPromise = this.startOnce(epoch).finally(() => {
      this.startPromise = null;
    });
    return this.startPromise;
  }

  async startOnce(epoch) {
    const cancelled = () => this.quitting || this.epoch !== epoch;
    await mkdir(dirname(this.options.logPath), { recursive: true });
    if (cancelled()) throw cancelledStart();
    const logHandle = await open(this.options.logPath, "a");
    if (cancelled()) {
      await logHandle.close();
      throw cancelledStart();
    }
    await this.closeLog();
    this.logHandle = logHandle;
    this.startedAt = new Date().toISOString();
    this.readyMs = null;
    const instanceId = randomUUID();
    const endpointFile = this.options.dynamicPort ? `${this.options.logPath}.${instanceId}.endpoint.json` : null;
    const failureFile = `${this.options.logPath}.${instanceId}.failure.json`;
    const child = spawn(this.options.command, this.options.args, {
      cwd: this.options.cwd,
      env: { ...process.env, ...this.options.env, CANDLESCOPE_DESKTOP_INSTANCE_ID: instanceId,
        CANDLESCOPE_DESKTOP_BOUND_PORT: this.boundPort === null ? "" : String(this.boundPort),
        CANDLESCOPE_DESKTOP_ENDPOINT_FILE: endpointFile || "",
        CANDLESCOPE_DESKTOP_STARTUP_FAILURE_FILE: failureFile },
      windowsHide: true,
      detached: this.options.processGroup,
      stdio: [this.options.gracefulStdin ? "pipe" : "ignore", logHandle.fd, logHandle.fd],
    });
    this.child = child;
    let spawnError = null;
    let supervised = false;
    child.once("error", (error) => { spawnError = error; });
    child.once("exit", (code, signal) => {
      if (supervised) void this.onUnexpectedExit(child, code, signal);
    });
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
        cancelled,
        () => readBackendFailure(failureFile),
      );
      // Existing renderers retain this endpoint. Restarts must bind it exactly.
      if (endpointFile) this.boundPort = Number(new URL(this.options.healthUrl).port);
      // Publish in the same turn as the health result: a later exit then
      // always reports after this and is never overwritten.
      supervised = true;
      const recovered = this.state.phase === "restarting" ? { ...this.state } : null;
      if (this.state.generation > 0) this.restartCount += 1;
      this.healthyAt = Date.now();
      this.publish({
        phase: "running", generation: this.state.generation + 1, attempt: 0, retryAt: null, error: null,
      });
      if (recovered) {
        await this.note(recovered.attempt
          ? `sidecar restarted (attempt ${recovered.attempt} of ${recovered.maxAttempts})`
          : "sidecar restarted on request");
      }
      return this.diagnostics();
    } catch (error) {
      if (this.child === child) await this.terminateChild();
      throw error;
    } finally {
      if (endpointFile) {
        await rm(endpointFile, { force: true });
        await rm(endpointFile.replace(/\.json$/, ".tmp"), { force: true });
      }
      await rm(failureFile, { force: true });
      await rm(`${failureFile}.tmp`, { force: true });
    }
  }

  /** Restart now: skips a scheduled wait, or retries once after the budget is used up. */
  async restart() {
    if (this.quitting) throw cancelledStart();
    if (this.running) return this.diagnostics();
    if (this.recovery) {
      this.wakeRecovery?.();
      return this.recovery;
    }
    this.publish({ phase: "restarting", attempt: 0, retryAt: null, error: null });
    // Someone asked for this start: later exits get the full automatic budget again.
    this.attemptsUsed = 0;
    try {
      const result = await this.start();
      if (!this.running) throw new SidecarStartupError("Sidecar exited right after it became healthy", {});
      return result;
    } catch (error) {
      if (!this.quitting && !this.running && !this.recovery) {
        this.publish({ phase: "failed", retryAt: null, error: error instanceof Error ? error.message : String(error) });
      }
      throw error;
    }
  }

  async onUnexpectedExit(child, code, signal) {
    if (this.child !== child || this.quitting) return;
    this.child = null;
    const exit = { code, signal, at: new Date().toISOString() };
    if (this.healthyAt === null || Date.now() - this.healthyAt >= this.options.stableAfterMs) this.attemptsUsed = 0;
    const run = {};
    this.recoveryRun = run;
    this.recovery = this.recover(run, child.pid, exit).finally(() => {
      if (this.recoveryRun !== run) return;
      this.recoveryRun = null;
      this.recovery = null;
    });
    await this.recovery;
  }

  async recover(run, pid, exit) {
    const active = () => this.recoveryRun === run && !this.quitting;
    const delays = this.options.restartDelaysMs;
    this.publish({ phase: "restarting", attempt: Math.min(this.attemptsUsed + 1, delays.length), retryAt: null, exit, error: null });
    await this.note(`sidecar exited unexpectedly (code ${exit.code}, signal ${exit.signal}); restarting`);
    try { await this.reapProcessGroup(pid); }
    catch (caught) { await this.note(`could not reclaim sidecar workers: ${caught?.message ?? caught}`); }
    await this.closeLog();
    let error = this.attemptsUsed >= delays.length ? "Sidecar kept exiting soon after it was restarted" : null;
    while (this.attemptsUsed < delays.length && active()) {
      const index = this.attemptsUsed++;
      this.publish({ phase: "restarting", attempt: index + 1, retryAt: new Date(Date.now() + delays[index]).toISOString(), error });
      await new Promise((resolve) => {
        this.recoveryTimer = setTimeout(resolve, delays[index]);
        this.wakeRecovery = resolve;
      });
      clearTimeout(this.recoveryTimer);
      this.recoveryTimer = null;
      this.wakeRecovery = null;
      if (!active()) return this.diagnostics();
      this.publish({ phase: "restarting", attempt: index + 1, retryAt: null, error });
      try {
        await this.start();
        if (this.running) return this.diagnostics();
        error = "Sidecar exited right after it became healthy";
      } catch (caught) {
        error = caught instanceof Error ? caught.message : String(caught);
      }
    }
    if (active()) {
      this.publish({ phase: "failed", attempt: delays.length, retryAt: null, error });
    }
    return this.diagnostics();
  }

  async note(message) {
    try { await this.logHandle?.write(`${new Date().toISOString()} [desktop] ${message}\n`); }
    catch { /* The log is diagnostic only. */ }
  }

  async closeLog() {
    const handle = this.logHandle;
    this.logHandle = null;
    if (handle) await handle.close().catch(() => {});
  }

  /** Reclaims workers left in the stopped sidecar's process group (POSIX). */
  async reapProcessGroup(pid) {
    if (!this.options.processGroup || !Number.isInteger(pid) || pid <= 0) return;
    if (!signalProcessGroup(pid, "SIGTERM")) return;
    const deadline = Date.now() + this.options.orphanGraceMs;
    while (Date.now() < deadline) {
      await delay(50);
      if (!signalProcessGroup(pid, 0)) return;
    }
    signalProcessGroup(pid, "SIGKILL");
  }

  /** Stops supervision for good: no later exit is restarted. Call before quitting. */
  beginQuit() {
    this.quitting = true;
    this.cancelRecovery();
  }

  cancelRecovery() {
    this.recoveryRun = null;
    this.recovery = null;
    clearTimeout(this.recoveryTimer);
    this.recoveryTimer = null;
    this.wakeRecovery?.();
    this.wakeRecovery = null;
  }

  /** Deliberate stop. Never restarts; a later `start()` or `restart()` may. */
  async stop() {
    this.epoch += 1;
    this.cancelRecovery();
    const pending = this.startPromise;
    if (pending) await pending.catch(() => {});
    await this.terminateChild();
    if (!this.quitting && this.state.phase !== "stopped") {
      this.publish({ phase: "stopped", attempt: 0, retryAt: null, error: null });
    }
  }

  async terminateChild() {
    const child = this.child;
    this.child = null;
    if (child && child.exitCode === null && child.signalCode === null) {
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
      if (child.exitCode === null && child.signalCode === null) child.kill("SIGKILL");
    }
    if (child?.pid && this.options.processGroup) await this.reapProcessGroup(child.pid);
    await this.closeLog();
  }
}
