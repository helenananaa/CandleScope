import { app, BrowserWindow, dialog, ipcMain, screen, shell } from "electron";
import { mkdir, writeFile } from "node:fs/promises";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { randomBytes } from "node:crypto";
import { resolvePythonCommand } from "./python-runtime.mjs";
import { desktopBackendEnvironment } from "./runtime-config.mjs";
import { isTrustedAppUrl } from "./app-origin.mjs";
import { startProfileAssetServer } from "./profile-origin.mjs";

import { ElectronWindowManager } from "./electron-window-manager.mjs";
import { AppWorkBudgetHub } from "./app-work-budget-hub.mjs";
import { DESKTOP_IPC, validateTopologyPayload } from "./ipc-contract.mjs";
import { createEvidenceSession } from "./evidence-harness-loader.mjs";
import { SidecarSupervisor } from "./sidecar-supervisor.mjs";
import { SeriesSnapshotHub } from "./series-snapshot-hub.mjs";
import { DesktopShellStateStore } from "./shell-state-store.mjs";
import { WorkspaceBusConflictError, WorkspaceBusHub } from "./workspace-bus-hub.mjs";

const desktopDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(desktopDir, "../..");
const runtimeRoot = app.isPackaged ? process.resourcesPath : repoRoot;
const backendRoot = path.join(runtimeRoot, "backend");
app.setName("CandleScope");
if (process.env.CANDLESCOPE_DESKTOP_USER_DATA) {
  app.setPath("userData", path.resolve(process.env.CANDLESCOPE_DESKTOP_USER_DATA));
}
app.setAppLogsPath(path.join(app.getPath("userData"), "logs"));
const multiWindowEnabled = process.env.MULTI_WINDOW_ENABLED === "1"
  || process.env.VITE_MULTI_WINDOW_ENABLED === "1";
let appUrl = process.env.CANDLESCOPE_DESKTOP_URL || "http://127.0.0.1:15173/";
let assetServer = null;
const managementSession = {
  sessionToken: randomBytes(32).toString("base64url"),
  csrfToken: randomBytes(32).toString("base64url"),
};
let backendPort = Number(process.env.CANDLESCOPE_DESKTOP_BACKEND_PORT || 18080);
const evidenceSession = createEvidenceSession(process.env);
evidenceSession?.configureApp(app);
const gotSingleInstanceLock = app.requestSingleInstanceLock({ source: "desktop-shell" });

let manager = null;
let supervisor = null;
let shutdownComplete = false;
let shutdownPromise = null;
const workspaceBus = new WorkspaceBusHub();
const appWorkBudget = new AppWorkBudgetHub();
const seriesSnapshots = new SeriesSnapshotHub();
const registeredWorkspaceContents = new WeakSet();

function windowIdForSender(sender) {
  return manager?.windowIdForContents(sender) ?? null;
}

const trustedIpc = {
  handle(channel, handler) {
    ipcMain.handle(channel, (event, ...args) => {
      manager.assertTrustedSender(event);
      return handler(event, ...args);
    });
  },
  on(channel, handler) {
    ipcMain.on(channel, (event, ...args) => {
      try {
        manager.assertTrustedSender(event);
        handler(event, ...args);
      } catch { event.returnValue = { ok: false, code: "DESKTOP_SENDER_REJECTED" }; }
    });
  },
};

function registerWorkspaceSender(sender) {
  const windowId = windowIdForSender(sender);
  if (!windowId) throw new Error("WorkspaceBus sender is not a managed CandleScope window");
  if (!registeredWorkspaceContents.has(sender)) {
    registeredWorkspaceContents.add(sender);
    workspaceBus.register(windowId, (message) => {
      if (!sender.isDestroyed()) sender.send(DESKTOP_IPC.workspaceBusEvent, message);
    });
    sender.once("destroyed", () => {
      workspaceBus.disconnect(windowId);
      appWorkBudget.releaseWindow(windowId);
    });
  }
  return windowId;
}

