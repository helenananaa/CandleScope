import test from "node:test";
import assert from "node:assert/strict";
import { workflowConnectionConfig } from "./workflowConnectionConfig.js";

test("workflow connection exports only an active session with the bundled runtime", () => {
  assert.equal(workflowConnectionConfig(null, "json"), "");
  const workflow = { enabled: true, adapterAvailable: true, scopes: ["observe"],
    config: { mcpServers: { candlescope: { command: "C:\\Program Files\\CandleScope.exe", args: ["C:\\Profile\\cli.mjs", "mcp"], env: { ELECTRON_RUN_AS_NODE: "1" } } } } };
  assert.deepEqual(JSON.parse(workflowConnectionConfig(workflow, "json")), workflow.config);
  const toml = workflowConnectionConfig(workflow, "toml");
  assert.ok(toml.includes(JSON.stringify(workflow.config.mcpServers.candlescope.command)));
  assert.ok(toml.includes('ELECTRON_RUN_AS_NODE = "1"'));
  assert.equal(workflowConnectionConfig({ ...workflow, enabled: false }, "toml"), "");
});
