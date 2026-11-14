import { useId, useState, type ReactNode } from "react";

import { Disclosure, EmptyState, TabPanel, Tabs } from "../../components/ui/index.js";
import { t } from "../../i18n/index.js";
import type { LocalDatasetManifest, LocalImportJob } from "./researchDataApi.js";
import { formatResearchRows } from "./researchDataFormat.js";
import { ResearchMarketTradeImportForm } from "./ResearchMarketTradeImportForm.js";
import { ResearchDataImportForm } from "./ResearchDataImportForm.js";
import type { ResearchImportSubmitInput } from "./useResearchDataLibrary.js";

export function ResearchDatasetRail({
  datasets,
  selectedId,
  importing,
  importJob,
  uploadProgress,
  onSelect,
  onImport,
  onMarketTradesImported,
  onCancelImport,
  management,
  analysis,
}: {
  datasets: LocalDatasetManifest[];
  selectedId: string | null;
  importing: boolean;
  importJob: LocalImportJob | null;
  uploadProgress: number | null;
  onSelect(datasetId: string): void;
  onImport(input: ResearchImportSubmitInput): Promise<unknown>;
  onMarketTradesImported?(dataset: LocalDatasetManifest): Promise<void>;
  onCancelImport(): void;
  management: ReactNode;
  analysis: ReactNode;
}) {
  const [view, setView] = useState<"library" | "import">(datasets.length === 0 ? "import" : "library");
  const tabsId = useId();
  const selected = datasets.find((dataset) => dataset.dataset_id === selectedId) ?? null;
  return (
    <section className="research-dataset-rail" aria-label={t("local.libraryAria")} data-testid="research-dataset-rail">
      <Tabs
        id={tabsId}
        label={t("local.libraryAria")}
        value={view}
        onChange={setView}
        tabs={[
          { value: "library", label: t("local.datasets"), badge: datasets.length },
          { value: "import", label: t("local.import") },
        ]}
      />
      {/* Both panels stay mounted, so a half-filled import form survives a look at the library. */}
      <div hidden={view !== "library"}>
        <TabPanel tabsId={tabsId} value="library" className="research-dataset-panel">
          {datasets.length === 0 ? (
            <EmptyState compact title={t("local.empty")} />
          ) : (
            <ul className="research-dataset-list">
              {datasets.map((dataset) => (
                <li key={dataset.dataset_id}>
                  <button
                    type="button"
                    className="research-dataset-row"
                    data-active={dataset.dataset_id === selectedId ? "true" : undefined}
                    aria-current={dataset.dataset_id === selectedId ? "true" : undefined}
                    data-testid={`research-dataset-${dataset.dataset_id}`}
                    onClick={() => onSelect(dataset.dataset_id)}
                  >
                    <span>
                      <strong>{dataset.name}</strong>
                      <small>{dataset.symbol} · {dataset.interval} · {dataset.market_trade_input ? t(dataset.market_trade_input.kind === "MARKET_AGG_TRADE" ? "settings.exchange.channel.aggTrade" : "settings.exchange.channel.trade") : dataset.volume_available ? "OHLCV" : "OHLC-only"}</small>
                    </span>
                    <span className="research-dataset-rows">
                      <b>{formatResearchRows(dataset.rows)}</b>
                      <small>{t("local.gaps", { count: dataset.excluded_range_count })}</small>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </TabPanel>
      </div>
      <div hidden={view !== "import"}>
        <TabPanel tabsId={tabsId} value="import" className="research-dataset-panel">
          <ResearchDataImportForm
            importing={importing}
            importJob={importJob}
            uploadProgress={uploadProgress}
            selected={selected}
            onCancel={onCancelImport}
            onImport={onImport}
          />
          {onMarketTradesImported && <ResearchMarketTradeImportForm selected={selected} onImported={onMarketTradesImported} />}
        </TabPanel>
      </div>
      <Disclosure className="research-dataset-ops" summary={t("local.ops")}>{management}</Disclosure>
      {analysis}
    </section>
  );
}
