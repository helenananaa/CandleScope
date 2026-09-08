import path from "node:path";
import fs from "node:fs";

export function bundledPythonPath(runtimeRoot, platform = process.platform) {
  return path.join(runtimeRoot, "python-runtime", "python", ...(platform === "win32" ? ["python.exe"] : ["bin", "python3"]));
}

export function resolvePythonCommand({ runtimeRoot, packaged, override, platform = process.platform, exists = fs.existsSync }) {
  if (override) return override;
  const bundled = bundledPythonPath(runtimeRoot, platform);
  if (exists(bundled)) return bundled;
  if (packaged) throw new Error("Packaged Python runtime is missing. Rebuild using npm run desktop:package:dir.");
  return "python";
}
