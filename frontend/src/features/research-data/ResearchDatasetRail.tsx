import { useState, type ReactNode } from "react";

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
  return (
    <aside className="local-data-rail" aria-label={t("local.libraryAria")} data-testid="research-dataset-rail">
      <div className="research-library-tabs" role="tablist" aria-label={t("local.libraryAria")}>
        {(["library", "import"] as const).map((tab) => (
          <button key={tab} type="button" role="tab" aria-selected={view === tab} onClick={() => setView(tab)}>
            {t(tab === "library" ? "local.datasets" : "local.import")}
          </button>
        ))}
      </div>
      <div hidden={view !== "import"} role="tabpanel" aria-label={t("local.import")}>
      {onMarketTradesImported && <ResearchMarketTradeImportForm
        selected={datasets.find((dataset) => dataset.dataset_id === selectedId) ?? null}
        onImported={onMarketTradesImported}
      />}
      <ResearchDataImportForm
        importing={importing}
        importJob={importJob}
        uploadProgress={uploadProgress}
        selected={datasets.find((dataset) => dataset.dataset_id === selectedId) ?? null}
        onCancel={onCancelImport}
        onImport={onImport}
      />
      </div>
      <section className="local-dataset-library" hidden={view !== "library"} role="tabpanel" aria-label={t("local.datasets")}>
        <header>
          <div>
            <span>{t("local.kicker.library")}</span>
            <strong>{t("local.datasets")}</strong>
          </div>
          <small>{t("local.count", { count: datasets.length })}</small>
        </header>
        <div className="local-dataset-list">
          {datasets.length === 0 ? (
            <div className="local-dataset-empty">{t("local.empty")}</div>
          ) : datasets.map((dataset) => (
            <button
              type="button"
              key={dataset.dataset_id}
              className={dataset.dataset_id === selectedId ? "active" : ""}
              data-testid={`research-dataset-${dataset.dataset_id}`}
              onClick={() => onSelect(dataset.dataset_id)}
            >
              <span><strong>{dataset.name}</strong><em>{dataset.symbol} · {dataset.interval} · {dataset.market_trade_input ? t(dataset.market_trade_input.kind === "MARKET_AGG_TRADE" ? "settings.exchange.channel.aggTrade" : "settings.exchange.channel.trade") : dataset.volume_available ? "OHLCV" : "OHLC-only"}</em></span>
              <span><b>{formatResearchRows(dataset.rows)}</b><small>{t("local.gaps", { count: dataset.excluded_range_count })}</small></span>
            </button>
          ))}
        </div>
      </section>
      <details className="local-management-details"><summary>{t("local.ops")}</summary>{management}</details>
      {analysis}
    </aside>
  );
}
