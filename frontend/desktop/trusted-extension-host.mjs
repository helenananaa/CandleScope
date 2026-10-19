import { readFile, writeFile, rename, unlink, mkdir, lstat, realpath } from "node:fs/promises";
import { createHash, randomUUID } from "node:crypto";
import path from "node:path";
import { pathToFileURL } from "node:url";

async function writeMarker(markerPath, value) {
  const temporary = `${markerPath}.${process.pid}.${randomUUID()}.tmp`;
  try {
    // A process can exit during either write. Never truncate the last complete marker.
    await writeFile(temporary, JSON.stringify(value), { encoding: "utf8", flush: true });
    await rename(temporary, markerPath);
  } catch (error) {
    await unlink(temporary).catch(() => {});
    throw error;
  }
}

async function bounded(work) {
  let timer;
  try {
    return await Promise.race([work, new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error("Desktop extension timed out; restart in recovery mode")), 10_000);
    })]);
  } finally { clearTimeout(timer); }
}

/** Only consumes the authenticated backend's full-trust, digest-verified plan. */
export class TrustedDesktopExtensionHost {
  constructor({ markerPath, context, safeMode = false }) {
    this.markerPath = markerPath;
    this.context = context;
    this.loaded = [];
    this.errors = {};
    this.safeMode = safeMode;
  }

  diagnostics() {
    return { safeMode: this.safeMode, active: this.loaded.map(({ id, digest, generation, version }) => ({ id, digest, generation, version })), errors: { ...this.errors } };
  }

  async start(plan) {
    this.safeMode = Boolean(plan.safeMode);
    if (plan.safeMode) return;
    await mkdir(path.dirname(this.markerPath), { recursive: true });
    let blocked = {};
    try {
      blocked = JSON.parse(await readFile(this.markerPath, "utf8"));
      if (!blocked || typeof blocked !== "object" || Array.isArray(blocked)) throw new Error("Invalid desktop extension crash marker");
    }
    catch (error) { if (error.code !== "ENOENT") { this.errors.runtime = String(error); return; } }
    for (const item of plan.active) {
      const { manifest, digest } = item;
      const cleanups = [];
      let disposed = false;
      let module;
      if (digest === blocked.digest && item.generation === blocked.generation) { this.errors[manifest.id] = "Previous startup interrupted while loading this extension"; continue; }
      if (Object.keys(manifest.dependencies ?? {}).some((id) => this.errors[id])) { this.errors[manifest.id] = "A dependency failed to start"; continue; }
      try {
        if (manifest.trust !== "full-trust" || manifest.apiVersion !== 1 || !manifest.entries?.desktop) throw new Error("Invalid desktop extension contract");
        const root = await realpath(item.root);
        for (const [name, digest] of Object.entries(item.files)) {
          const target = path.resolve(root, name);
          if (!target.startsWith(`${root}${path.sep}`) || (await lstat(target)).isSymbolicLink() || await realpath(target) !== target) throw new Error("Unsafe desktop extension path");
          if (createHash("sha256").update(await readFile(target)).digest("hex") !== digest) throw new Error("Desktop extension integrity check failed");
        }
        const entry = path.resolve(root, manifest.entries.desktop);
        if (!Object.hasOwn(item.files, manifest.entries.desktop)) throw new Error("Unverified desktop entry");
        await writeMarker(this.markerPath, { digest, generation: item.generation });
        module = await bounded(import(pathToFileURL(entry).href));
        if (typeof module.activate !== "function") throw new Error("Desktop entry must export activate(context)");
        if (typeof module.deactivate === "function") cleanups.push(module.deactivate);
        const result = await bounded(Promise.resolve(module.activate({ ...this.context, apiVersion: 1, internalApiVersion: 1,
          id: manifest.id, root, track: (cleanup) => {
            if (typeof cleanup !== "function") throw new TypeError("Cleanup must be callable");
            if (disposed) { void Promise.resolve().then(cleanup).catch((error) => { this.errors[manifest.id] = String(error); }); throw new Error("Extension has been disposed"); }
            cleanups.push(cleanup);
          } })));
        if (typeof result === "function") cleanups.push(result);
        this.loaded.push({ id: manifest.id, digest, generation: item.generation, version: manifest.version, cleanups, markDisposed: () => { disposed = true; } });
      } catch (error) {
        disposed = true;
        this.errors[manifest.id] = String(error);
        await this.dispose(manifest.id, cleanups);
      } finally {
        await writeMarker(this.markerPath, blocked);
      }
    }
  }

  async dispose(id, cleanups) {
    for (const cleanup of [...cleanups].reverse()) {
      try { await bounded(Promise.resolve(cleanup())); } catch (error) { this.errors[id] = String(error); }
    }
  }

  async stop() {
    for (const item of [...this.loaded].reverse()) { item.markDisposed(); await this.dispose(item.id, item.cleanups); }
    this.loaded = [];
  }
}
