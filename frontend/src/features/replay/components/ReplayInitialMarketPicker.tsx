import { useReplayOperations } from "../useReplayOperations.js";
import { describeError } from "../../../i18n/serverErrors.js";
import { useEffect, useMemo, useState } from "react";
import { useControlCommands } from "../../app-control/useControlCommands.js";
import { command } from "../../app-control/commandRegistry.js";
import { bool, choice, empty, nullable, object, text } from "../../app-control/commandSchema.js";
import { t } from "../../../i18n/index.js";
import { Button, Checkbox, EmptyState, Field, InlineAlert, Input, SegmentedControl, Select } from "../../../components/ui/index.js";
import { useLocale } from "../../../i18n/useLocale.js";
import type { ReplayCatalog, ReplayCatalogEntry } from "../replayTypes.js";
import type { TrainingRunCard } from "../replayV2Types.js";
import { ReplayV2ApiError } from "../replayV2Api.js";
import {
  prepareReplayInitialMarketSelection,
  ReplayInitialMarketDowngradeRequired,
  selectReplayInitialMarketWithEpochRetry,
} from "../replayInitialMarket.js";
import {
  formatReplayMarketCoverage,
  formatReplayUtcDateTime,
  isReplayInitialMarketAvailable,
  trainingExchangeLabel,
  trainingMarketKey,
  trainingMarketTypeLabel,
  trainingSourceKindLabel,
  trainingVenueLabel,
} from "../trainingHubLabels.js";

export interface ReplayInitialMarketPickerProps {
  readonly run: TrainingRunCard;
  readonly onInitialized: (run: TrainingRunCard) => void;
}

interface MarketTypeFilter {
  readonly exchange: string;
  readonly marketType: string;
}

function marketTypeKey(filter: MarketTypeFilter): string {
  return `${filter.exchange}:${filter.marketType}`;
}

function sameMarketType(
  left: MarketTypeFilter,
  right: MarketTypeFilter,
): boolean {
  return left.exchange === right.exchange && left.marketType === right.marketType;
}

function ReplayMarketPickerRow({
  entry,
  available,
  recommended,
  selecting,
  sourceKind,
  coverage,
  onSelect,
}: {
  readonly entry: ReplayCatalogEntry;
  readonly available: boolean;
  readonly recommended: boolean;
  readonly selecting: boolean;
  readonly sourceKind: TrainingRunCard["source_kind"];
  readonly coverage: string;
  readonly onSelect: () => void;
}) {
  const reason = entry.start_compatibility?.message
    ?? t("replay.picker.compatUnknown");
  return (
    <article
      className="replay-market-picker-row"
      data-market-symbol={entry.identity.symbol}
      data-market-exchange={entry.identity.exchange}
      data-market-type={entry.identity.market_type}
      data-available={available ? "true" : "false"}
      data-recommended={recommended ? "true" : "false"}
    >
      <div className="replay-market-picker-row-main">
        <strong>{entry.identity.symbol}</strong>
        <p>
          {trainingVenueLabel(entry)}
          {" · "}{t("replay.picker.interval")} {entry.selected_base_interval ?? "—"}
          {" · "}{t("replay.picker.coverage")} {coverage}
        </p>
        {!available && <p className="replay-market-picker-reason">{reason}</p>}
      </div>
      {available && (
        <Button
          size="sm"
          variant="primary"
          aria-label={`${t("replay.picker.select")} ${entry.identity.symbol}`}
          disabled={selecting}
          onClick={onSelect}
        >
          {selecting
            ? sourceKind === "AGG_TRADE" && entry.quality !== "USER_MARKET_TRADE_COVERAGE"
              ? t("replay.picker.downloading")
              : t("replay.picker.init")
            : t("replay.picker.select")}
        </Button>
      )}
    </article>
  );
}

