import type {
  SettingsCategory,
  SettingsCategoryDescriptor,
} from "./settingsTypes.js";

export const SETTINGS_CATEGORIES = [
  { key: "appearance", labelKey: "settings.category.appearance", icon: "palette" },
  { key: "network", labelKey: "settings.category.network", icon: "globe" },
  { key: "exchanges", labelKey: "settings.category.exchanges", icon: "exchange" },
  { key: "data", labelKey: "settings.category.data", icon: "database" },
  { key: "plugins", labelKey: "settings.category.plugins", icon: "puzzle" },
  { key: "about", labelKey: "settings.category.about", icon: "info" },
] as const satisfies readonly SettingsCategoryDescriptor[];

export function resolveSettingsTab(
  categoryKey: SettingsCategory | string,
): (typeof SETTINGS_CATEGORIES)[number] {
  return SETTINGS_CATEGORIES.find((category) => category.key === categoryKey) || SETTINGS_CATEGORIES[0];
}
