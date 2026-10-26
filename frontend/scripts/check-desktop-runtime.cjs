const fs = require("node:fs");
const path = require("node:path");
const { createHash } = require("node:crypto");
const { Arch } = require("builder-util");

module.exports = async (context) => {
  const controlRoot = path.join(context.packager.projectDir, ".desktop-runtime", "control");
  const control = JSON.parse(fs.readFileSync(path.join(controlRoot, "manifest.json"), "utf8"));
  const digest = createHash("sha256").update(fs.readFileSync(path.join(controlRoot, "cli.mjs"))).digest("hex");
  if (control.schema !== "candlescope.control-bundle/1" || digest !== control.sha256) throw new Error("Prepare the control adapter before packaging.");
  const root = path.join(context.packager.projectDir, ".desktop-runtime", "runtime");
  const manifest = JSON.parse(fs.readFileSync(path.join(root, "manifest.json"), "utf8"));
  if (manifest.platform !== context.electronPlatformName || manifest.arch !== Arch[context.arch]) {
    throw new Error("Python runtime does not match the desktop target. Prepare and package on the target platform and architecture.");
  }
  const pluginsRoot = path.join(root, "plugins");
  const plugins = JSON.parse(fs.readFileSync(path.join(pluginsRoot, "manifest.json"), "utf8"));
  if (plugins.schemaVersion !== 2 || !Array.isArray(plugins.plugins)
      || plugins.plugins.length !== 1
      || plugins.plugins[0]?.runtimeId !== "candlescope.pine-compat") {
    throw new Error("Prepare the bundled Pine runtime before packaging.");
  }
  for (const plugin of plugins.plugins) {
    const bytes = fs.readFileSync(path.join(pluginsRoot, plugin.filename));
    if (bytes.length !== plugin.size || `sha256:${createHash("sha256").update(bytes).digest("hex")}` !== plugin.sha256) {
      throw new Error(`Bundled runtime hash mismatch: ${plugin.runtimeId}`);
    }
  }
};
