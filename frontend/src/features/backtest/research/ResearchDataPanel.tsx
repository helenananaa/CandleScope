import { useState } from "react";
import { DateTimeInput, Disclosure, Field, Select } from "../../../components/ui/index.js";
import { getLocale, t } from "../../../i18n/index.js";
import type { BacktestResearchRuntime } from "./backtestResearchTypes.js";
import { researchFidelityLabel, shortFingerprint } from "./researchLabels.js";
import ResearchPanelFrame from "./ResearchPanelFrame.js";

export default function ResearchDataPanel({ runtime }: { runtime: BacktestResearchRuntime }) {
  const {
    advancedEnabled,
    datasets,
    selectedDatasetId,
    snapshot,
    startTimeMs,
    endTimeMs,
  } = runtime.view;
  // A start or end the user is still typing (not yet a time) stays in the field until it parses.
  const [unfinished, setUnfinished] = useState({ start: false, end: false });
  const dataset = datasets.find((item) => item.dataset_id === selectedDatasetId) ?? null;
  return (
    <ResearchPanelFrame
      eyebrow={t("research.panel.data")}
      title={dataset?.name ?? t("research.data.noContext")}
    >
      {advancedEnabled ? (
        <>
          <Field label={t("research.data.dataset")}>
            <Select size="sm" value={selectedDatasetId} onChange={(event) => runtime.actions.selectDataset(event.target.value)}>
              {datasets.map((item) => (
                <option key={`${item.dataset_id}:${item.data_epoch}`} value={item.dataset_id}>
                  {item.name} · {item.symbol} · {item.interval}
                </option>
              ))}
            </Select>
          </Field>
          <div className="research-range-grid">
            <Field label={t("research.data.start")}><DateTimeInput size="sm" seconds value={unfinished.start ? null : startTimeMs} onChange={(value) => {
              setUnfinished((current) => ({ ...current, start: value === null }));
              if (value !== null) runtime.actions.setRange(value, endTimeMs);
            }} /></Field>
            <Field label={t("research.data.end")}><DateTimeInput size="sm" seconds value={unfinished.end ? null : endTimeMs} onChange={(value) => {
              setUnfinished((current) => ({ ...current, end: value === null }));
              // The field edits whole seconds; an end at .999 (the last millisecond of a second) keeps it.
              if (value !== null) runtime.actions.setRange(startTimeMs, value + (endTimeMs % 1000));
            }} /></Field>
          </div>
        </>
      ) : <p className="research-empty">{t("research.data.readOnly")}</p>}
      {dataset && (
        <dl className="research-facts">
          <div><dt>{t("research.data.rows")}</dt><dd>{dataset.rows}</dd></div>
          <div><dt>{t("research.data.epoch")}</dt><dd title={dataset.data_epoch}>{shortFingerprint(dataset.data_epoch)}</dd></div>
          <div><dt>{t("research.data.coverage")}</dt><dd>{new Date(dataset.first_open_ms ?? 0).toLocaleDateString(getLocale())} → {new Date(dataset.last_close_ms ?? 0).toLocaleDateString(getLocale())}</dd></div>
        </dl>
      )}
      {snapshot ? (
        <Disclosure defaultOpen summary={t("research.data.snapshot", { count: snapshot.row_count })}>
          <dl className="research-facts">
            <div><dt>{t("research.data.hash")}</dt><dd title={snapshot.snapshot_hash}>{shortFingerprint(snapshot.snapshot_hash)}</dd></div>
            <div><dt>{t("research.data.marketRows")}</dt><dd>{snapshot.market_row_count ?? snapshot.row_count}</dd></div>
            <div><dt>{t("research.data.fidelity")}</dt><dd>{snapshot.fidelity_capabilities.map(researchFidelityLabel).join(" · ") || "—"}</dd></div>
          </dl>
          <Disclosure summary={t("plugin.techDetails")}>
            <pre className="research-json-readout">{JSON.stringify({
              quality: snapshot.quality,
              role_hashes: snapshot.role_hashes ?? {},
              coverage: dataset?.coverage ?? {},
              gap: dataset?.gap ?? {},
              contract_history: dataset?.contract_history ?? {},
            }, null, 2)}</pre>
          </Disclosure>
        </Disclosure>
      ) : advancedEnabled ? <p className="research-empty">{t("research.data.waiting")}</p> : null}
    </ResearchPanelFrame>
  );
}
