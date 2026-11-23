import { createReadStream } from "node:fs";
import { lstat, mkdir, readFile, realpath } from "node:fs/promises";
import { createHash, randomUUID } from "node:crypto";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { writeMarker } from "./activation-marker.mjs";
import { UnifiedEntryLifecycle } from "./unified-entry-lifecycle.mjs";

export class UnifiedDesktopHost {
  constructor({ request, context, markerPath }) {
    this.request = request;
    this.markerPath = markerPath;
    this.blockedStartup = null;
    this.loading = null;
    this.clientId = randomUUID();
    this.host = new UnifiedEntryLifecycle({
      load: async (item) => {
        if (item.manifest.trust !== "full-trust" || item.entry.kind !== "desktop") throw new Error("Desktop host code requires full trust");
        const root = await realpath(item.root);
        for (const [name, digest] of Object.entries(item.files)) {
          const target = path.resolve(root, name);
          if (!target.startsWith(root + path.sep) || (await lstat(target)).isSymbolicLink() || await realpath(target) !== target) throw new Error("Unsafe plugin execution path");
          const hash = createHash("sha256");
          let size = 0;
          for await (const block of createReadStream(target)) {
            size += block.length;
            if (size > 256 * 1024 * 1024) throw new Error("Plugin asset too large");
            hash.update(block);
          }
          if (hash.digest("hex") !== digest) throw new Error("Plugin integrity check failed");
        }
        if (!Object.hasOwn(item.files, item.entry.path)) throw new Error("Unpinned desktop entry");
        if (this.markerPath) {
          await writeMarker(this.markerPath, this.marker(item));
          this.loading = item.instanceId;
        }
        return import(`${pathToFileURL(path.resolve(root, item.entry.path)).href}?instance=${item.instanceId}`);
      },
      createContext: (item, guard) => {
        const cleanups = [];
        let disposed = false;
        return { context: { ...context, apiVersion: 1, id: item.pluginId, entryId: item.entry.id,
          identity: item.identity, instanceId: item.instanceId, root: item.root, storage: item.storage,
          track(cleanup) {
            if (typeof cleanup !== "function") throw new TypeError("Cleanup must be callable");
            if (disposed) { void Promise.resolve().then(cleanup).catch(() => {}); throw new Error("Entry disposed"); }
            cleanups.push(cleanup); guard();
          } }, async dispose() {
          disposed = true;
          const errors = [];
          for (const cleanup of cleanups.reverse()) {
            try { await cleanup(); } catch (error) { errors.push(error); }
          }
          if (errors.length) throw new globalThis.AggregateError(errors, "Plugin cleanup failed");
        } };
      },
      report: async (plan, item, state, error) => {
        if (this.loading === item.instanceId) {
          await writeMarker(this.markerPath, this.blockedStartup ?? {});
          this.loading = null;
        }
        return request("/report", { sessionId: plan.sessionId,
          instanceId: item.instanceId, state, ...(error ? { error } : {}) });
      },
    });
  }

  marker(item) {
    const { pluginId, packageSha256, generation } = item.identity;
    return { pluginId, packageSha256, generation, entryId: item.entry.id };
  }

  blocked(item) {
    const marker = this.marker(item);
    return this.blockedStartup && Object.keys(marker).every((key) => marker[key] === this.blockedStartup[key]);
  }

  async refresh() {
    if (this.stopped) return;
    if (this.refreshing) return this.refreshing;
    this.refreshing = (async () => {
      const plan = await this.request("/realm", { clientId: this.clientId, realm: "desktop" });
      if (this.stopped) return;
      const entries = [];
      for (const item of plan.entries) {
        if (!this.blocked(item)) { entries.push(item); continue; }
        const error = "Previous desktop startup was interrupted; disable or reapprove this activation";
        this.host.errors[item.pluginId] = error;
        await this.request("/report", { sessionId: plan.sessionId, instanceId: item.instanceId, state: "failed", error });
      }
      if (!this.stopped) await this.host.reconcile({ ...plan, entries });
    })().catch((error) => { this.host.errors.runtime = String(error); }).finally(() => { this.refreshing = null; });
    return this.refreshing;
  }
  async start() {
    if (this.markerPath) {
      try {
        await mkdir(path.dirname(this.markerPath), { recursive: true });
        this.blockedStartup = JSON.parse(await readFile(this.markerPath, "utf8"));
        if (!this.blockedStartup || typeof this.blockedStartup !== "object" || Array.isArray(this.blockedStartup)) {
          throw new Error("Invalid desktop plugin startup marker");
        }
      } catch (error) {
        if (error.code !== "ENOENT") { this.host.errors.runtime = String(error); return; }
      }
    }
    await this.refresh();
    if (this.stopped) return;
    this.timer = setInterval(() => { void this.refresh(); }, 5000);
    this.timer.unref?.();
  }
  diagnostics() { return { ...this.host.diagnostics(), safeMode: Boolean(this.host.plan.safeMode) }; }
  async stop() {
    this.stopped = true;
    clearInterval(this.timer);
    await this.host.stop();
  }
}
