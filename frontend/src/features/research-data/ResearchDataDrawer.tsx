import type { ReactNode } from "react";
import { Drawer } from "../../components/ui/index.js";

import { t } from "../../i18n/index.js";
import { ordinarySourceLabel, isCapabilityAvailable } from "./researchDataSourceModel.js";
import type { ResearchCapabilitySummaryV1, ResearchRuntimeMode, ResearchSourceKind } from "./researchDataTypes.js";
import { ResearchDatasetRail } from "./ResearchDatasetRail.js";
import { ResearchDatasetManagement } from "./ResearchDatasetManagement.js";
import type { ResearchDataLibraryController, ResearchImportSubmitInput } from "./useResearchDataLibrary.js";
import type { ChartSettings } from "../settings/chartAppearanceSettings.js";
import type { LocalAnalysisEvent } from "../local-data/localAnalysisTypes.js";
import type { LocalDatasetManifest } from "../local-data/localDataTypes.js";

export function ResearchDataDrawer(props: {
  open: boolean;
  runtimeMode: ResearchRuntimeMode;
  capabilities: ResearchCapabilitySummaryV1 | null;
  currentChartEnabled?: boolean;
  availableKinds?: ResearchSourceKind[];
  library?: ResearchDataLibraryController;
  settings: ChartSettings;
  events: readonly LocalAnalysisEvent[];
  analysis?: ReactNode;
  onSelectKind(kind: ResearchSourceKind): void;
  onSelectDataset?(datasetId: string): void;
  onRevisionActivated?(manifest: LocalDatasetManifest): void;
  onSettingsImported?(settings: ChartSettings): void;
  onProjectRestored?(manifest: LocalDatasetManifest): void;
  onImport?(input: ResearchImportSubmitInput): Promise<unknown>;
  onMarketTradesImported?(dataset: LocalDatasetManifest): Promise<void>;
  onClose(): void;
}) {
  if (!props.open) return null;
  return <ResearchDataDrawerBody {...props} />;
}

function ResearchDataDrawerBody({
  runtimeMode,
  capabilities,
  currentChartEnabled = false,
  availableKinds,
  library,
  settings,
  events,
  analysis = null,
  onSelectKind,
  onSelectDataset,
  onRevisionActivated,
  onSettingsImported,
  onProjectRestored,
  onImport,
  onMarketTradesImported,
  onClose,
}: {
  open: boolean;
  runtimeMode: ResearchRuntimeMode;
  capabilities: ResearchCapabilitySummaryV1 | null;
  currentChartEnabled?: boolean;
  availableKinds?: ResearchSourceKind[];
  library?: ResearchDataLibraryController;
  settings: ChartSettings;
  events: readonly LocalAnalysisEvent[];
  analysis?: ReactNode;
  onSelectKind(kind: ResearchSourceKind): void;
  onSelectDataset?(datasetId: string): void;
  onRevisionActivated?(manifest: LocalDatasetManifest): void;
  onSettingsImported?(settings: ChartSettings): void;
  onProjectRestored?(manifest: LocalDatasetManifest): void;
  onImport?(input: ResearchImportSubmitInput): Promise<unknown>;
  onMarketTradesImported?(dataset: LocalDatasetManifest): Promise<void>;
  onClose(): void;
}) {
  const kinds: ResearchSourceKind[] = availableKinds ?? ["CURRENT_CHART", "IMPORTED_DATASET", "COMPLETED_RUN"];
  return (
    <Drawer open onClose={onClose} title={t("research.drawer.title")} className="research-data-drawer">
      <div className="research-data-drawer-content" data-testid="research-data-drawer">
      {kinds.length > 1 && <div className="research-source-cards">
        {kinds.map((kind) => {
          const runnable = kind !== "CURRENT_CHART" || currentChartEnabled;
          const reason = kind === "CURRENT_CHART" && !runnable
            ? runtimeMode === "LOCAL_OFFLINE"
              ? t("research.source.offlineLiveUnavailable")
              : t("strategy.currentChartUnbound")
            : capabilities && !isCapabilityAvailable(capabilities, "barApprox") && kind === capabilities.sourceKind
              ? t("research.source.liveOffline")
              : null;
          return (
            <button
              key={kind}
              type="button"
              className="research-source-card"
              disabled={kind === "CURRENT_CHART" && !runnable}
              onClick={() => onSelectKind(kind)}
              data-testid={`research-source-card-${kind}`}
            >
              <strong>{ordinarySourceLabel(kind)}</strong>
              {reason ? <small>{reason}</small> : null}
            </button>
          );
        })}
      </div>}
      {library ? (
        <ResearchDatasetRail
          datasets={library.datasets}
          selectedId={library.selectedId}
          importing={library.importing}
          importJob={library.importJob}
          uploadProgress={library.uploadProgress}
          onSelect={(datasetId) => {
            library.setSelectedId(datasetId);
            onSelectDataset?.(datasetId);
          }}
          onImport={onImport ?? library.handleImport}
          {...(onMarketTradesImported ? { onMarketTradesImported } : {})}
          onCancelImport={library.cancelImport}
          management={(
            <ResearchDatasetManagement
              manifest={library.selected}
              settings={settings}
              events={events}
              onChanged={library.refresh}
              {...(onRevisionActivated === undefined ? {} : { onRevisionActivated })}
              onSettingsImported={onSettingsImported ?? (() => undefined)}
              {...(onProjectRestored === undefined ? {} : { onProjectRestored })}
              onError={library.setError}
            />
          )}
          analysis={analysis}
        />
      ) : null}
      </div>
    </Drawer>
  );
}
