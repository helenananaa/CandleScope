const fs = require("node:fs");
const path = require("node:path");
const { Arch } = require("builder-util");

module.exports = async (context) => {
  const root = path.join(context.packager.projectDir, ".desktop-runtime", "runtime");
  const manifest = JSON.parse(fs.readFileSync(path.join(root, "manifest.json"), "utf8"));
  if (manifest.platform !== context.electronPlatformName || manifest.arch !== Arch[context.arch]) {
    throw new Error("Python runtime does not match the desktop target. Prepare and package on the target platform and architecture.");
  }
};
