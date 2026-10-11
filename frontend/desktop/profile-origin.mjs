import { access, mkdir, readFile, rename, writeFile } from "node:fs/promises";
import path from "node:path";
import { startDesktopAssetServer } from "./app-origin.mjs";

async function exists(file) {
  try {
    await access(file);
    return true;
  } catch (error) {
    if (error.code === "ENOENT") return false;
    throw error;
  }
}

/** A Chromium origin owns localStorage and IndexedDB: never silently change it. */
export async function startProfileAssetServer(directory, { userData, port = 18079 } = {}) {
  const filename = path.join(userData, "desktop-origin-v1.json");
  let saved;
  try {
    saved = JSON.parse(await readFile(filename, "utf8"));
    if (saved.schemaVersion !== 1 || !Number.isInteger(saved.port) || saved.port < 1 || saved.port > 65535) {
      throw new Error("Invalid saved desktop origin; restore desktop-origin-v1.json from backup.");
    }
  } catch (error) {
    if (error.code !== "ENOENT") throw error;
  }
  const legacy = !saved && (
    await exists(path.join(userData, "Local Storage"))
    || await exists(path.join(userData, "IndexedDB"))
  );
  const candidate = saved?.port ?? port;
  if (!Number.isInteger(candidate) || candidate < 1 || candidate > 65535) {
    throw new Error("Desktop UI port must be between 1 and 65535.");
  }
  let server;
  try {
    server = await startDesktopAssetServer(directory, {
      port: candidate,
      allowPortFallback: !saved && !legacy,
    });
  } catch (error) {
    if (!["EADDRINUSE", "EACCES"].includes(error.code)) throw error;
    throw Object.assign(new Error(`Saved desktop port ${candidate} is unavailable. Close the other app using this port and reopen CandleScope. Your profile has not been reset.`), { code: "DESKTOP_ORIGIN_UNAVAILABLE", port: candidate });
  }
  if (!saved) {
    try {
      await mkdir(userData, { recursive: true });
      const temporary = `${filename}.tmp`;
      await writeFile(temporary, JSON.stringify({ schemaVersion: 1, port: Number(new URL(server.appUrl).port) }), { mode: 0o600 });
      await rename(temporary, filename);
    } catch (error) {
      await server.close();
      throw error;
    }
  }
  return server;
}