function parseSidecarCommand() {
  const override = process.env.CANDLESCOPE_DESKTOP_SIDECAR_COMMAND_JSON;
  if (override) {
    const parsed = JSON.parse(override);
    if (!Array.isArray(parsed) || parsed.length < 1 || parsed.some((part) => typeof part !== "string")) {
      throw new TypeError("CANDLESCOPE_DESKTOP_SIDECAR_COMMAND_JSON must be a JSON string array");
    }
    return { command: parsed[0], args: parsed.slice(1) };
  }
  return {
    command: resolvePythonCommand({ runtimeRoot, packaged: app.isPackaged, override: process.env.CANDLESCOPE_PYTHON }),
    args: [
      "-m",
      "app.desktop_sidecar",
      "--host",
      "127.0.0.1",
      "--port",
      String(backendPort),
    ],
  };
}

function createSupervisor() {
  if (process.env.CANDLESCOPE_DESKTOP_SKIP_SIDECAR === "1") return null;
  const command = parseSidecarCommand();
  return new SidecarSupervisor({
    ...command,
    gracefulStdin: !process.env.CANDLESCOPE_DESKTOP_SIDECAR_COMMAND_JSON,
    dynamicPort: !process.env.CANDLESCOPE_DESKTOP_SIDECAR_COMMAND_JSON,
    cwd: backendRoot,
    env: {
      ...(app.isPackaged ? desktopBackendEnvironment(JSON.parse(readFileSync(
        path.join(app.getAppPath(), "dist", "desktop-runtime-config.json"), "utf8",
      ))) : {}),
      ...(app.isPackaged ? { PYTHONNOUSERSITE: "1", PYTHONDONTWRITEBYTECODE: "1" } : {}),
      CANDLE_HOST: "127.0.0.1",
      CANDLE_PORT: String(backendPort),
      CANDLE_DATA_DIR: process.env.CANDLE_DATA_DIR || path.join(app.getPath("userData"), "data"),
      CORS_ORIGINS: new URL(appUrl).origin,
      CANDLESCOPE_PLUGIN_PLATFORM_V2_MANAGEMENT_ORIGINS: new URL(appUrl).origin,
      CANDLESCOPE_DESKTOP_PLUGIN_SESSION: managementSession.sessionToken,
      CANDLESCOPE_DESKTOP_PLUGIN_CSRF: managementSession.csrfToken,
      PYTHONPATH: [
        path.join(runtimeRoot, "python-runtime", "site-packages"),
        path.join(runtimeRoot, "packages", "candlescope-plugin-sdk", "src"),
        process.env.PYTHONPATH,
      ].filter(Boolean).join(path.delimiter),
    },
    healthUrl: `http://127.0.0.1:${backendPort}/health`,
    healthTimeoutMs: Number(process.env.CANDLESCOPE_DESKTOP_SIDECAR_TIMEOUT_MS || 90_000),
    shutdownTimeoutMs: 15_000,
    logPath: path.join(app.getPath("logs"), "backend-sidecar.log"),
  });
}

