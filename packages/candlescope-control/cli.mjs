import { StdioServerTransport } from "@modelcontextprotocol/server/stdio";
import { readFile, writeFile } from "node:fs/promises";
import { ControlClient, defaultConnectionFile } from "./client.mjs";
import { createControlMcp } from "./server.mjs";
import { uploadFile, downloadFile } from "./files.mjs";

const args = process.argv.slice(2);
const operation = args.shift();
const options = new Map();
async function main() {
  while (args.length) {
    const key = args.shift(); const value = args.shift();
    if (!["--connection", "--window", "--params-file", "--id", "--out", "--file"].includes(key) || !value || options.has(key)) throw new Error("Invalid CLI options");
    options.set(key, value);
  }
  if (!operation || operation === "help") {
    console.log("CandleScope control: mcp | capabilities | inspect --window ID | commands --window ID | query/execute/open/configure --params-file FILE | request --id ID | capture --window ID --out FILE | upload --window ID --file FILE | download --window ID --id fileRef --out FILE\nEvery command accepts --connection FILE. Enable desktop workflow tools in Settings > AI connection and choose read/control access. Discover command schemas and context tokens with commands before execute.");
    return;
  }
  const client = new ControlClient(options.get("--connection") ?? defaultConnectionFile());
  const capabilities = await client.connect();
  if (operation === "mcp") {
    const server = createControlMcp(client, capabilities);
    await server.connect(new StdioServerTransport());
    return;
  }
  let result;
  if (operation === "capabilities") result = capabilities;
  else if (operation === "inspect") result = await client.call("workspace.inspect", { windowId: options.get("--window") ?? "main-window" });
  else if (operation === "commands") result = await client.call("app.commands", { windowId: options.get("--window") ?? "main-window" });
  else if (["configure", "query", "execute", "open"].includes(operation)) {
    if (!options.get("--params-file")) throw new Error("--params-file is required");
    const methods = { configure: "workspace.configure", query: "app.query", execute: "app.execute", open: "app.open" };
    result = await client.call(methods[operation], JSON.parse(await readFile(options.get("--params-file"), "utf8")));
  } else if (operation === "upload") {
    if (!options.get("--file") || !options.get("--window")) throw new Error("--file and --window are required");
    result = await uploadFile(client, options.get("--window"), options.get("--file"));
  } else if (operation === "download") {
    if (!options.get("--out") || !options.get("--window") || !options.get("--id")) throw new Error("--out, --window and --id=fileRef are required");
    result = await downloadFile(client, options.get("--window"), options.get("--id"), options.get("--out"));
  } else if (operation === "request") result = await client.call("request.get", { requestId: options.get("--id") });
  else if (operation === "capture") {
    if (!options.get("--out")) throw new Error("--out is required");
    const capture = await client.call("chart.capture", { windowId: options.get("--window") ?? "main-window" });
    await writeFile(options.get("--out"), Buffer.from(capture.data, "base64"));
    result = { output: options.get("--out"), windowId: capture.windowId };
  } else throw new Error("Unknown operation; run help");
  console.log(JSON.stringify(result, null, 2));
  if (result.state === "failed") process.exitCode = 1;
}
main().catch((error) => { console.error(error.message); process.exitCode = 1; });
