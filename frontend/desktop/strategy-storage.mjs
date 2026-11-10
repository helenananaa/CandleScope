import { mkdir, readFile, rename, unlink, writeFile } from "node:fs/promises";
import { dirname } from "node:path";
import { randomUUID } from "node:crypto";

const KEYS = new Set([
  "candlescope-strategy-drafts-v1", "candlescope:strategy-research:v1",
  "candlescope-chart-workspace-v8", "candlescope-chart-workspace-v7",
]);
const MAX_VALUE_BYTES = 16 * 1024 * 1024;
const RESEARCH_RETURN_KEY = /^candlescope:research-return:[\w-]{8,80}$/;
const MAX_RESEARCH_RETURNS = 64;

function valueLimit(key) {
  if (KEYS.has(key)) return MAX_VALUE_BYTES;
  return typeof key === "string" && RESEARCH_RETURN_KEY.test(key) ? 2048 : 0;
}

function pruneResearchReturns(values) {
  const entries = Object.keys(values).filter((key) => RESEARCH_RETURN_KEY.test(key));
  for (const key of entries.slice(0, Math.max(0, entries.length - MAX_RESEARCH_RETURNS))) delete values[key];
}

/** Profile-owned strategy state is independent of the loopback asset-server port. */
export class DesktopStrategyStorage {
  constructor(filePath) {
    this.filePath = filePath;
    this.values = {};
    this.writeQueue = Promise.resolve();
  }
  async load() {
    try {
      const data = JSON.parse(await readFile(this.filePath, "utf8"));
      if (data.schemaVersion === 1 && data.values && typeof data.values === "object") {
        for (const [key, value] of Object.entries(data.values)) {
          const limit = valueLimit(key);
          if (limit && typeof value === "string" && Buffer.byteLength(value) <= limit) {
            this.values[key] = value;
          }
        }
        pruneResearchReturns(this.values);
      }
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
    }
  }
  getItem(key) {
    if (!valueLimit(key)) throw new TypeError("Unsupported strategy storage key");
    return this.values[key] ?? null;
  }
  setItem(key, value) {
    const limit = valueLimit(key);
    if (!limit || typeof value !== "string" || Buffer.byteLength(value) > limit) {
      throw new TypeError("Invalid strategy storage value");
    }
    // Update memory immediately so concurrent reads/updates cannot overwrite a pending change.
    this.values[key] = value;
    pruneResearchReturns(this.values);
    const serialized = JSON.stringify({ schemaVersion: 1, values: this.values });
    const operation = this.writeQueue.catch(() => {}).then(async () => {
      await mkdir(dirname(this.filePath), { recursive: true });
      const temporary = `${this.filePath}.${randomUUID()}.tmp`;
      try {
        await writeFile(temporary, serialized, "utf8");
        await rename(temporary, this.filePath);
      } catch (error) {
        await unlink(temporary).catch(() => {});
        throw error;
      }
    });
    this.writeQueue = operation;
    return operation;
  }
  flush() { return this.writeQueue; }
}
