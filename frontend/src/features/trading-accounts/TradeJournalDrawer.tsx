import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { Icon } from "../../components/icons/Icon.js";
import { Badge, Button, Disclosure, Drawer, Field, InlineAlert, Input, Textarea } from "../../components/ui/index.js";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import {
  PRE_TRADE_FIELD_KEYS,
  RISK_FIELD_KEYS,
  sectionExpanded,
  templateFor,
  TRADE_REVIEW_TEMPLATE,
  type TemplateField,
  type TemplateSection,
} from "./journalTemplates.js";
import { JournalDraftError, JournalEditor } from "./journalEditor.js";
import type { JournalApi } from "./journalApi.js";
import { tradingApi } from "./tradingApi.js";
import {
  formatAmount,
  formatDateTime,
  formatDuration,
  formatPrice,
  formatQty,
  formatSigned,
  pnlTone,
} from "./tradingFormat.js";
import type {
  Excursion,
  JournalEntry,
  JournalStage,
  TradeDetail,
  TradingAccount,
  TradingChartContext,
} from "./tradingTypes.js";
import { tradingErrorMessage } from "./useTradingAccountsRuntime.js";
import type { PlanDraft } from "./PracticeOrderTicket.js";
import { autoFieldText, journalMarkdown, linkSuggestionLabel } from "./journalRender.js";

export type JournalTarget =
  | { kind: "trade"; tradeId: string }
  | { kind: "entry"; entryId: string }
  | { kind: "plan"; draft: PlanDraft | null };

const PRE_KEYS = new Set<string>(PRE_TRADE_FIELD_KEYS);
const SAVE_DELAY_MS = 800;

function stageOf(trade: TradeDetail | null): JournalStage {
  if (!trade) return "pre";
  return trade.status === "closed" ? "post" : "open";
}

