/** Keep the historical unpacked command; distributables are explicitly opt-in. */
export function desktopBuilderArguments(args = [], hasLocalElectron = false) {
  return [
    ...(args.includes("--distributable") ? [] : ["--dir"]),
    ...(hasLocalElectron ? ["-c.electronDist=node_modules/electron/dist"] : []),
    ...args.filter((argument) => argument !== "--distributable"),
  ];
}
