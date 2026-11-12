import "./styles/layers.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./styles/fonts.js";
import AppProviders, { ChartErrorBoundary } from "./app/AppProviders.js";
import ReplayApp from "./features/replay/ReplayApp.js";
import { replayEntryFromWindow } from "./features/replay/replayEntry.js";
import { readPersistedLocale } from "./features/settings/chartAppearanceSettings.js";
import { bindDocumentLocale, initializeLocale } from "./i18n/index.js";
import "./index.css";

async function boot(): Promise<void> {
  await initializeLocale(readPersistedLocale());
  bindDocumentLocale({
    titleKey: "replay.documentTitle",
    descriptionKey: "replay.documentDescription",
  });

  const root = document.getElementById("root");
  if (!(root instanceof HTMLElement)) throw new Error("Replay document root is missing");

  createRoot(root).render(
    <StrictMode>
      <ChartErrorBoundary>
        <AppProviders><ReplayApp entry={replayEntryFromWindow()} /></AppProviders>
      </ChartErrorBoundary>
    </StrictMode>,
  );
}

void boot();
