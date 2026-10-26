import type { ExportRuntime } from "../export/useExportRuntime.js";
import { command, type ControlCommandGroup } from "./commandRegistry.js";
import { bool, choice, empty, number, object, optional, text } from "./commandSchema.js";
import { publishControlFile } from "./controlFiles.js";

export function exportCommands(id: string, runtime: ExportRuntime): ControlCommandGroup {
  const v = runtime.view;
  return { id: `export:${id}`, title: "Chart export preview and files", context: () => ({ options: v.options, metadata: v.metadata, previewKey: v.preview.optionsKey, busy: runtime.status.inProgress }),
    snapshot: () => ({ open: v.isOpen, options: v.options, metadata: v.metadata, error: v.error, notice: v.notice, busy: runtime.status.inProgress, previewReady: !!v.preview.blob, previewKey: v.preview.optionsKey }), commands: [
      command("open", "Open export and start the existing preview lifecycle.", empty, () => { if (!v.isOpen) runtime.actions.togglePanel(); }),
      command("close", "Close export preview.", empty, () => runtime.actions.closePanel()),
      command("options", "Edit export options; wait for the new preview before saving.", object({ scope: optional(choice(["chart", "main-pane", "page"])), format: optional(choice(["png", "jpeg", "webp"])), scale: optional(number(0.25, 4)), quality: optional(number(0.1, 1)), backgroundColor: optional(text(64)), hideDrawings: optional(bool), includeContext: optional(bool), watermarkEnabled: optional(bool), watermarkText: optional(text(256)), filenamePrefix: optional(text(128)) }), (patch) => runtime.actions.updateOptions({ ...v.options, ...patch }), { available: () => !runtime.status.inProgress }),
      command("save", "Export through the existing drawing lease/revalidation workflow to a downloadable fileRef.", empty, async () => {
        let result: unknown; await runtime.actions.exportTo(async (blob, name) => { result = await publishControlFile(blob, name); });
        if (!result) throw new Error("EXPORT_NOT_READY"); return result;
      }, { available: () => !runtime.status.inProgress && !!v.preview.blob }),
    ] };
}