async function boot() {
  if (app.isPackaged && !process.env.CANDLESCOPE_DESKTOP_URL) {
    assetServer = await startProfileAssetServer(path.join(app.getAppPath(), "dist"), {
      userData: app.getPath("userData"),
      port: Number(process.env.CANDLESCOPE_DESKTOP_UI_PORT || 18079),
    });
    appUrl = assetServer.appUrl;
  }
  if (!isTrustedAppUrl(appUrl, appUrl)) throw new Error("Desktop URL must be a loopback application page");
  supervisor = createSupervisor();
  await supervisor?.start();
  if (supervisor) backendPort = Number(new URL(supervisor.diagnostics().healthUrl).port);

  const store = new DesktopShellStateStore(path.join(app.getPath("userData"), "desktop-windows-v1.json"));
  const cached = await store.load();
  manager = new ElectronWindowManager({
    openExternal: (url) => shell.openExternal(url),
    BrowserWindow,
    screen,
    store,
    channels: DESKTOP_IPC,
    preloadPath: path.join(desktopDir, "preload.cjs"),
    backendPort,
    appUrl: evidenceSession?.instrumentAppUrl(appUrl) ?? new URL(appUrl).href,
    multiWindowEnabled,
  });

  await evidenceSession?.initialize({
    app, screen, manager, supervisor, backendPort, multiWindowEnabled,
    workspaceBus, appWorkBudget, seriesSnapshots, process,
  });

  trustedIpc.on(DESKTOP_IPC.backendEndpoint, (event) => {
    event.returnValue = { port: backendPort };
  });

  trustedIpc.on(DESKTOP_IPC.managementSession, (event) => {
    event.returnValue = supervisor ? {
      apiBase: `http://127.0.0.1:${backendPort}/api/v2/plugins`,
      ...managementSession,
    } : null;
  });
  trustedIpc.handle(DESKTOP_IPC.openAppPage, (_event, url) => manager.openAppPage(url));

  trustedIpc.handle(DESKTOP_IPC.bootstrap, (event) => {
    const windowId = manager.assertTrustedSender(event);
    const state = store.snapshot();
    return {
      mode: "native",
      multiWindowAvailable: true,
      multiWindowEnabled,
      windowId,
      workspaceId: state.workspaceId,
      shellRevision: state.shellRevision,
      displayCount: screen.getAllDisplays().length,
      sidecar: supervisor?.diagnostics() || { skipped: true },
      logsPath: app.getPath("logs"),
    };
  });
  trustedIpc.handle(DESKTOP_IPC.reconcile, async (_event, raw) => {
    const probeRejection = evidenceSession?.topologyRejection(store.snapshot().shellRevision);
    if (probeRejection) return probeRejection;
    try {
      const result = await manager.reconcile(validateTopologyPayload(raw));
      return { ok: true, ...result };
    } catch (error) {
      return {
        ok: false,
        code: error?.code || "DESKTOP_TOPOLOGY_REJECTED",
        message: error instanceof Error ? error.message : String(error),
        shellRevision: store.snapshot().shellRevision,
      };
    }
  });
  trustedIpc.handle(DESKTOP_IPC.workspaceBusConnect, (event, raw) => {
    try {
      const windowId = registerWorkspaceSender(event.sender);
      return workspaceBus.connect(windowId, raw?.snapshot ?? null);
    } catch (error) {
      return {
        ...workspaceBus.stateResult(),
        ok: false,
        code: error?.code || "WORKSPACE_BUS_CONNECT_REJECTED",
        message: String(error?.message || error),
      };
    }
  });
  trustedIpc.handle(DESKTOP_IPC.workspaceBusCommit, (event, raw) => {
    try {
      const windowId = registerWorkspaceSender(event.sender);
      return workspaceBus.commit(windowId, raw);
    } catch (error) {
      const state = workspaceBus.stateResult();
      return {
        ...state,
        ok: false,
        code: error?.code || "WORKSPACE_BUS_COMMIT_REJECTED",
        message: String(error?.message || error),
        conflict: error instanceof WorkspaceBusConflictError ? error.details : null,
      };
    }
  });
  trustedIpc.handle(DESKTOP_IPC.workspaceBusLink, (event, raw) => {
    try {
      const windowId = registerWorkspaceSender(event.sender);
      return workspaceBus.publishLink(windowId, raw);
    } catch (error) {
      return { ok: false, code: "WORKSPACE_LINK_REJECTED", message: String(error?.message || error) };
    }
  });
  trustedIpc.on(DESKTOP_IPC.workspaceBusWindow, (event, raw) => {
    try {
      workspaceBus.reportWindow(registerWorkspaceSender(event.sender), raw);
    } catch {
      // A destroyed or unmanaged sender has no remaining health authority.
    }
  });
  trustedIpc.handle(DESKTOP_IPC.appWorkAcquire, (event, raw) => {
    try {
      const windowId = registerWorkspaceSender(event.sender);
      return appWorkBudget.acquire({ ...raw, windowId });
    } catch {
      return { released: true };
    }
  });
  trustedIpc.on(DESKTOP_IPC.appWorkRelease, (_event, leaseId) => {
    if (typeof leaseId === "string") appWorkBudget.release(leaseId);
  });
  trustedIpc.handle(DESKTOP_IPC.appPreviewRequest, (event, raw) => {
    const windowId = registerWorkspaceSender(event.sender);
    return appWorkBudget.requestPreview({ ...raw, windowId });
  });
  trustedIpc.on(DESKTOP_IPC.appPreviewRelease, (event, raw) => {
    const windowId = windowIdForSender(event.sender);
    if (windowId) appWorkBudget.releasePreview({ ...raw, windowId });
  });
  trustedIpc.handle(DESKTOP_IPC.appBudgetDiagnostics, () => ({
    workspaceBus: workspaceBus.diagnostics(),
    appWork: appWorkBudget.diagnostics(),
    seriesSnapshots: seriesSnapshots.diagnostics(),
  }));
  trustedIpc.on(DESKTOP_IPC.seriesSnapshotRead, (event, rawKey) => {
    event.returnValue = windowIdForSender(event.sender)
      ? seriesSnapshots.read(rawKey)
      : { ok: false, code: "SERIES_SNAPSHOT_SENDER_UNMANAGED", rows: [] };
  });
  trustedIpc.on(DESKTOP_IPC.seriesSnapshotPublish, (event, raw) => {
    if (!windowIdForSender(event.sender)) return;
    try {
      seriesSnapshots.publish(raw);
    } catch {
      // The hub records bounded validation rejects; renderer state is never trusted.
    }
  });
  trustedIpc.handle(DESKTOP_IPC.seriesSnapshotDiagnostics, () => seriesSnapshots.diagnostics());

  screen.on("display-added", () => {
    evidenceSession?.noteDisplayEvent("added");
    manager.recoverOffscreenWindows();
  });
  screen.on("display-removed", () => {
    evidenceSession?.noteDisplayEvent("removed");
    manager.recoverOffscreenWindows();
  });
  screen.on("display-metrics-changed", () => {
    evidenceSession?.noteDisplayEvent("metricsChanged");
    manager.recoverOffscreenWindows();
  });

  if (evidenceSession) {
    await evidenceSession.run({ store, cached, manager });
    app.quit();
    return;
  }
  await manager.restoreCached(cached);
}

