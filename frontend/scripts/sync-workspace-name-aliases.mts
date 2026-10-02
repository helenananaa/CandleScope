import fs from "node:fs";
import { LOCALES, loadLocaleCatalog, localeDefinition } from "../src/i18n/registry.js";

await Promise.all(LOCALES.map(loadLocaleCatalog));
const keys = Object.keys(localeDefinition("zh-CN").messages).filter((key) => (
  key === "workspace.name.default" || key.startsWith("workspace.name.template.")
));
const names = Object.fromEntries(keys.map((key) => [key, [...new Set(LOCALES.map((locale) => (
  (localeDefinition(locale).messages as Readonly<Record<string, string>>)[key]
)))]]));
fs.writeFileSync(new URL("../src/i18n/workspaceNameAliases.ts", import.meta.url),
  "// Legacy persisted workspace names; regenerate with scripts/sync-workspace-name-aliases.mts.\n"
  + "export const workspaceNameAliases: Readonly<Record<string, readonly string[]>> = "
  + JSON.stringify(names, null, 2) + ";\n");
