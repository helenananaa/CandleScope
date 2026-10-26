import type { AiControlStatus } from "./aiControlTypes.js";

export function workflowConnectionConfig(workflow: AiControlStatus["workflow"], format: "json" | "toml"): string {
  if (!workflow?.enabled || !workflow.config) return "";
  if (format === "json") return JSON.stringify(workflow.config, null, 2);
  const server = workflow.config.mcpServers.candlescope;
  return `[mcp_servers.candlescope]\ncommand = ${JSON.stringify(server.command)}\nargs = ${JSON.stringify(server.args)}\n\n[mcp_servers.candlescope.env]\nELECTRON_RUN_AS_NODE = "1"\n`;
}
