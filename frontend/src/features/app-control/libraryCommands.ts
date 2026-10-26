import type { ResearchDataLibraryController } from "../research-data/useResearchDataLibrary.js";
import { command, type ControlCommandGroup } from "./commandRegistry.js";
import { bool, choice, empty, object, optional, record, text } from "./commandSchema.js";
import { readControlFile, publishControlFile } from "./controlFiles.js";
import { activateLocalRevision, compareLocalRevisions, exportLocalProject, importLocalProject, listLocalRevisions, listLocalTrash, restoreLocalTrash, trashLocalDataset, updateLocalDataset } from "../research-data/researchDataApi.js";

export function libraryCommands(library: ResearchDataLibraryController): ControlCommandGroup {
  const dataset = (id: string) => { const item = library.datasets.find((row) => row.dataset_id === id); if (!item) throw new Error("DATASET_UNAVAILABLE"); return item; };
  const idle = () => !library.importing;
  return { id: "data-library", title: "Imported research datasets", context: () => ({ selectedId: library.selectedId,
    datasets: library.datasets.map((item) => [item.dataset_id, item.data_epoch]), importing: library.importing }),
    snapshot: () => ({ datasets: library.datasets, selectedId: library.selectedId, presets: library.indicatorPresets,
      loading: library.loadingLibrary, importing: library.importing, job: library.importJob, uploadProgress: library.uploadProgress, error: library.error }), commands: [
      command("select", "Select a current imported dataset.", object({ datasetId: text(128) }), ({ datasetId }) => {
        if (!library.datasets.some((item) => item.dataset_id === datasetId)) throw new Error("DATASET_UNAVAILABLE"); library.setSelectedId(datasetId);
      }),
      command("refresh", "Refresh dataset manifests.", empty, () => library.refresh()),
      command("importCsv", "Import a committed window-bound file through the UI upload/job workflow. Inspect importing/job/error until finished.", object({ fileRef: text(96), name: text(128), symbol: text(96), interval: text(24), timezone: text(96), timestampUnit: choice(["auto", "s", "ms", "iso"]), volumeRequired: bool,
        datasetId: optional(text(128)), columns: optional(object({ time: optional(text(128)), open: optional(text(128)), high: optional(text(128)), low: optional(text(128)), close: optional(text(128)), volume: optional(text(128)) })) }),
        async ({ fileRef, ...input }) => { const file = await readControlFile(fileRef); void library.handleImport({ ...input, file }).catch(() => undefined); return { submitted: true }; }, { available: idle }),
      command("update", "Rename/archive an existing dataset.", object({ datasetId: text(128), name: optional(text(128)), archived: optional(bool) }), async ({ datasetId, ...patch }) => { dataset(datasetId); const result = await updateLocalDataset(datasetId, patch); await library.refresh(datasetId); return result; }, { available: idle }),
      command("revisions", "List revisions of an existing dataset.", object({ datasetId: text(128) }), ({ datasetId }) => { dataset(datasetId); return listLocalRevisions(datasetId); }, { readOnly: true }),
      command("compareRevisions", "Compare data revisions using the existing domain service.", object({ datasetId: text(128), leftEpoch: text(128), rightEpoch: text(128) }), ({ datasetId, leftEpoch, rightEpoch }) => { dataset(datasetId); return compareLocalRevisions(datasetId, leftEpoch, rightEpoch); }, { readOnly: true }),
      command("activateRevision", "Activate a revision with the current dataset epoch guard.", object({ datasetId: text(128), dataEpoch: text(128) }), async ({ datasetId, dataEpoch }) => { const result = await activateLocalRevision(dataset(datasetId), dataEpoch); await library.refresh(datasetId); return result; }, { available: idle }),
      command("trash", "Move a listed dataset to recoverable trash with the UI's explicit confirmation.", object({ datasetId: text(128), confirmed: choice([true]) }), async ({ datasetId }) => { dataset(datasetId); const result = await trashLocalDataset(datasetId); await library.refresh(); return result; }, { available: idle }),
      command("trashList", "List recoverable dataset trash.", empty, () => listLocalTrash(), { readOnly: true }),
      command("restore", "Restore a trash entry.", object({ trashId: text(128) }), async ({ trashId }) => { const result = await restoreLocalTrash(trashId); await library.refresh(result.dataset_id); return result; }, { available: idle }),
      command("exportProject", "Export a dataset and optional chart/settings/analysis client state to a window-bound file.", object({ datasetId: text(128), clientState: optional(record) }), async ({ datasetId, clientState }) => { let result: unknown; await exportLocalProject(dataset(datasetId), clientState ?? {}, async (blob, name) => { result = await publishControlFile(blob, name); }); return result; }, { available: idle }),
      command("importProject", "Import a committed project file using the existing project validation.", object({ fileRef: text(96) }), async ({ fileRef }) => { const result = await importLocalProject(await readControlFile(fileRef)); await library.refresh(result.dataset_id); return result; }, { available: idle }),
      command("cancelImport", "Cancel the current import using the existing abort/job cancellation action.", empty, () => library.cancelImport(), { interrupt: true, available: () => library.importing }),
    ] };
}
