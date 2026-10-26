import fs from "node:fs/promises";
import path from "node:path";
import { randomUUID } from "node:crypto";

/** Build before replacing the active runtime; retain one rollback generation. */
export async function prepareDesktopRuntime(cache, build) {
  cache = path.resolve(cache);
  const removeDirectory = async directory => {
    const target = path.resolve(directory);
    if (path.dirname(target) !== cache) throw new Error(`Refusing to remove a directory outside ${cache}`);
    await fs.rm(target, { recursive: true, force: true });
  };
  await fs.mkdir(cache, { recursive: true });
  const staging = await fs.mkdtemp(path.join(cache, `staging-${Date.now()}-`));
  const destination = path.join(cache, "runtime");
  const lockPath = path.join(cache, "runtime-promotion.lock");
  let promotionLock;
  let previous;
  try {
    await build(staging);
    try {
      promotionLock = await fs.open(lockPath, "wx");
    } catch (error) {
      if (error.code === "EEXIST") throw new Error(`Runtime promotion is locked: ${lockPath}`, { cause: error });
      throw error;
    }
    await promotionLock.writeFile(JSON.stringify({ pid: process.pid }) + "\n");
    const backup = path.join(cache, `previous-${Date.now()}-${randomUUID()}`);
    try {
      await fs.rename(destination, backup);
      previous = backup;
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
    }
    try {
      await fs.rename(staging, destination);
    } catch (error) {
      if (previous) await fs.rename(previous, destination);
      throw error;
    }

    // Only remove our direct backup directories after promotion succeeds.
    // Downloads, control/build tools and other in-progress builds stay intact.
    const backups = (await fs.readdir(cache, { withFileTypes: true }))
      .filter(entry => entry.isDirectory() && /^previous-\d+(?:-[a-f0-9-]+)?$/.test(entry.name))
      .map(entry => entry.name)
      .sort((a, b) => Number(b.split("-")[1]) - Number(a.split("-")[1]));
    const keep = previous ? path.basename(previous) : backups[0];
    for (const name of backups) {
      if (name !== keep) await removeDirectory(path.join(cache, name));
    }
    return destination;
  } finally {
    try {
      await removeDirectory(staging);
    } finally {
      if (promotionLock) {
        await promotionLock.close();
        await fs.unlink(lockPath);
      }
    }
  }
}
