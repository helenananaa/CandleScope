import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
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

type SaveState = "idle" | "saving" | "saved" | "failed";

const PRE_KEYS = new Set<string>(PRE_TRADE_FIELD_KEYS);
const SAVE_DELAY_MS = 800;

function stageOf(trade: TradeDetail | null): JournalStage {
  if (!trade) return "pre";
  return trade.status === "closed" ? "post" : "open";
}

export default function TradeJournalDrawer({
  account,
  target,
  context,
  onClose,
  onChanged,
  onOpenQuickReplay,
}: {
  account: TradingAccount;
  target: JournalTarget;
  context: TradingChartContext;
  onClose(): void;
  onChanged(): void;
  onOpenQuickReplay(trade: TradeDetail): void;
}) {
  useLocale();
  const [trade, setTrade] = useState<TradeDetail | null>(null);
  const [note, setNote] = useState<JournalEntry | null>(null);
  const [fields, setFields] = useState<Record<string, string>>({});
  const [excursion, setExcursion] = useState<Excursion | null>(null);
  const [saveState, setSaveState] = useState<SaveState>("idle");
  const [error, setError] = useState<string | null>(null);
  const [quickText, setQuickText] = useState("");
  const [copied, setCopied] = useState(false);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const noteRef = useRef<JournalEntry | null>(null);
  const fieldsRef = useRef(fields);
  const timerRef = useRef<number | null>(null);
  const creatingRef = useRef<Promise<JournalEntry> | null>(null);
  noteRef.current = note;
  fieldsRef.current = fields;

  const source = trade ?? note ?? context;
  const instrument = useMemo(
    () => ({ exchange: source.exchange, marketType: source.marketType, symbol: source.symbol }),
    [source.exchange, source.marketType, source.symbol],
  );
  const instrumentLabel = `${instrument.symbol} · ${instrument.exchange} ${instrument.marketType}`;
  const stage = stageOf(trade);
  const template = templateFor(note?.templateId);

  const loadTrade = useCallback(async (tradeId: string) => {
    const detail = await tradingApi.trade(account.id, tradeId);
    setTrade(detail);
    const tradeNote = detail.entries.find((entry) => entry.id === detail.noteId) ?? null;
    if (tradeNote && noteRef.current === null) {
      setNote(tradeNote);
      setFields(tradeNote.fields);
    } else if (tradeNote) {
      setNote(tradeNote);
    }
    if (detail.status === "closed") {
      tradingApi.excursion(account.id, tradeId).then(setExcursion).catch(() => setExcursion(null));
    }
    return detail;
  }, [account.id]);

  useEffect(() => {
    let cancelled = false;
    const run = async () => {
      try {
        if (target.kind === "trade") {
          await loadTrade(target.tradeId);
        } else if (target.kind === "entry") {
          const entry = await tradingApi.entry(target.entryId);
          if (cancelled) return;
          setNote(entry);
          setFields(entry.fields);
          if (entry.tradeId) await loadTrade(entry.tradeId);
        } else {
          const draft = target.draft;
          const initial = {
            timeframe: context.interval,
            ...(draft?.entryPrice ? { entryPrice: draft.entryPrice } : {}),
            ...(draft?.stopPrice ? { stopPrice: draft.stopPrice } : {}),
            ...(draft?.targetPrice ? { targetPrice: draft.targetPrice } : {}),
            ...(draft?.riskUsdt ? { riskUsdt: draft.riskUsdt } : {}),
          };
          setFields(initial);
          fieldsRef.current = initial;
          // A plan prefilled from the order ticket is saved right away so its
          // risk exists before the order that may fill moments later.
          if (draft && (draft.stopPrice || draft.riskUsdt)) {
            timerRef.current = window.setTimeout(() => { void flush(); }, 0);
          }
        }
      } catch (cause) {
        if (!cancelled) setError(tradingErrorMessage(cause));
      }
    };
    void run();
    return () => { cancelled = true; };
    // The drawer is keyed by its target; context changes must not reload it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target, loadTrade]);

  const ensureNote = useCallback(async (): Promise<JournalEntry> => {
    if (noteRef.current) return noteRef.current;
    if (!creatingRef.current) {
      creatingRef.current = tradingApi.createEntry(account.id, {
        ...instrument,
        kind: "note",
        templateId: TRADE_REVIEW_TEMPLATE.id,
        templateVersion: TRADE_REVIEW_TEMPLATE.version,
        ...(trade ? { tradeId: trade.id } : {}),
        fields: fieldsRef.current,
      }).then((created) => {
        setNote(created);
        noteRef.current = created;
        onChanged();
        return created;
      }).finally(() => { creatingRef.current = null; });
    }
    return creatingRef.current;
  }, [account.id, instrument, onChanged, trade]);

  const flush = useCallback(async () => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    setSaveState("saving");
    try {
      const existing = noteRef.current;
      const saved = existing
        ? await tradingApi.saveEntry(existing.id, { fields: fieldsRef.current })
        : await ensureNote();
      setNote(saved);
      setSaveState("saved");
    } catch (cause) {
      setSaveState("failed");
      setError(tradingErrorMessage(cause));
    }
  }, [ensureNote]);

  useEffect(() => () => {
    if (timerRef.current !== null) {
      window.clearTimeout(timerRef.current);
      void flush();
    }
  }, [flush]);

  const setField = (key: string, value: string) => {
    setFields((current) => {
      const next = { ...current };
      if (value) next[key] = value;
      else delete next[key];
      fieldsRef.current = next;
      return next;
    });
    setSaveState("idle");
    if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    timerRef.current = window.setTimeout(() => { void flush(); }, SAVE_DELAY_MS);
  };

  const quickNotes = useMemo(
    () => (trade?.entries ?? []).filter((entry) => entry.kind === "quick"),
    [trade],
  );

  const addQuickNote = async () => {
    const text = quickText.trim();
    if (!text) return;
    try {
      await tradingApi.createEntry(account.id, {
        ...instrument,
        kind: "quick",
        body: text,
        ...(trade ? { tradeId: trade.id } : {}),
      });
      setQuickText("");
      if (trade) await loadTrade(trade.id);
      onChanged();
    } catch (cause) {
      setError(tradingErrorMessage(cause));
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
      const updated = await tradingApi.addSnapshot(entry.id, { ...(image ? { image } : {}), state });
      setNote(updated);
    } catch (cause) {
      setError(tradingErrorMessage(cause));
    }
  };

  const link = async (entryId: string) => {
    if (!trade) return;
    try {
      const linked = await tradingApi.linkEntry(entryId, trade.id);
      setNote(linked);
      setFields(linked.fields);
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
    return (
      <div key={field.key} className="trading-journal-field">
        <label className="trading-journal-label" htmlFor={id}>
          {t(field.labelKey)}
          {hindsight && <em className="trading-badge" data-tone="warning">{t("trading.journal.afterEntry")}</em>}
        </label>
        {field.kind === "choice" ? (
          <div className="trading-segmented" role="group" id={id}>
            {field.choices?.map((choice) => (
              <button
                key={choice.value}
                type="button"
                data-active={value === choice.value}
                onClick={() => setField(field.key, value === choice.value ? "" : choice.value)}
              >
                {t(choice.labelKey)}
              </button>
            ))}
          </div>
        ) : field.kind === "longText" ? (
          <textarea id={id} rows={2} value={value} onChange={(event) => setField(field.key, event.target.value)} />
        ) : (
          <input
            id={id}
            inputMode={field.kind === "price" || field.kind === "number" ? "decimal" : "text"}
            value={value}
            onChange={(event) => setField(field.key, event.target.value)}
          />
        )}
        {field.hintKey && <small className="trading-help">{t(field.hintKey)}</small>}
      </div>
    );
  };

  return createPortal(
    <aside className="trading-drawer" role="dialog" aria-label={t("trading.journal.title")}>
      <header className="trading-drawer-header">
        <div>
          <h2>{trade ? t("trading.journal.tradeTitle", { symbol: trade.symbol }) : t("trading.journal.planTitle", { symbol: instrument.symbol })}</h2>
          <p>
            <span className="trading-badge" data-tone={stage === "pre" ? "info" : stage === "open" ? "accent" : "muted"}>
              {t(`trading.stage.${stage}` as const)}
            </span>
            {" "}{instrumentLabel}
            {trade && ` · ${t(trade.direction === "long" ? "trading.long" : "trading.short")} ${formatQty(trade.maxQty)}`}
          </p>
        </div>
        <span className="trading-save-state" data-state={saveState} role="status">
          {saveState === "saving" ? t("trading.journal.saving")
            : saveState === "saved" ? t("trading.journal.saved")
              : saveState === "failed" ? t("trading.journal.saveFailed") : ""}
        </span>
        <button type="button" className="trading-icon-button" aria-label={t("trading.close")} onClick={() => { void flush().finally(onClose); }}>×</button>
      </header>
      <div className="trading-drawer-body">
        {error && <p className="trading-error" role="alert">{error}</p>}
        {trade && (
          <div className="trading-trade-strip">
            <span>{formatDateTime(trade.openedAtMs)}{trade.closedAtMs ? ` · ${formatDuration(trade.openedAtMs, trade.closedAtMs)}` : ""}</span>
            <strong data-tone={pnlTone(trade.status === "closed" ? trade.netPnl : trade.unrealizedPnl)}>
              {formatSigned(trade.status === "closed" ? trade.netPnl : trade.unrealizedPnl)}
            </strong>
            <button type="button" className="trading-button" onClick={() => onOpenQuickReplay(trade)}>
              {t("trading.replay.open")}
            </button>
          </div>
        )}
        {plan && (
          <p className="trading-locked" data-edited={riskEdited}>
            {t("trading.journal.locked", {
              entry: formatPrice(plan.entryPrice), stop: formatPrice(plan.stopPrice),
              target: formatPrice(plan.targetPrice), risk: formatAmount(plan.riskUsdt),
            })}
            {riskEdited && ` ${t("trading.journal.lockedEdited")}`}
          </p>
        )}
        {trade && !plan && trade.entries.every((entry) => entry.kind !== "note") && trade.linkSuggestions.length > 0 && (
          <div className="trading-suggestions">
            <span>{t("trading.journal.suggestions")}</span>
            {trade.linkSuggestions.map((item) => (
              <button key={item.id} type="button" className="trading-button" onClick={() => { void link(item.id); }}>
                {linkSuggestionLabel(item)}
              </button>
            ))}
          </div>
        )}
        {template.sections.map((section) => {
          const open = expanded[section.id] ?? sectionExpanded(section, stage);
          return (
            <section key={section.id} className="trading-journal-section" data-open={open}>
              <button
                type="button"
                className="trading-journal-section-toggle"
                aria-expanded={open}
                onClick={() => setExpanded((current) => ({ ...current, [section.id]: !open }))}
              >
                {t(section.titleKey)}
              </button>
              {open && section.fields.map((field) => renderField(section, field))}
            </section>
          );
        })}
        {trade && (
          <section className="trading-journal-section" data-open="true">
            <h3>{t("trading.journal.quickNotes")}</h3>
            <ul className="trading-quick-notes">
              {quickNotes.map((entry) => (
                <li key={entry.id}>
                  <span className="trading-badge" data-tone={entry.reviewNote ? "muted" : "info"}>
                    {entry.reviewNote ? t("trading.journal.reviewNote") : t(`trading.stage.${entry.stage}` as const)}
                  </span>
                  <time>{formatDateTime(entry.marketTimeMs ?? entry.createdAtMs)}</time>
                  <p>{entry.body}</p>
                </li>
              ))}
            </ul>
            <input
              className="trading-quick-input"
              value={quickText}
              placeholder={t("trading.journal.quickPlaceholder")}
              onChange={(event) => setQuickText(event.target.value)}
              onKeyDown={(event) => { if (event.key === "Enter") void addQuickNote(); }}
            />
          </section>
        )}
        <section className="trading-journal-section" data-open="true">
          <h3>{t("trading.journal.snapshots")}</h3>
          <div className="trading-snapshots">
            {(note?.snapshots ?? []).map((snapshot) => (
              <figure key={snapshot.id}>
                {snapshot.hasImage
                  ? <img src={tradingApi.snapshotImageUrl(snapshot.id)} alt={t("trading.journal.snapshotAlt", { time: formatDateTime(snapshot.createdAtMs) })} />
                  : <span className="trading-help">{t("trading.journal.snapshotNoImage")}</span>}
                <figcaption>{formatDateTime(snapshot.createdAtMs)} · {String(snapshot.state.symbol ?? "")} {String(snapshot.state.interval ?? "")}</figcaption>
              </figure>
            ))}
          </div>
          <div className="trading-actions">
            <button type="button" className="trading-button" onClick={() => { void capture(); }}>
              {t("trading.journal.capture", { symbol: context.symbol, interval: context.interval })}
            </button>
            <button type="button" className="trading-button" onClick={() => { void copyMarkdown(); }}>
              {copied ? t("trading.journal.copied") : t("trading.journal.copyMarkdown")}
            </button>
          </div>
        </section>
      </div>
    </aside>,
    document.body,
  );
}
