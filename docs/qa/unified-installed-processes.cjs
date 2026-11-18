const assert = require("node:assert/strict");
const { execFileSync } = require("node:child_process");
const windows = process.platform === "win32";

const processTable = () => (windows
  ? execFileSync("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command",
    "Get-CimInstance Win32_Process | Where-Object CreationDate | ForEach-Object { '{0} {1} {2} {3}' -f $_.ProcessId,$_.ParentProcessId,$_.CreationDate.ToFileTimeUtc(),$_.Name }"],
  { encoding: "utf8" })
  : execFileSync("ps", ["-axo", "pid=,ppid=,lstart=,comm="], {
    encoding: "utf8", env: { ...process.env, LC_ALL: "C" },
  }))
  .trim().split("\n").flatMap(line => {
    const match = line.trim().match(windows ? /^(\d+)\s+(\d+)\s+(\d+)\s+(.+)$/ : /^(\d+)\s+(\d+)\s+(.{24})\s+(.+)$/);
    if (!match) return [];
    const [, pid, parent, started, name] = match;
    return [{ pid: Number(pid), parent: Number(parent), started, name }];
  });

function trackInstalledProcesses(rootPid) {
  // Process IDs can be reused between enumerations, especially by the
  // Windows process that takes the snapshot itself.
  const tracked = new Map();
  function observe() {
    const all = processTable();
    const current = new Map(all.map(process => [process.pid, process]));
    if (!tracked.size) {
      const root = current.get(rootPid);
      assert.ok(root, "packaged app process is missing");
      tracked.set(rootPid, root);
    }
    for (let level = 0; level < 10; level++) {
      for (const process of all) {
        const owner = tracked.get(process.parent);
        if (owner && current.get(owner.pid)?.started === owner.started) {
          tracked.set(process.pid, process);
        }
      }
    }
  }
  observe();
  return {
    observe,
    remaining: () => processTable().filter(process => tracked.get(process.pid)?.started === process.started),
    get size() { return tracked.size; },
  };
}

module.exports = { trackInstalledProcesses };
