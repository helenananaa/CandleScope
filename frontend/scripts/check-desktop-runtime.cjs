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
  if (fs.existsSync(path.join(pluginsRoot, "manifest.json"))) {
    throw new Error("Retired script runtime manifest found in desktop build.");
  }
  for (const [id, kind] of [["candlescope.pine-compat", "pine"], ["candlescope.python-indicator", "python"]]) {
    const descriptor = path.join(pluginsRoot, `unified-${kind}.json`);
    if (!fs.existsSync(descriptor)) throw new Error(`Prepare the bundled first-party runtime: ${id}`);
    const plugin = JSON.parse(fs.readFileSync(descriptor, "utf8"));
    if (plugin?.schema !== `candlescope.bundled-unified-${kind}/1`) {
      throw new Error(`Bundled runtime descriptor is invalid: ${id}`);
    }
    if (typeof plugin.filename !== "string" || !/^[a-zA-Z0-9_.-]+[.]cspkg$/.test(plugin.filename)) {
      throw new Error(`Bundled runtime filename is invalid: ${id}`);
    }
    const bytes = fs.readFileSync(path.join(pluginsRoot, plugin.filename));
    if (bytes.length !== plugin.size || `sha256:${createHash("sha256").update(bytes).digest("hex")}` !== plugin.sha256) {
      throw new Error(`Bundled runtime hash mismatch: ${id}`);
    }
  }
};
