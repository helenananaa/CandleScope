/** Test-only driver using the production desktop executor; no Electron qualification. */
import readline from "node:readline";
import { UnifiedDesktopHost } from "../../desktop/unified-entry-host.mjs";
const events = [];
let host;
for await (const line of readline.createInterface({ input: process.stdin })) {
  const message = JSON.parse(line);
  if (message.action === "start") {
    host = new UnifiedDesktopHost({ context: { host: { events } }, request: async (route, body) => {
      const response = await fetch(message.base + route, { method: "POST", headers: { ...message.headers, "Content-Type": "application/json" }, body: JSON.stringify(body) });
      if (!response.ok) throw new Error(`Lifecycle response ${response.status}`);
      return response.json();
    } });
    await host.start();
  } else if (message.action === "refresh") await host.refresh();
  else if (message.action === "stop") await host.stop();
  process.stdout.write(JSON.stringify({ diagnostics: host.diagnostics(), events }) + "\n");
  if (message.action === "stop") break;
}
process.stdin.destroy();
