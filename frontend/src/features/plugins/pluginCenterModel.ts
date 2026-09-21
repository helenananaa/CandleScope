import type { PluginCatalogPlugin } from "./pluginPlatformTypes.js";

export type PluginFilter = "all" | "active" | "disabled" | "attention";

export function pluginStatus(plugin: PluginCatalogPlugin): "active" | "disabled" | "staged" | "attention" {
  if (!plugin.permissions.activationReady || (plugin.state === "active" && !plugin.available) || plugin.runtime.entrypoints.some((entry) => ["failed", "crashed", "unavailable"].includes(entry.state))) return "attention";
  return plugin.state;
}

export function filterPlugins(plugins: PluginCatalogPlugin[], query: string, filter: PluginFilter) {
  const search = query.trim().toLocaleLowerCase();
  return plugins.filter((plugin) => {
    const matches = `${plugin.name} ${plugin.id} ${plugin.publisher} ${plugin.contributions.map((item) => item.title).join(" ")}`.toLocaleLowerCase().includes(search);
    const status = pluginStatus(plugin);
    return matches && (filter === "all" || (filter === "attention" ? status === "attention" || status === "staged" : status === filter));
  });
}
