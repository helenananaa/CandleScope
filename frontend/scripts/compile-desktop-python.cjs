const path = require("node:path");
const { spawnSync } = require("node:child_process");

module.exports = async (context) => {
  const resources = context.electronPlatformName === "darwin"
    ? path.join(context.appOutDir, `${context.packager.appInfo.productFilename}.app`, "Contents", "Resources")
    : path.join(context.appOutDir, "resources");
  const runtime = path.join(resources, "python-runtime");
  const python = path.join(runtime, "python", ...(context.electronPlatformName === "win32" ? ["python.exe"] : ["bin", "python3"]));
  // Hash-based pyc files remain valid after bundle copying and relocation.
  // ccxt 4.5.60 ships unused BIP configuration templates with invalid imports.
  // Preserve their sources, but do not treat those templates as executable modules.
  const result = spawnSync(python, ["-m", "compileall", "-q", "--invalidation-mode", "checked-hash",
    "-x", "[/\\\\]ccxt[/\\\\]static_dependencies[/\\\\]bip[/\\\\]conf[/\\\\]",
    path.join(resources, "backend", "app"), path.join(resources, "packages"),
    path.join(runtime, "site-packages"), path.join(runtime, "python", "lib")], {
    stdio: "inherit", env: { ...process.env, PYTHONNOUSERSITE: "1" },
  });
  if (result.error) throw result.error;
  if (result.status !== 0) throw new Error("Packaged Python bytecode compilation failed");
};