export default function ReplayInitialMarketPicker({
  run,
  onInitialized,
}: ReplayInitialMarketPickerProps) {
  const { api } = useReplayOperations(run.run_id, "catalog");
  useLocale();
  const [catalog, setCatalog] = useState<ReplayCatalog | null>(null);
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [selecting, setSelecting] = useState<string | null>(null);
  const [availableOnly, setAvailableOnly] = useState(true);
  const [marketType, setMarketType] = useState<MarketTypeFilter | null>(null);
  const [unavailableOpen, setUnavailableOpen] = useState(false);
  const [downgrade, setDowngrade] = useState<{
    readonly entry: ReplayCatalogEntry;
    readonly message: string;
  } | null>(null);

  const loadCatalog = () => {
    setError(null);
    setDowngrade(null);
    setCatalog(null);
    void api.marketCatalog(run.run_id).then(setCatalog).catch((reason: unknown) => {
      setError(reason instanceof Error ? describeError(reason, reason.message) : t("replay.picker.catalogFailed"));
    });
  };

  useEffect(() => {
    const abort = new AbortController();
    void api.marketCatalog(run.run_id, abort.signal)
      .then(setCatalog)
      .catch((reason: unknown) => {
        if (abort.signal.aborted) return;
        setError(reason instanceof Error ? describeError(reason, reason.message) : t("replay.picker.catalogFailed"));
      });
    return () => abort.abort();
  }, [api, run.run_id]);

  const marketTypes = useMemo(() => {
    const seen = new Map<string, MarketTypeFilter>();
    for (const entry of catalog?.entries ?? []) {
      const filter = {
        exchange: entry.identity.exchange,
        marketType: entry.identity.market_type,
      };
      seen.set(marketTypeKey(filter), filter);
    }
    return [...seen.values()];
  }, [catalog]);

  const entries = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (catalog?.entries ?? []).filter((entry) => {
      const matchesQuery = needle.length === 0
        || entry.identity.symbol.toLowerCase().includes(needle)
        || entry.identity.exchange.toLowerCase().includes(needle)
        || entry.identity.market_type.toLowerCase().includes(needle)
        || trainingVenueLabel(entry).toLowerCase().includes(needle);
      const matchesType = marketType === null
        || sameMarketType(marketType, {
          exchange: entry.identity.exchange,
          marketType: entry.identity.market_type,
        });
      return matchesQuery && matchesType;
    });
  }, [catalog, marketType, query]);

  const availableEntries = entries.filter(isReplayInitialMarketAvailable);
  const blockedEntries = entries.filter((entry) => !isReplayInitialMarketAvailable(entry));
  const visibleBlocked = !availableOnly || unavailableOpen ? blockedEntries : [];
  const timeCommitment = catalog?.time_commitment;
  const committedTimeLabel = timeCommitment?.committed_start_ms === null
    ? t("replay.picker.frozenHidden")
    : timeCommitment?.committed_start_ms === undefined
      ? t("replay.picker.reading")
      : formatReplayUtcDateTime(timeCommitment.committed_start_ms);
  const hedgeLocked = (catalog?.entries ?? []).some((entry) => {
    const text = `${entry.start_compatibility?.code ?? ""} ${entry.start_compatibility?.message ?? ""}`;
    return /HEDGE|双向/.test(text);
  });

  const selectMarket = async (entry: ReplayCatalogEntry, confirmed = false) => {
    if (catalog === null || entry.selected_base_interval === null || selecting !== null) return;
    setSelecting(trainingMarketKey(entry));
    setError(null);
    if (!confirmed) setDowngrade(null);
    try {
      let activeCatalog = catalog;
      let activeEntry = entry;
      if (!confirmed) {
        const prepared = await prepareReplayInitialMarketSelection({
          api: api,
          runId: run.run_id,
          catalog,
          entry,
        });
        activeCatalog = prepared.catalog;
        activeEntry = prepared.entry;
        setCatalog(activeCatalog);
        if (prepared.downgradeConfirmation !== null) {
          setDowngrade({ entry: activeEntry, message: prepared.downgradeConfirmation });
          setSelecting(null);
          return;
        }
      }
      const result = await selectReplayInitialMarketWithEpochRetry({
        api: api,
        runId: run.run_id,
        catalog: activeCatalog,
        entry: activeEntry,
        allowHedgeHybrid: confirmed,
      });
      setCatalog(result.catalog);
      setDowngrade(null);
      onInitialized(result.response.run);
    } catch (reason) {
      if (reason instanceof ReplayInitialMarketDowngradeRequired) {
        setCatalog(reason.catalog);
        setDowngrade({ entry: reason.entry, message: reason.message });
        setSelecting(null);
        return;
      }
      const message = reason instanceof ReplayV2ApiError
        ? `${reason.code}: ${reason.message}`
        : reason instanceof Error ? describeError(reason, reason.message) : t("replay.picker.initFailed");
      setError(message);
      setSelecting(null);
    }
  };

  useControlCommands(() => ({ id: "replay-initial-market", title: "Replay initial market selection", context: () => ({ runId: run.run_id, catalog, selecting, downgrade }),
    snapshot: () => ({ runId: run.run_id, catalog, selecting, downgrade, error, query, marketType, availableOnly, unavailableOpen }), commands: [
      command("refresh", "Refresh the public initial-market catalog.", empty, () => loadCatalog(), { available: () => selecting === null }),
      command("filters", "Set market picker filters.", object({ query: text(128, 0), marketType: nullable(object({ exchange: text(64), marketType: text(32) })), availableOnly: bool, unavailableOpen: bool }), (input) => { setQuery(input.query); setMarketType(input.marketType); setAvailableOnly(input.availableOnly); setUnavailableOpen(input.unavailableOpen); }),
      command("select", "Prepare and select an available catalog market. Inspect any downgrade confirmation first.", object({ marketKey: text(256) }), ({ marketKey }) => { const entry = catalog?.entries.find((entry) => trainingMarketKey(entry) === marketKey); if (!entry || !isReplayInitialMarketAvailable(entry)) throw new Error("MARKET_UNAVAILABLE"); return selectMarket(entry); }, { available: () => catalog !== null && selecting === null }),
      command("confirmDowngrade", "Confirm only the currently pending domain-generated downgrade.", object({ confirmed: choice([true]) }), () => { if (!downgrade) throw new Error("DOWNGRADE_UNAVAILABLE"); return selectMarket(downgrade.entry, true); }, { available: () => downgrade !== null && selecting === null }),
      command("cancelDowngrade", "Cancel the pending downgrade.", empty, () => setDowngrade(null)),
    ] }));
  const marketTypeValue = marketType === null ? "all" : marketTypeKey(marketType);
  const marketTypeOptions = [
    { value: "all", label: t("replay.picker.allMarkets") },
    ...marketTypes.map((filter) => ({
      value: marketTypeKey(filter),
      label: `${trainingExchangeLabel(filter.exchange)} ${trainingMarketTypeLabel(filter.marketType)}`,
    })),
  ];
  const chooseMarketType = (value: string) => setMarketType(marketTypes.find((filter) => marketTypeKey(filter) === value) ?? null);
  return (
    <main
      className="training-hub-page replay-market-picker"
      data-replay-run-state="AWAITING_MARKET"
    >
      <section className="training-hub-shell training-hub-runs">
        <header className="training-hub-heading">
          <div>
            <h1>{run.name}</h1>
            <p>{t("replay.picker.intro")}</p>
          </div>
          <div className="training-hub-heading-actions">
            <Button onClick={loadCatalog} disabled={selecting !== null}>{t("replay.picker.refresh")}</Button>
            <a className="ui-btn ui-btn-ghost" href="/replay.html">{t("replay.picker.backToHub")}</a>
          </div>
        </header>

        <dl className="replay-market-picker-commit" aria-label={t("replay.picker.constraints")}>
          <div><dt>{t("replay.picker.startTime")}</dt><dd>{committedTimeLabel}</dd></div>
          <div><dt>{t("replay.picker.settlement")}</dt><dd>{run.settlement_asset}</dd></div>
          <div><dt>{t("replay.picker.source")}</dt><dd>{trainingSourceKindLabel(run.source_kind)}</dd></div>
          {hedgeLocked && <div><dt>{t("replay.picker.position")}</dt><dd>{t("replay.picker.hedge")}</dd></div>}
        </dl>

        {run.source_kind === "AGG_TRADE" && !catalog?.entries.some(entry => entry.quality === "USER_MARKET_TRADE_COVERAGE") && (
          <div data-replay-agg-trade-download-note>
            <InlineAlert tone="info">{t("replay.picker.firstDownload")}</InlineAlert>
          </div>
        )}
        {hedgeLocked && (
          <div data-replay-hedge-lock-note>
            <InlineAlert tone="info">{t("replay.picker.hedgeLocked")}</InlineAlert>
          </div>
        )}

        <div className="replay-market-picker-toolbar">
          <Field label={t("replay.picker.search")} className="replay-market-picker-search">
            <Input
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t("replay.picker.searchPh")}
              autoFocus
            />
          </Field>
          {marketTypes.length > 1 && (marketTypeOptions.length <= 5 ? (
            <div className="training-hub-choice">
              <span className="ui-field-label">{t("replay.picker.marketType")}</span>
              <SegmentedControl label={t("replay.picker.marketType")} value={marketTypeValue} options={marketTypeOptions} onChange={chooseMarketType} />
            </div>
          ) : (
            <Field label={t("replay.picker.marketType")}>
              <Select value={marketTypeValue} onChange={(event) => chooseMarketType(event.target.value)}>
                {marketTypeOptions.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </Select>
            </Field>
          ))}
          <Checkbox
            className="replay-market-picker-toggle"
            label={t("replay.picker.availableOnly")}
            checked={availableOnly}
            onChange={(event) => {
              setAvailableOnly(event.target.checked);
              if (event.target.checked) setUnavailableOpen(false);
            }}
          />
        </div>

        {error !== null && <InlineAlert tone="danger">{error}</InlineAlert>}
        {downgrade !== null && (
          <div data-replay-market-downgrade="HEDGE_HYBRID">
            <InlineAlert
              tone="warning"
              title={t("replay.picker.confirmDowngrade", { symbol: downgrade.entry.identity.symbol })}
              action={<>
                <Button size="sm" variant="primary" disabled={selecting !== null}
                  onClick={() => void selectMarket(downgrade.entry, true)}>{t("replay.picker.confirmHybrid")}</Button>
                <Button size="sm" disabled={selecting !== null} onClick={() => setDowngrade(null)}>{t("replay.hub.cancel")}</Button>
              </>}
            >
              {downgrade.message}
            </InlineAlert>
          </div>
        )}

        {catalog === null ? (
          <EmptyState icon={<span className="replay-loading-spinner" />} title={t("replay.picker.loading")} />
        ) : entries.length === 0 ? (
          <EmptyState title={t("replay.picker.noMatch")} description={t("replay.picker.noMatchHint")} />
        ) : availableEntries.length === 0 && visibleBlocked.length === 0 ? (
          <EmptyState
            title={t("replay.picker.noneReady")}
            description={t("replay.picker.noneReadyHint")}
            action={<>
              {blockedEntries.length > 0 && (
                <Button onClick={() => { setAvailableOnly(false); setUnavailableOpen(true); }}>
                  {t("replay.picker.viewBlocked", { count: blockedEntries.length })}
                </Button>
              )}
              <a className="ui-btn ui-btn-ghost" href="/replay.html">{t("replay.picker.newRun")}</a>
            </>}
          />
        ) : (
          <div className="replay-market-picker-list">
            {availableEntries.length > 0 && (
              <section aria-label={t("replay.picker.available")}>
                <h2>{t("replay.picker.availableH")} <span>{availableEntries.length}</span></h2>
                <div className="replay-market-picker-rows">
                  {availableEntries.map((entry, index) => (
                    <ReplayMarketPickerRow
                      key={trainingMarketKey(entry)}
                      entry={entry}
                      available
                      recommended={index === 0}
                      selecting={selecting === trainingMarketKey(entry)}
                      sourceKind={run.source_kind}
                      coverage={formatReplayMarketCoverage(entry, catalog.blind_mode)}
                      onSelect={() => void selectMarket(entry)}
                    />
                  ))}
                </div>
              </section>
            )}
            {visibleBlocked.length > 0 && (
              <section aria-label={t("replay.picker.blocked")}>
                <h2>{t("replay.picker.blockedH")} <span>{visibleBlocked.length}</span></h2>
                <div className="replay-market-picker-rows">
                  {visibleBlocked.map((entry) => (
                    <ReplayMarketPickerRow
                      key={trainingMarketKey(entry)}
                      entry={entry}
                      available={false}
                      recommended={false}
                      selecting={false}
                      sourceKind={run.source_kind}
                      coverage={formatReplayMarketCoverage(entry, catalog.blind_mode)}
                      onSelect={() => undefined}
                    />
                  ))}
                </div>
              </section>
            )}
            {blockedEntries.length > 0 && (
              <div className="replay-market-picker-more">
                {availableOnly && !unavailableOpen && (
                  <Button variant="ghost" onClick={() => setUnavailableOpen(true)}>
                    {t("replay.picker.showBlocked", { count: blockedEntries.length })}
                  </Button>
                )}
                <a className="ui-btn ui-btn-ghost" href="/replay.html">{t("replay.picker.newRun")}</a>
              </div>
            )}
          </div>
        )}
      </section>
    </main>
  );
}
