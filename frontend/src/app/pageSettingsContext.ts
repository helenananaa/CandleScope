import { createContext } from "react";
import type { ChartSettingsRuntime } from "../features/settings/chartAppearanceSettings.js";

/** Settings owned by the page's root, so the header can open Settings without a second copy. */
export const PageSettingsContext = createContext<ChartSettingsRuntime | null>(null);