export default function TradeJournalDrawer({
  account,
  api = tradingApi,
  target,
  context,
  onClose,
  onChanged,
  onOpenQuickReplay,
}: {
  account: Pick<TradingAccount, "id">;
  api?: JournalApi;
  target: JournalTarget;
  context: TradingChartContext;
  onClose(): void;
  onChanged(): void;
  onOpenQuickReplay(trade: TradeDetail): void;
}) {
  useLocale();
  const [trade, setTrade] = useState<TradeDetail | null>(null);
  const [excursion, setExcursion] = useState<Excursion | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const timerRef = useRef<number | null>(null);
  const sourceRef = useRef({ exchange: context.exchange, marketType: context.marketType, symbol: context.symbol,
    tradeId: target.kind === "trade" ? target.tradeId : null as string | null });
  const [editor] = useState(() => new JournalEditor({
    key: `candlescope.journal-draft.v1:${account.id}:${target.kind === "trade" ? `trade:${target.tradeId}`
      : target.kind === "entry" ? `entry:${target.entryId}`
        : `plan:${context.exchange}:${context.marketType}:${context.symbol}`}`,
    storage: () => window.localStorage,
    create: (fields, clientEntryId) => api.createEntry(account.id, {
      ...sourceRef.current,
      kind: "note", templateId: TRADE_REVIEW_TEMPLATE.id, templateVersion: TRADE_REVIEW_TEMPLATE.version,
      fields, clientEntryId,
    }),
    save: (id, fields, expectedRevision) => api.saveEntry(id, { fields, expectedRevision }),
    quick: (body, clientEntryId) => api.createEntry(account.id, {
      ...sourceRef.current,
      kind: "quick", body, clientEntryId,
    }),
  }));
  const editorState = useSyncExternalStore(editor.subscribe, editor.getSnapshot, editor.getSnapshot);
  const { note, fields, quickText, status: saveState } = editorState;
  const editorError = editorState.error instanceof JournalDraftError
    ? t(editorState.error.reason === "storage" ? "trading.journal.draftStorageFailed" : "trading.journal.draftChanged")
    : editorState.error ? tradingErrorMessage(editorState.error) : null;

  const source = trade ?? note ?? context;
  const instrument = useMemo(
    () => ({ exchange: source.exchange, marketType: source.marketType, symbol: source.symbol }),
    [source.exchange, source.marketType, source.symbol],
  );
  const instrumentLabel = `${instrument.symbol} · ${instrument.exchange} ${instrument.marketType}`;
  const stage = stageOf(trade);
  const template = templateFor(note?.templateId);

  const loadTrade = useCallback(async (tradeId: string) => {
    const detail = await api.trade(account.id, tradeId);
    sourceRef.current = { exchange: detail.exchange, marketType: detail.marketType, symbol: detail.symbol, tradeId: detail.id };
    setTrade(detail);
    if (detail.status === "closed") {
      api.excursion(account.id, tradeId).then(setExcursion).catch(() => setExcursion(null));
    }
    return detail;
  }, [account.id, api]);

  useEffect(() => {
    let cancelled = false;
    editor.activate();
    const run = async () => {
      try {
        if (target.kind === "trade") {
          const detail = await loadTrade(target.tradeId);
          if (!cancelled) editor.initialize(detail.entries.find((entry) => entry.id === detail.noteId) ?? null);
        } else if (target.kind === "entry") {
          const entry = await api.entry(target.entryId);
          if (cancelled) return;
          sourceRef.current = { exchange: entry.exchange, marketType: entry.marketType, symbol: entry.symbol, tradeId: entry.tradeId };
          editor.initialize(entry);
          if (entry.tradeId) await loadTrade(entry.tradeId);
        } else {
          const draft = target.draft;
          editor.initialize(null, {
            timeframe: context.interval,
            ...(draft?.entryPrice ? { entryPrice: draft.entryPrice } : {}),
            ...(draft?.stopPrice ? { stopPrice: draft.stopPrice } : {}),
            ...(draft?.targetPrice ? { targetPrice: draft.targetPrice } : {}),
            ...(draft?.riskUsdt ? { riskUsdt: draft.riskUsdt } : {}),
          });
          if (draft && (draft.stopPrice || draft.riskUsdt) && !editor.getSnapshot().recovered) {
            void editor.flush();
          }
        }
      } catch (cause) {
        if (!cancelled) setError(tradingErrorMessage(cause));
      }
    };
    void run();
    return () => {
      cancelled = true;
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
      editor.dispose();
    };
  }, [api, context.interval, editor, loadTrade, target]);

  const flush = async () => {
    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    timerRef.current = null;
    const saved = await editor.flush();
    if (saved) onChanged();
    return saved;
  };
  const ensureNote = async (): Promise<JournalEntry> => {
    if (!await editor.ensureNote()) throw new Error(t("trading.journal.saveFailed"));
    onChanged();
    const saved = editor.getSnapshot().note;
    if (!saved) throw new Error(t("trading.journal.plan"));
    return saved;
  };
  const setField = (key: string, value: string) => {
    const next = { ...editor.getSnapshot().fields };
    if (value) next[key] = value;
    else delete next[key];
    editor.edit(next);
    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(() => { void flush(); }, SAVE_DELAY_MS);
  };
  const quickNotes = useMemo(() => (trade?.entries ?? []).filter((entry) => entry.kind === "quick"), [trade]);
  const addQuickNote = async () => {
    if (await editor.saveQuick()) {
      if (trade) await loadTrade(trade.id);
      onChanged();
    }
  };

  const capture = async () => {
    try {
      const entry = await ensureNote();
      const image = context.captureImage ? await context.captureImage() : null;
      const state = {
        exchange: context.exchange,
        marketType: context.marketType,
        symbol: context.symbol,
        interval: context.interval,
        lastPrice: context.lastPrice,
        capturedAtMs: Date.now(),
        ...(context.describeChart ? context.describeChart() : {}),
      };
      const updated = await api.addSnapshot(entry.id, { ...(image ? { image } : {}), state });
      editor.adopt(updated);
    } catch (cause) {
      setError(tradingErrorMessage(cause));
    }
  };

  const link = async (entryId: string) => {
    if (!trade) return;
    try {
      if (!await flush()) return;
      const linked = await api.linkEntry(entryId, trade.id);
      editor.adopt(linked);
      await loadTrade(trade.id);
      onChanged();
    } catch (cause) {
      setError(tradingErrorMessage(cause));
    }
  };

  const copyMarkdown = async () => {
    const text = `# ${instrumentLabel}\n\n${journalMarkdown(fields, trade, excursion, instrumentLabel)}`;
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch (cause) {
      setError(tradingErrorMessage(cause));
    }
  };

  const plan = trade?.plan ?? note?.plan ?? null;
  const numeric = (value: string | null | undefined) => (value ? Number(value) : null);
  const riskEdited = plan !== null
    && RISK_FIELD_KEYS.some((key) => numeric(fields[key]) !== numeric(plan[key]));

  const renderField = (section: TemplateSection, field: TemplateField) => {
    const timing = note?.fieldTiming[field.key];
    const hindsight = trade !== null && PRE_KEYS.has(field.key) && timing !== undefined && timing.phase !== "pre";
    const id = `trading-field-${section.id}-${field.key}`;
    if (field.kind === "auto") {
      return (
        <div key={field.key} className="trading-journal-field" data-auto="true">
          <span className="trading-journal-label">{t(field.labelKey)}</span>
          <span className="trading-journal-auto" data-tone={field.auto === "netResult" && trade ? pnlTone(trade.netPnl) : undefined}>
            {autoFieldText(field, fields, trade, excursion, instrumentLabel)}
          </span>
        </div>
      );
    }
    const value = fields[field.key] ?? "";
    const label = <>
      {t(field.labelKey)}
      {hindsight && <Badge tone="warning">{t("trading.journal.afterEntry")}</Badge>}
    </>;
    const hint = field.hintKey ? t(field.hintKey) : undefined;
    if (field.kind === "choice") {
      return (
        <div key={field.key} className="trading-journal-field">
          <span className="trading-journal-label" id={id}>{label}</span>
          <div className="trading-choice" role="group" aria-labelledby={id}>
            {field.choices?.map((choice) => (
              <Button
                key={choice.value}
                size="sm"
                aria-pressed={value === choice.value}
                onClick={() => setField(field.key, value === choice.value ? "" : choice.value)}
              >
                {t(choice.labelKey)}
              </Button>
            ))}
          </div>
          {hint && <small className="trading-help">{hint}</small>}
        </div>
      );
    }
    return (
      <Field key={field.key} className="trading-journal-field" label={label} {...(hint ? { hint } : {})}>
        {field.kind === "longText" ? (
          <Textarea rows={2} value={value} onChange={(event) => setField(field.key, event.target.value)} />
        ) : (
          <Input
            size="sm"
            inputMode={field.kind === "price" || field.kind === "number" ? "decimal" : "text"}
            value={value}
            onChange={(event) => setField(field.key, event.target.value)}
          />
        )}
      </Field>
    );
  };

  // Save first, then close: from the close button, Escape, or another right-hand drawer opening.
  const requestClose = () => {
    if (!editorState.ready) { onClose(); return; }
    void flush().then((saved) => { if (saved) onClose(); });
  };

  return (
    <Drawer
      open
      onClose={requestClose}
      side="right"
      className="trading-drawer"
      title={trade ? t("trading.journal.tradeTitle", { symbol: trade.symbol }) : t("trading.journal.planTitle", { symbol: instrument.symbol })}
      actions={<>
        <span className="trading-save-state" data-state={saveState} role="status">
          {saveState === "saving" ? t("trading.journal.saving")
            : saveState === "saved" ? t("trading.journal.saved")
              : saveState === "failed" ? t("trading.journal.saveFailed") : ""}
        </span>
        <Button size="sm" disabled={!editorState.ready || saveState === "saving"} onClick={() => { void flush(); }}>
          {t("trading.journal.saveNow")}
        </Button>
      </>}
    >
      <p className="trading-drawer-meta">
        <Badge tone={stage === "pre" ? "accent" : stage === "open" ? "success" : "neutral"}>{t(`trading.stage.${stage}` as const)}</Badge>
        <span>
          {instrumentLabel}
          {trade && ` · ${t(trade.direction === "long" ? "trading.long" : "trading.short")} ${formatQty(trade.maxQty)}`}
        </span>
      </p>
      {(error || editorError) && <InlineAlert tone="danger">{editorError ?? error}</InlineAlert>}
      {editorState.recovered && <InlineAlert tone="info">{t("trading.journal.draftRecovered")}</InlineAlert>}
      <fieldset className="trading-journal-form" disabled={!editorState.ready}>
        {trade && (
          <div className="trading-trade-strip">
            <span>{formatDateTime(trade.openedAtMs)}{trade.closedAtMs ? ` · ${formatDuration(trade.openedAtMs, trade.closedAtMs)}` : ""}</span>
            <strong data-tone={pnlTone(trade.status === "closed" ? trade.netPnl : trade.unrealizedPnl)}>
              {formatSigned(trade.status === "closed" ? trade.netPnl : trade.unrealizedPnl)}
            </strong>
            <Button size="sm" onClick={() => { void flush().then((saved) => { if (saved) onOpenQuickReplay(trade); }); }}>
              {t("trading.replay.open")}
            </Button>
          </div>
        )}
        {trade?.readonlySource && (
          <Disclosure className="trading-source" summary={t("account.review.source", { instrument: trade.readonlySource.instrument, currency: trade.readonlySource.currency })}>
            <p>{t("account.review.identity", { uid: trade.readonlySource.accountUid, margin: trade.readonlySource.marginMode, position: trade.readonlySource.positionId })}</p>
            <p>{t("account.review.verified", { time: formatDateTime(trade.readonlySource.verifiedAtMs) })}</p>
            {trade.readonlySource.fills.map((fill) => <p key={fill.fillId}>{t("account.review.fillIdentity", { fill: fill.fillId, trade: fill.tradeId, order: fill.orderId ?? "—", contracts: fill.contracts })}</p>)}
            <p>{t("account.review.noR")}</p>
          </Disclosure>
        )}
        {plan && (
          <InlineAlert tone={riskEdited ? "warning" : "info"}>
            {t("trading.journal.locked", {
              entry: formatPrice(plan.entryPrice), stop: formatPrice(plan.stopPrice),
              target: formatPrice(plan.targetPrice), risk: formatAmount(plan.riskUsdt),
            })}
            {riskEdited && ` ${t("trading.journal.lockedEdited")}`}
          </InlineAlert>
        )}
        {trade && !plan && trade.entries.every((entry) => entry.kind !== "note") && trade.linkSuggestions.length > 0 && (
          <div className="trading-suggestions">
            <span>{t("trading.journal.suggestions")}</span>
            {trade.linkSuggestions.map((item) => (
              <Button key={item.id} size="sm" onClick={() => { void link(item.id); }}>
                {linkSuggestionLabel(item)}
              </Button>
            ))}
          </div>
        )}
        {template.sections.map((section) => {
          const open = expanded[section.id] ?? sectionExpanded(section, stage);
          return (
            <Disclosure
              key={section.id}
              className="trading-journal-section"
              summary={t(section.titleKey)}
              open={open}
              onToggle={(next) => { if (next !== open) setExpanded((current) => ({ ...current, [section.id]: next })); }}
            >
              {section.fields.map((field) => renderField(section, field))}
            </Disclosure>
          );
        })}
        {trade && (
          <section className="trading-journal-block">
            <h3>{t("trading.journal.quickNotes")}</h3>
            <ul className="trading-quick-notes">
              {quickNotes.map((entry) => (
                <li key={entry.id}>
                  <Badge tone={entry.reviewNote ? "neutral" : "accent"}>
                    {entry.reviewNote ? t("trading.journal.reviewNote") : t(`trading.stage.${entry.stage}` as const)}
                  </Badge>
                  <time>{formatDateTime(entry.marketTimeMs ?? entry.createdAtMs)}</time>
                  <p>{entry.body}</p>
                </li>
              ))}
            </ul>
            <Input
              size="sm"
              aria-label={t("trading.journal.quickNotes")}
              value={quickText}
              placeholder={t("trading.journal.quickPlaceholder")}
              onChange={(event) => editor.editQuick(event.target.value)}
              onKeyDown={(event) => { if (event.key === "Enter") void addQuickNote(); }}
            />
          </section>
        )}
        <section className="trading-journal-block">
          <h3>{t("trading.journal.snapshots")}</h3>
          {(note?.snapshots ?? []).length > 0 && (
            <div className="trading-snapshots">
              {(note?.snapshots ?? []).map((snapshot) => (
                <figure key={snapshot.id}>
                  {snapshot.hasImage
                    ? <JournalImage api={api} id={snapshot.id} time={snapshot.createdAtMs} />
                    : <span className="trading-help">{t("trading.journal.snapshotNoImage")}</span>}
                  <figcaption>{formatDateTime(snapshot.createdAtMs)} · {String(snapshot.state.symbol ?? "")} {String(snapshot.state.interval ?? "")}</figcaption>
                </figure>
              ))}
            </div>
          )}
          <div className="trading-actions">
            <Button size="sm" icon={<Icon name="camera" size={14} />} onClick={() => { void capture(); }}>
              {t("trading.journal.capture", { symbol: context.symbol, interval: context.interval })}
            </Button>
            <Button size="sm" onClick={() => { void copyMarkdown(); }}>
              {copied ? t("trading.journal.copied") : t("trading.journal.copyMarkdown")}
            </Button>
          </div>
        </section>
      </fieldset>
    </Drawer>
  );
}


function JournalImage({ api, id, time }: { api: JournalApi; id: string; time: number }) {
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    void Promise.resolve(api.snapshotImageUrl(id)).then((url) => { if (active) setSrc(url); })
      .catch(() => { if (active) setSrc(null); });
    return () => { active = false; };
  }, [api, id]);
  return src ? <img src={src} alt={t("trading.journal.snapshotAlt", { time: formatDateTime(time) })} /> : <span>—</span>;
}
