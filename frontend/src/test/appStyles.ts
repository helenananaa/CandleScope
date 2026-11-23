import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "..");

/**
 * The global stylesheet as the browser receives it: src/index.css with every import
 * inlined in order. Tests that assert on global CSS read this instead of index.css,
 * which only lists the feature files.
 */
export function readAppStyles(file = resolve(SRC, "index.css"), seen = new Set<string>()): string {
  return readFileSync(file, "utf8").replace(/^@import\s+"([^"]+)"[^;\n]*;$/gm, (_match: string, target: string) => {
    const path = resolve(dirname(file), target);
    if (seen.has(path)) return "";
    seen.add(path);
    return readAppStyles(path, seen);
  });
}