if (!gotSingleInstanceLock) {
  app.quit();
} else {
  app.on("second-instance", () => {
    const window = manager?.windows.get("main-window") || manager?.windows.values().next().value;
    if (!window) return;
    if (window.isMinimized()) window.restore();
    window.show();
    window.focus();
  });
  app.whenReady().then(boot).catch(async (error) => {
    const logsPath = app.getPath("logs");
    try {
      await mkdir(logsPath, { recursive: true });
      await writeFile(
        path.join(logsPath, "desktop-startup-error.log"),
        `${new Date().toISOString()} ${error?.stack || error}\n`,
        { flag: "a" },
      );
    } catch (logError) {
      console.error("Could not save startup diagnostics", logError);
    }
    const chinese = app.getLocale().toLowerCase().startsWith("zh");
    const sidecarFailed = error?.code === "SIDECAR_STARTUP_FAILED";
    const originFailed = error?.code === "DESKTOP_ORIGIN_UNAVAILABLE";
    dialog.showErrorBox(
      chinese ? "CandleScope 启动失败" : "CandleScope could not start",
      [
        originFailed
          ? (chinese ? `此配置使用的端口 ${error.port} 被占用。请关闭占用端口的其他应用后重试。配置与数据未被重置。` : `This profile's port ${error.port} is unavailable. Close the other application using it and try again. Your settings and data have not been reset.`)
          : sidecarFailed
          ? (chinese ? "本地后端未能启动。请检查 Python 运行环境及后端依赖是否完整。" : "The local backend could not start. Check that the Python runtime and backend dependencies are installed.")
          : (chinese ? "应用初始化失败，请查看启动日志以确定原因。" : "Application initialization failed. Check the startup log for details."),
        `${chinese ? "原因" : "Reason"}: ${error instanceof Error ? error.message : String(error)}`,
        chinese ? "日志目录：" : "Log directory:",
        logsPath,
        sidecarFailed ? "backend-sidecar.log / desktop-startup-error.log" : "desktop-startup-error.log",
      ].join("\n\n"),
    );
    await supervisor?.stop();
    await assetServer?.close();
    app.exit(1);
  });
}

app.on("before-quit", () => {
  manager?.approveQuit();
});

// Close renderer-owned streams before waiting for the backend to shut down.
app.on("will-quit", (event) => {
  if (shutdownComplete || (!supervisor && !assetServer)) return;
  event.preventDefault();
  shutdownPromise ??= Promise.all([supervisor?.stop(), assetServer?.close()]).finally(() => {
    shutdownComplete = true;
    app.quit();
  });
});
app.on("window-all-closed", () => app.quit());
