import { Button, IconButton } from "../ui/Button.js";
import { TabPanel, Tabs } from "../ui/Choice.js";
import { Badge, Disclosure, InlineAlert } from "../ui/Display.js";
import { EmptyState } from "../ui/EmptyState.js";
import { Checkbox, Field, Input, Select, Textarea } from "../ui/Field.js";
import { DateTimeInput } from "../ui/Inputs.js";
import { fromDateTimeInputValue, toDateTimeInputValue } from "../ui/helpers.js";
import { confirmAction } from "../ui/overlay/overlayApi.js";
import { OverlayLayer } from "../ui/Overlays.js";
import { useCallback, useEffect, useId, useMemo, useState } from "react";
import { useControlCommands } from "../../features/app-control/useControlCommands.js";
import { command } from "../../features/app-control/commandRegistry.js";
import { bool, choice, empty, object, optional, text } from "../../features/app-control/commandSchema.js";
import { alertDraftPatchSchema } from "../../features/app-control/alertCommandSchema.js";
import { getLocale, t, translateMarketType } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import { watchlistDisplayName } from "../../features/watchlist/watchlistDisplayName.js";
import { useRightDrawerResize } from "../../shared/useRightDrawerResize.js";
import {
  createAlertRule,
  deleteAlertRule,
  evaluateAlertExpression,
  fetchAlertHistory,
  fetchAlertRules,
  fetchAlertStatus,
  setAlertHistoryAcknowledged,
  setAlertRuleEnabled,
  updateAlertRule,
} from "../../features/alerts/alertsClient";
import {
  ALERT_COMPARATOR_OPTIONS,
  ALERT_RIGHT_TYPE_OPTIONS,
  ALERT_SOURCE_OPTIONS,
  buildAlertPayloadFromDraft,
  createDefaultAlertDraft,
  createDraftFromRule,
  describeAlertChannels,
  describeAlertDraftExpression,
  describeAlertDispatch,
  describeAlertRule,
  expressionDraftReducer,
  formatAlertTime,
  labelForComparator,
  labelForRightType,
  labelForSource,
} from "../../features/alerts/alertRuleModel";
import {
  ALERT_PANEL_OPEN_REQUEST_EVENT,
  ALERT_RULE_STATE_CHANGED_EVENT,
  primeAlertSound,
  takePendingAlertDraft,
  requestBrowserAlertPermission,
} from "../../features/alerts/alertDeliveryClient.js";
import { parseSymbolKey } from "../../utils/symbolKey";
import type {
  Dispatch,
  ReactNode,
  SetStateAction,
} from "react";
import type {
  AlertChannelState,
  AlertComparator,
  AlertConditionDraft,
  AlertDraft,
  AlertEvaluateResult,
  AlertEvaluationContext,
  AlertExpressionDraft,
  AlertExpressionDraftAction,
  AlertGroupDraft,
  AlertHistoryEvent,
  AlertLogicalOperator,
  AlertProductInput,
  AlertRule,
  AlertSystemStatus,
  AlertTraceNode as AlertTraceNodeData,
  AlertTriggerOn,
} from "../../features/alerts/alertTypes.js";
import type { WatchlistGroup } from "../../features/watchlist/watchlistTypes.js";
import { Icon } from "../icons/Icon.js";

type AlertTab = "add" | "all" | "history";
type AlertStatusFilter = "all" | "enabled" | "paused" | "expired";
type AlertHistoryRange = "today" | "7d" | "30d";
type AlertAcknowledgementFilter = "all" | "unread" | "ack";
type TestContextBucket = "previous" | "values";
type TestValueField = "close" | "last" | "rsi" | "macdHist" | "ma20" | "volume";

interface AlertTestContext {
  previous: Record<TestValueField, string>;
  values: Record<TestValueField, string>;
}

interface WatchlistAlertProduct extends AlertProductInput {
  symbol: string;
  marketType: string;
  exchange: string;
  key: string;
  listNames: string[];
  color: string;
}

function alertMarketLabel(marketType: string | undefined): string {
  if (marketType === "spot" || marketType === "futures") return translateMarketType(marketType);
  return marketType || t("market.spot");
}

const TAB_OPTIONS: Array<{ key: AlertTab; labelKey: "alert.tab.add" | "alert.tab.all" | "alert.tab.history" }> = [
  { key: "add", labelKey: "alert.tab.add" },
  { key: "all", labelKey: "alert.tab.all" },
  { key: "history", labelKey: "alert.tab.history" },
];

const TRIGGER_OPTIONS: Array<{ value: AlertTriggerOn; labelKey: "alert.trigger.realtime" | "alert.trigger.barUpdate" | "alert.trigger.barClose" }> = [
  { value: "realtime", labelKey: "alert.trigger.realtime" },
  { value: "bar_update", labelKey: "alert.trigger.barUpdate" },
  { value: "bar_close", labelKey: "alert.trigger.barClose" },
];

const CHANNEL_OPTIONS: Array<{
  key: keyof AlertChannelState;
  titleKey: "alert.channel.inApp" | "alert.channel.browser" | "alert.channel.sound" | "alert.channel.webhook" | "alert.channel.history";
  descKey: "alert.channel.inAppDesc" | "alert.channel.browserDesc" | "alert.channel.soundDesc" | "alert.channel.webhookDesc" | "alert.channel.historyDesc";
}> = [
  { key: "in_app", titleKey: "alert.channel.inApp", descKey: "alert.channel.inAppDesc" },
  { key: "browser", titleKey: "alert.channel.browser", descKey: "alert.channel.browserDesc" },
  { key: "sound", titleKey: "alert.channel.sound", descKey: "alert.channel.soundDesc" },
  { key: "webhook", titleKey: "alert.channel.webhook", descKey: "alert.channel.webhookDesc" },
  { key: "history", titleKey: "alert.channel.history", descKey: "alert.channel.historyDesc" },
];

const TEST_VALUE_FIELDS: Array<{ key: TestValueField; label?: string; labelKey?: "alert.field.close" | "alert.field.last" | "alert.field.volume" }> = [
  { key: "close", labelKey: "alert.field.close" },
  { key: "last", labelKey: "alert.field.last" },
  { key: "rsi", label: "RSI(14)" },
  { key: "macdHist", label: "MACD Hist" },
  { key: "ma20", label: "MA(20)" },
  { key: "volume", labelKey: "alert.field.volume" },
];

const RANGE_COMPARATORS = new Set<AlertComparator>(["between", "outsideRange"]);
const PERCENT_CHANGE_COMPARATORS = new Set<AlertComparator>(["percentChangeAbove", "percentChangeBelow"]);

function formatPrice(value: unknown): string {
  const num = Number(value);
  if (!Number.isFinite(num)) return "--";
  if (num >= 1000) {
    return num.toLocaleString("en-US", {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  }
  if (num >= 1) return num.toFixed(4);
  return num.toFixed(8);
}

function formatMarket(exchange: string | undefined, marketType: string | undefined): string {
  const ex = String(exchange || "binance").toUpperCase();
  return `${ex} · ${alertMarketLabel(marketType)}`;
}

function buildProductKey({ symbol, marketType, exchange }: AlertProductInput): string {
  return `${exchange || "binance"}:${marketType || "spot"}:${symbol || ""}`;
}

function buildWatchlistProducts(watchlists: WatchlistGroup[] = [], locale = getLocale()): WatchlistAlertProduct[] {
  const productMap = new Map<string, WatchlistAlertProduct>();
  for (const list of watchlists) {
    const symbols = Array.isArray(list?.symbols) ? list.symbols : [];
    for (const rawKey of symbols) {
      const parsed = parseSymbolKey(rawKey);
      if (!parsed.symbol) continue;
      const key = buildProductKey(parsed);
      const existing = productMap.get(key);
      if (existing) {
        existing.listNames.push((list.name ? watchlistDisplayName(list) : t("alert.watchlistFallback", {}, locale)));
        continue;
      }
      productMap.set(key, {
        ...parsed,
        key,
        listNames: [(list.name ? watchlistDisplayName(list) : t("alert.watchlistFallback", {}, locale))],
        color: list.color || "#3b82f6",
      });
    }
  }
  return Array.from(productMap.values()).sort((a, b) => a.symbol.localeCompare(b.symbol));
}

interface StepProps {
  n: number;
  title: string;
  action?: ReactNode;
  children: ReactNode;
}

/** One numbered part of the alert form: a heading and its fields, no card around it. */
function Step({ n, title, action, children }: StepProps) {
  return (
    <section className="alert-step" aria-label={title}>
      <div className="alert-step-head">
        <h4 className="alert-step-title"><span className="alert-step-number" aria-hidden="true">{n}</span>{title}</h4>
        {action}
      </div>
      {children}
    </section>
  );
}

function alertRuntimeRuleStateLabel(state: string | undefined, enabled: boolean): string {
  const labels: Record<string, "alert.state.ready" | "alert.state.warming" | "alert.state.recovering" | "alert.state.degraded" | "alert.state.disabled" | "alert.state.expired" | "alert.state.exhausted"> = {
    ready: "alert.state.ready",
    warming: "alert.state.warming",
    recovering: "alert.state.recovering",
    degraded: "alert.state.degraded",
    disabled: "alert.state.disabled",
    expired: "alert.state.expired",
    exhausted: "alert.state.exhausted",
  };
  if (state && labels[state]) return t(labels[state]);
  return enabled ? t("alert.state.waiting") : t("alert.state.disabled");
}

interface ConditionCardProps {
  node: AlertConditionDraft;
  index: string | number;
  onAction(action: AlertExpressionDraftAction): void;
  canDelete: boolean;
}

function ConditionCard({ node, index, onAction, canDelete }: ConditionCardProps) {
  const update = (patch: Partial<AlertConditionDraft>) => onAction({ type: "update-node", nodeId: node.id, patch });
  const isRangeComparator = RANGE_COMPARATORS.has(node.comparator);
  const isPercentComparator = PERCENT_CHANGE_COMPARATORS.has(node.comparator);
  const sourceChoices = node.rightType === "indicator"
    ? ALERT_SOURCE_OPTIONS.filter((item) => ["rsi", "macdHist", "ma20"].includes(item.value))
    : ALERT_SOURCE_OPTIONS;
  const updateComparator = (value: AlertComparator) => {
    const patch: Partial<AlertConditionDraft> = { comparator: value };
    if (RANGE_COMPARATORS.has(value)) {
      patch.rangeMin = node.rangeMin || "30";
      patch.rangeMax = node.rangeMax || "70";
    }
    if (PERCENT_CHANGE_COMPARATORS.has(value)) {
      patch.percentValue = node.percentValue || "2";
    }
    update(patch);
  };

  return (
    <div className="alert-condition">
      <div className="alert-condition-head">
        <span className="alert-condition-index">{t("alert.condition", { index: String(index) })}</span>
        <div className="alert-inline-actions">
          <Checkbox label="NOT" checked={Boolean(node.not)} onChange={(event) => update({ not: event.target.checked })} />
          <Button size="sm" variant="ghost" onClick={() => onAction({ type: "duplicate-node", nodeId: node.id })}>{t("alert.copy")}</Button>
          <Button size="sm" variant="ghost" onClick={() => onAction({ type: "delete-node", nodeId: node.id })} disabled={!canDelete}>{t("alert.delete")}</Button>
        </div>
      </div>
      <div className="alert-field-grid">
        <Field label={t("alert.left")}>
          <Select size="sm" value={node.left} onChange={(event) => update({ left: event.target.value })}>
            {ALERT_SOURCE_OPTIONS.map((item) => <option key={item.value} value={item.value}>{labelForSource(item.value)}</option>)}
          </Select>
        </Field>
        <Field label={t("alert.operator")}>
          <Select size="sm" value={node.comparator} onChange={(event) => updateComparator(event.target.value as AlertComparator)}>
            {ALERT_COMPARATOR_OPTIONS.map((item) => <option key={item.value} value={item.value}>{labelForComparator(item.value)}</option>)}
          </Select>
        </Field>
        {isRangeComparator ? (
          <>
            <Field label={t("alert.rangeMin")}>
              <Input size="sm" type="number" value={node.rangeMin} onChange={(event) => update({ rangeMin: event.target.value })} />
            </Field>
            <Field label={t("alert.rangeMax")}>
              <Input size="sm" type="number" value={node.rangeMax} onChange={(event) => update({ rangeMax: event.target.value })} />
            </Field>
          </>
        ) : isPercentComparator ? (
          <Field label={t("alert.changePct")} className="alert-field-wide">
            <Input size="sm" type="number" value={node.percentValue} onChange={(event) => update({ percentValue: event.target.value })} />
          </Field>
        ) : (
          <>
            <Field label={t("alert.rightType")}>
              <Select size="sm" value={node.rightType} onChange={(event) => update({ rightType: event.target.value as AlertConditionDraft["rightType"], rightValue: event.target.value === "number" ? node.rightValue : "close" })}>
                {ALERT_RIGHT_TYPE_OPTIONS.map((item) => <option key={item.value} value={item.value}>{labelForRightType(item.value)}</option>)}
              </Select>
            </Field>
            <Field label={t("alert.right")}>
              {node.rightType === "number" ? (
                <Input size="sm" type="number" value={node.rightValue} onChange={(event) => update({ rightValue: event.target.value })} />
              ) : (
                <Select size="sm" value={node.rightValue || "close"} onChange={(event) => update({ rightValue: event.target.value })}>
                  {sourceChoices.map((item) => <option key={item.value} value={item.value}>{labelForSource(item.value)}</option>)}
                </Select>
              )}
            </Field>
          </>
        )}
      </div>
    </div>
  );
}

function numericInputValue(value: unknown): string {
  const num = Number(value);
  return Number.isFinite(num) ? String(num) : "";
}

function createDefaultTestContext(price: unknown): AlertTestContext {
  const current = Number(price);
  const safePrice = Number.isFinite(current) && current > 0 ? current : 0;
  return {
    previous: {
      close: numericInputValue(safePrice ? safePrice * 0.995 : 0),
      last: numericInputValue(safePrice ? safePrice * 0.995 : 0),
      rsi: "68",
      macdHist: "-0.1",
      ma20: numericInputValue(safePrice ? safePrice * 0.99 : 0),
      volume: "900",
    },
    values: {
      close: numericInputValue(safePrice),
      last: numericInputValue(safePrice),
      rsi: "72",
      macdHist: "0.1",
      ma20: numericInputValue(safePrice ? safePrice * 0.99 : 0),
      volume: "1200",
    },
  };
}

function normalizeTestContext(context: AlertTestContext): AlertEvaluationContext {
  const normalizeBucket = (bucket: Record<TestValueField, string>): Record<string, number> => {
    const normalized: Record<string, number> = {};
    for (const { key } of TEST_VALUE_FIELDS) {
      const value = Number(bucket[key]);
      if (Number.isFinite(value)) normalized[key] = value;
    }
    return normalized;
  };
  return {
    previous: normalizeBucket(context.previous),
    values: normalizeBucket(context.values),
  };
}

interface LogicConnectorProps {
  value: AlertLogicalOperator;
}

function LogicConnector({ value }: LogicConnectorProps) {
  return (
    <div className="alert-logic-connector">
      <span>{value}</span>
    </div>
  );
}

interface LogicGroupEditorProps {
  node: AlertGroupDraft;
  onAction(action: AlertExpressionDraftAction): void;
  depth?: number;
  path?: string;
  canDelete?: boolean;
}

function LogicGroupEditor({ node, onAction, depth = 0, path, canDelete = false }: LogicGroupEditorProps) {
  const update = (patch: Partial<AlertGroupDraft>) => onAction({ type: "update-node", nodeId: node.id, patch });
  const children = Array.isArray(node.children) ? node.children : [];
  const displayPath = path || t("alert.root");

  return (
    <div className={`alert-logic-group ${depth === 0 ? "root" : "nested"}`}>
      <div className="alert-logic-head">
        <div>
          <div className="alert-logic-title">{t("alert.logicTitle", { path: displayPath })}</div>
          <div className="alert-logic-desc">{t("alert.logicDesc", { count: children.length, op: node.op || "AND" })}</div>
        </div>
        <div className="alert-inline-actions">
          <Checkbox label="NOT" checked={Boolean(node.not)} onChange={(event) => update({ not: event.target.checked })} />
          <Select size="sm" aria-label={t("alert.logicTitle", { path: displayPath })} value={node.op || "AND"} onChange={(event) => update({ op: event.target.value as AlertLogicalOperator })}>
            <option value="AND">AND</option>
            <option value="OR">OR</option>
          </Select>
          <Button size="sm" variant="ghost" onClick={() => onAction({ type: "duplicate-node", nodeId: node.id })} disabled={depth === 0}>{t("alert.copyGroup")}</Button>
          <Button size="sm" variant="ghost" onClick={() => onAction({ type: "delete-node", nodeId: node.id })} disabled={!canDelete}>{t("alert.deleteGroup")}</Button>
        </div>
      </div>

      {children.map((child, index) => (
        <div key={child.id}>
          {index > 0 && <LogicConnector value={node.op || "AND"} />}
          {child.type === "group" ? (
            <LogicGroupEditor
              node={child}
              onAction={onAction}
              depth={depth + 1}
              path={`${displayPath}.${index + 1}`}
              canDelete={children.length > 1}
            />
          ) : (
            <ConditionCard
              node={child}
              index={`${displayPath}.${index + 1}`}
              onAction={onAction}
              canDelete={children.length > 1}
            />
          )}
        </div>
      ))}

      <div className="alert-logic-footer">
        <Button size="sm" onClick={() => onAction({ type: "add-condition", nodeId: node.id })}>{t("alert.addCondition")}</Button>
        <Button size="sm" onClick={() => onAction({ type: "add-group", nodeId: node.id })}>{t("alert.addGroup")}</Button>
      </div>
    </div>
  );
}

interface NestedLogicBuilderProps {
  expression: AlertExpressionDraft;
  onAction(action: AlertExpressionDraftAction): void;
}

function NestedLogicBuilder({ expression, onAction }: NestedLogicBuilderProps) {
  // Most alerts are one condition ("price crosses X"): show just that condition, and
  // only bring in the AND / OR / NOT group editor once a second condition is added.
  const only = expression.type === "group" && !expression.not && expression.children.length === 1
    ? expression.children[0]
    : undefined;
  if (expression.type === "group" && only && only.type !== "group") {
    const single = only;
    return (
      <div className="alert-logic-builder">
        <ConditionCard node={single} index="1" onAction={onAction} canDelete={false} />
        <div className="alert-logic-footer">
          <Button size="sm" onClick={() => onAction({ type: "add-condition", nodeId: expression.id })}>{t("alert.addCondition")}</Button>
        </div>
      </div>
    );
  }
  return (
    <div className="alert-logic-builder">
      {expression.type === "group" ? (
        <LogicGroupEditor node={expression} onAction={onAction} />
      ) : (
        <ConditionCard node={expression} index={`${t("alert.root")}.1`} onAction={onAction} canDelete={false} />
      )}
    </div>
  );
}

interface ExpiryStepProps {
  draft: AlertDraft;
  onDraftChange: Dispatch<SetStateAction<AlertDraft>>;
}

function ExpiryStep({ draft, onDraftChange }: ExpiryStepProps) {
  const update = (patch: Partial<AlertDraft>) => onDraftChange((prev) => ({ ...prev, ...patch }));
  const updateAfterTrigger = (value: AlertDraft["afterTrigger"]) => {
    update({
      afterTrigger: value,
      ...(value === "keep" ? { maxTriggerMode: "unlimited" as const } : {}),
      ...(value === "pause" ? { maxTriggerMode: "once" as const } : {}),
    });
  };
  // The draft keeps the expiry as a local `datetime-local` value; the kit field works in epoch ms.
  const customExpiresMs = draft.customExpiresAt ? fromDateTimeInputValue(draft.customExpiresAt, false) : null;

  return (
    <Step n={3} title={t("alert.stepExpiry")}>
      <div className="alert-field-grid">
        <Field label={t("alert.when")}>
          <Select value={draft.triggerOn} onChange={(event) => update({ triggerOn: event.target.value as AlertTriggerOn })}>
            {TRIGGER_OPTIONS.map((item) => <option key={item.value} value={item.value}>{t(item.labelKey)}</option>)}
          </Select>
        </Field>
        <Field label={t("alert.afterTrigger")}>
          <Select value={draft.afterTrigger} onChange={(event) => updateAfterTrigger(event.target.value as AlertDraft["afterTrigger"])}>
            <option value="auto-disable">{t("alert.autoDisable")}</option>
            <option value="keep">{t("alert.keepEnabled")}</option>
            <option value="pause">{t("alert.pauseAfter")}</option>
          </Select>
        </Field>
        <Field label={t("alert.triggerCount")}>
          <Select value={draft.maxTriggerMode} disabled={draft.afterTrigger !== "auto-disable"} onChange={(event) => update({ maxTriggerMode: event.target.value as AlertDraft["maxTriggerMode"] })}>
            <option value="once">{t("alert.once")}</option>
            <option value="3">{t("alert.threeTimes")}</option>
            <option value="custom">{t("alert.customCount")}</option>
            <option value="unlimited">{t("alert.unlimited")}</option>
          </Select>
        </Field>
        {draft.maxTriggerMode === "custom" && (
          <Field label={t("alert.customTimes")}>
            <Input type="number" min="1" step="1" value={draft.customMaxTriggers} onChange={(event) => update({ customMaxTriggers: event.target.value })} />
          </Field>
        )}
        <Field label={t("alert.timeExpiry")}>
          <Select value={draft.expiresMode} onChange={(event) => update({ expiresMode: event.target.value as AlertDraft["expiresMode"] })}>
            <option value="1h">{t("alert.in1h")}</option>
            <option value="today">{t("alert.endOfDay")}</option>
            <option value="7d">{t("alert.in7d")}</option>
            <option value="custom">{t("alert.customDatetime")}</option>
            <option value="never">{t("alert.never")}</option>
          </Select>
        </Field>
        {draft.expiresMode === "custom" && (
          <Field label={t("alert.expiryTime")} className="alert-field-wide">
            <DateTimeInput
              utc={false}
              value={customExpiresMs}
              onChange={(ms) => update({ customExpiresAt: ms === null ? "" : toDateTimeInputValue(ms, false, false) })}
            />
          </Field>
        )}
      </div>
    </Step>
  );
}

interface NotifyStepProps {
  draft: AlertDraft;
  onDraftChange: Dispatch<SetStateAction<AlertDraft>>;
  availableChannels: string[];
}

function NotifyStep({ draft, onDraftChange, availableChannels }: NotifyStepProps) {
  const [channelSetupMessage, setChannelSetupMessage] = useState("");
  const webhookAvailable = availableChannels.includes("webhook");
  const update = (patch: Partial<AlertDraft>) => onDraftChange((prev) => ({ ...prev, ...patch }));
  const updateChannel = (key: keyof AlertChannelState, checked: boolean) => {
    void (async () => {
      let enabled = checked;
      if (checked && key === "browser") {
        const permission = await requestBrowserAlertPermission();
        enabled = permission === "granted";
        setChannelSetupMessage(enabled ? t("alert.browserGranted") : t("alert.browserDenied", { permission }));
      } else if (checked && key === "sound") {
        enabled = await primeAlertSound();
        setChannelSetupMessage(enabled ? t("alert.soundOn") : t("alert.soundOff"));
      } else if (checked && key === "webhook" && !webhookAvailable) {
        enabled = false;
        setChannelSetupMessage(t("alert.webhookOff"));
      }
      onDraftChange((prev) => ({
        ...prev,
        channels: { ...prev.channels, [key]: enabled },
      }));
    })();
  };

  return (
    <Step n={4} title={t("alert.stepNotify")}>
      <div className="alert-channels">
        {CHANNEL_OPTIONS.map(({ key, titleKey, descKey }) => (
          <Checkbox
            key={key}
            label={t(titleKey)}
            description={key === "webhook" && !webhookAvailable ? t("alert.webhookDisabled") : t(descKey)}
            checked={Boolean(draft.channels?.[key])}
            disabled={key === "history" || (key === "webhook" && !webhookAvailable)}
            onChange={(event) => updateChannel(key, event.target.checked)}
          />
        ))}
      </div>
      {draft.channels.webhook && (
        <Field label={t("alert.webhookUrl")}>
          <Input
            type="url"
            value={draft.webhookUrl}
            disabled={!webhookAvailable}
            placeholder="https://example.com/candlescope-alerts"
            onChange={(event) => update({ webhookUrl: event.target.value })}
          />
        </Field>
      )}
      {channelSetupMessage && <InlineAlert>{channelSetupMessage}</InlineAlert>}
      <Field label={t("alert.messageTemplate")}>
        <Textarea value={draft.messageTemplate} onChange={(event) => update({ messageTemplate: event.target.value })} rows={2} />
      </Field>
      <div className="alert-field-grid">
        <Field label={t("alert.cooldown")}>
          <Select value={draft.cooldownMode} onChange={(event) => update({ cooldownMode: event.target.value as AlertDraft["cooldownMode"] })}>
            <option value="always">{t("alert.notifyAlways")}</option>
            <option value="30s">{t("alert.cooldown30s")}</option>
            <option value="5m">{t("alert.cooldown5m")}</option>
            <option value="custom">{t("alert.custom")}</option>
          </Select>
        </Field>
        {draft.cooldownMode === "custom" && (
          <Field label={t("alert.cooldownSeconds")}>
            <Input type="number" min="0" step="1" value={draft.customCooldownSeconds} onChange={(event) => update({ customCooldownSeconds: event.target.value })} />
          </Field>
        )}
      </div>
    </Step>
  );
}

interface RulePreviewProps {
  draft: AlertDraft;
  product: WatchlistAlertProduct | null;
  fallbackSymbol?: string;
  interval: string;
}

function RulePreview({ draft, product, fallbackSymbol, interval }: RulePreviewProps) {
  const symbol = product?.symbol || fallbackSymbol || "BTCUSDT";
  const maxTriggers = draft.maxTriggerMode === "unlimited"
    ? t("alert.unlimitedTriggers")
    : t("alert.maxTriggers", { count: draft.maxTriggerMode === "custom" ? draft.customMaxTriggers : (draft.maxTriggerMode === "3" ? 3 : 1) });
  return (
    <InlineAlert title={t("alert.preview")}>
      {t("alert.previewBody", {
        symbol,
        interval,
        expression: describeAlertDraftExpression(draft.expression),
        maxTriggers,
        cooldown: draft.cooldownMode,
      })}
    </InlineAlert>
  );
}

interface AlertTraceNodeProps {
  node: AlertTraceNodeData | null;
  depth?: number;
}

function AlertTraceNode({ node, depth = 0 }: AlertTraceNodeProps) {
  if (!node) return null;
  const statusKeys = {
    matched: "alert.trace.matched",
    not_matched: "alert.trace.notMatched",
    missing_value: "alert.trace.missingValue",
    missing_previous: "alert.trace.missingPrevious",
    unsupported_comparator: "alert.trace.unsupported",
    invalid: "alert.trace.invalid",
  } as const;
  const statusKey = Object.prototype.hasOwnProperty.call(statusKeys, node.status)
    ? statusKeys[node.status as keyof typeof statusKeys]
    : null;
  const statusLabel = statusKey ? t(statusKey) : (node.status || "--");
  const details = node.details || {};
  const hasDetails = Object.keys(details).length > 0;
  return (
    <div className="alert-trace-node" data-depth={Math.min(depth, 3)} data-result={node.result ? "true" : "false"}>
      <div className="alert-trace-main">
        <span className="alert-trace-dot" aria-hidden="true" />
        <div>
          <div className="alert-trace-title">{node.summary || t("alert.trace.condition")}</div>
          {hasDetails && (
            <div className="alert-trace-details">
              {t("alert.trace.details", { left: String(details.left ?? "--"), right: String(details.right ?? "--") })}
              {details.previousLeft !== undefined && t("alert.trace.prevLeft", { value: String(details.previousLeft ?? "--") })}
              {details.previousRight !== undefined && t("alert.trace.prevRight", { value: String(details.previousRight ?? "--") })}
              {details.rangeMin !== undefined && t("alert.trace.range", { min: String(details.rangeMin), max: String(details.rangeMax ?? "--") })}
              {details.percentChange !== undefined && t("alert.trace.pct", { pct: Number(details.percentChange).toFixed(2) })}
            </div>
          )}
        </div>
        <Badge tone={node.result ? "success" : "neutral"}>{statusLabel}</Badge>
      </div>
      {Array.isArray(node.children) && node.children.length > 0 && (
        <div className="alert-trace-children">
          {node.children.map((child) => (
            <AlertTraceNode key={child.path} node={child} depth={depth + 1} />
          ))}
        </div>
      )}
    </div>
  );
}

interface RuleTestPanelProps {
  testContext: AlertTestContext;
  testResult: AlertEvaluateResult | null;
  testLoading: boolean;
  onContextChange(bucket: TestContextBucket, key: TestValueField, value: string): void;
  onResetContext(): void;
  onRunTest(): void;
}

/** A dry run against sample values, folded away: most alerts are saved without it. */
function RuleTestPanel({
  testContext,
  testResult,
  testLoading,
  onContextChange,
  onResetContext,
  onRunTest,
}: RuleTestPanelProps) {
  const status = testResult ? (testResult.result ? t("alert.testHit") : t("alert.testMiss")) : t("alert.untested");
  return (
    <Disclosure summary={<span className="alert-test-summary">{t("alert.stepTest")}<Badge tone={testResult?.result ? "success" : "neutral"}>{status}</Badge></span>}>
      <div className="alert-test-grid">
        {(["previous", "values"] as const).map((bucket) => (
          <fieldset key={bucket} className="alert-test-column">
            <legend>{bucket === "previous" ? t("alert.prevSample") : t("alert.currSample")}</legend>
            {TEST_VALUE_FIELDS.map((field) => (
              <Field key={`${bucket}-${field.key}`} label={field.labelKey ? t(field.labelKey) : field.label}>
                <Input
                  size="sm"
                  type="number"
                  value={testContext[bucket][field.key] ?? ""}
                  onChange={(event) => onContextChange(bucket, field.key, event.target.value)}
                />
              </Field>
            ))}
          </fieldset>
        ))}
      </div>
      <div className="alert-test-actions">
        <Button size="sm" variant="ghost" onClick={onResetContext} disabled={testLoading}>{t("alert.resetChart")}</Button>
        <Button size="sm" onClick={onRunTest} disabled={testLoading}>
          {testLoading ? t("alert.testing") : t("alert.testRule")}
        </Button>
      </div>
      {testResult && (
        <div className="alert-test-result">
          <InlineAlert tone={testResult.result ? "success" : "warning"} title={testResult.result ? t("alert.testWouldFire") : t("alert.testWouldNotFire")}>
            {t("alert.testShared")}
          </InlineAlert>
          <AlertTraceNode node={testResult.trace} />
        </div>
      )}
    </Disclosure>
  );
}

interface RuleListCardProps {
  title: string;
  symbol: string;
  summary: string;
  status: string;
  expiry: string;
  channels: string;
  enabled: boolean;
  onToggle(): void;
  onDelete(): void;
  onDuplicate(): void;
  onEdit(): void;
  busy: boolean;
}

function RuleListCard({ title, symbol, summary, status, expiry, channels, enabled, onToggle, onDelete, onDuplicate, onEdit, busy }: RuleListCardProps) {
  return (
    <li className="alert-row" data-enabled={enabled ? "true" : "false"}>
      <div className="alert-row-main">
        <div className="alert-row-title">
          <strong>{title}</strong>
          <Badge>{symbol}</Badge>
        </div>
        <span className="alert-row-summary">{summary}</span>
        <span className="alert-row-meta">{[status, expiry, channels].filter(Boolean).join(" · ")}</span>
      </div>
      <div className="alert-row-actions">
        <Button size="sm" variant="ghost" onClick={onEdit} disabled={busy}>{t("alert.edit")}</Button>
        <Button size="sm" variant="ghost" onClick={onDuplicate} disabled={busy}>{t("alert.duplicate")}</Button>
        <Button size="sm" variant="ghost" onClick={onToggle} disabled={busy}>{enabled ? t("alert.disable") : t("alert.enable")}</Button>
        <Button size="sm" variant="ghost" onClick={onDelete} disabled={busy}>{t("alert.delete")}</Button>
      </div>
    </li>
  );
}

interface HistoryItemProps {
  time: string;
  symbol: string;
  title: string;
  value: string;
  channels: string;
  acknowledged: boolean;
  busy: boolean;
  onAcknowledge(): void;
  onViewRule?: () => void;
}

function HistoryItem({
  time,
  symbol,
  title,
  value,
  channels,
  acknowledged,
  busy,
  onAcknowledge,
  onViewRule,
}: HistoryItemProps) {
  return (
    <li className="alert-row" data-unread={acknowledged ? undefined : "true"}>
      <div className="alert-row-main">
        <div className="alert-row-title">
          {!acknowledged && <span className="alert-unread-dot" aria-hidden="true" />}
          <strong>{title}</strong>
        </div>
        <span className="alert-row-summary">{t("alert.firedValue", { symbol, value })}</span>
        <span className="alert-row-meta">{time} · {channels}</span>
      </div>
      <div className="alert-row-actions">
        <Button size="sm" variant="ghost" onClick={onAcknowledge} disabled={busy}>
          {acknowledged ? t("alert.unack") : t("alert.ack")}
        </Button>
        <Button size="sm" variant="ghost" onClick={onViewRule} disabled={!onViewRule}>{t("alert.viewRule")}</Button>
      </div>
    </li>
  );
}

export interface AlertsPanelProps {
  isOpen: boolean;
  onClose(): void;
  currentSymbol?: string;
  currentMarketType?: string;
  currentExchange?: string;
  currentInterval?: string;
  displayPrice?: number | null;
  /** Accepted for callers; the drawer no longer repeats the chart's connection state. */
  wsStatus?: string;
  watchlists?: WatchlistGroup[];
}

function errorMessage(error: unknown, fallback: string): string {
  if (error && typeof error === "object") {
    const record = error as Record<string, unknown>;
    if (typeof record.detail === "string" && record.detail) return record.detail;
    if (typeof record.message === "string" && record.message) return record.message;
  }
  return fallback;
}

export default function AlertsPanel({
  isOpen,
  onClose,
  currentSymbol,
  currentMarketType,
  currentExchange,
  currentInterval,
  displayPrice,
  watchlists = [],
}: AlertsPanelProps) {
  const locale = useLocale();
  const [tab, setTab] = useState<AlertTab>("add");
  const tabsId = useId();
  const {
    width: panelWidth,
    isResizing,
    resizeHandleProps,
  } = useRightDrawerResize({
    initialWidth: 520,
    minWidth: 430,
    storageKey: "candlescope-alert-drawer-width",
  });
  const [selectedProductKey, setSelectedProductKey] = useState("");
  const [selectedInterval, setSelectedInterval] = useState("");
  const [rules, setRules] = useState<AlertRule[]>([]);
  const [history, setHistory] = useState<AlertHistoryEvent[]>([]);
  const [systemStatus, setSystemStatus] = useState<AlertSystemStatus | null>(null);
  const [alertLoading, setAlertLoading] = useState(false);
  const [alertSaving, setAlertSaving] = useState(false);
  const [alertError, setAlertError] = useState("");
  const [searchTerm, setSearchTerm] = useState("");
  const [statusFilter, setStatusFilter] = useState<AlertStatusFilter>("all");
  const [historyRange, setHistoryRange] = useState<AlertHistoryRange>("7d");
  const [acknowledgementFilter, setAcknowledgementFilter] = useState<AlertAcknowledgementFilter>("all");
  const [editingRuleId, setEditingRuleId] = useState("");
  const [draft, setDraft] = useState(() => createDefaultAlertDraft({
    ...(currentSymbol === undefined ? {} : { symbol: currentSymbol }),
    interval: currentInterval || "1m",
    price: displayPrice,
  }));
  const [testContext, setTestContext] = useState(() => createDefaultTestContext(displayPrice));
  const [testLoading, setTestLoading] = useState(false);
  const [testResult, setTestResult] = useState<AlertEvaluateResult | null>(null);

  const formattedPrice = formatPrice(displayPrice);
  const normalizedExchange = currentExchange || "binance";
  const symbolLabel = currentSymbol || "--";
  const intervalLabel = currentInterval || "--";

  const watchlistProducts = useMemo(() => buildWatchlistProducts(watchlists, locale), [locale, watchlists]);
  const currentProductKey = buildProductKey({
    ...(currentSymbol === undefined ? {} : { symbol: currentSymbol }),
    ...(currentMarketType === undefined ? {} : { marketType: currentMarketType }),
    ...(currentExchange === undefined ? {} : { exchange: currentExchange }),
  });
  const alertProducts = useMemo(() => {
    const products = new Map<string, WatchlistAlertProduct>();
    for (const item of watchlistProducts) products.set(item.key, { ...item, listNames: [...item.listNames] });

    let currentChartProduct: WatchlistAlertProduct | null = null;
    if (currentSymbol) {
      const existing = products.get(currentProductKey);
      currentChartProduct = {
        symbol: currentSymbol.toUpperCase(),
        marketType: currentMarketType || "spot",
        exchange: normalizedExchange,
        key: currentProductKey,
        listNames: Array.from(new Set([t("alert.currentChart", {}, locale), ...(existing?.listNames || [])])),
        color: existing?.color || "#3b82f6",
      };
      products.delete(currentProductKey);
    }

    for (const rule of rules) {
      const target = rule.target;
      if (!target?.symbol) continue;
      const key = buildProductKey(target);
      if (key === currentProductKey || products.has(key)) continue;
      products.set(key, {
        symbol: target.symbol,
        marketType: target.marketType || "spot",
        exchange: target.exchange || "binance",
        key,
        listNames: [t("alert.existingRules", {}, locale)],
        color: "var(--text-muted)",
      });
    }

    return [
      ...(currentChartProduct ? [currentChartProduct] : []),
      ...Array.from(products.values()).sort((a, b) => a.symbol.localeCompare(b.symbol)),
    ];
  }, [currentMarketType, currentProductKey, currentSymbol, locale, normalizedExchange, rules, watchlistProducts]);
  const selectedProductExists = alertProducts.some((item) => item.key === selectedProductKey);
  const defaultProductKey = currentSymbol ? currentProductKey : (alertProducts[0]?.key || "");
  const effectiveSelectedProductKey = selectedProductExists ? selectedProductKey : defaultProductKey;
  const selectedProduct = alertProducts.find((item) => item.key === effectiveSelectedProductKey) || null;
  const effectiveInterval = selectedInterval || (intervalLabel !== "--" ? intervalLabel : "1m");
  const canCreateAlert = Boolean(selectedProduct?.symbol || currentSymbol) && !alertSaving;
  const editorModeLabel = editingRuleId ? t("alert.update") : t("alert.create");
  const runtimeRuleStates = useMemo(() => systemStatus?.runtime.rules || [], [systemStatus]);
  const runtimeRuleStateById = useMemo(
    () => new Map(runtimeRuleStates.map((item) => [item.ruleId, item])),
    [runtimeRuleStates],
  );
  const warmingRuleCount = runtimeRuleStates.filter((item) => item.state === "warming").length;
  const degradedRuleCount = runtimeRuleStates.filter((item) => ["degraded", "recovering"].includes(item.state)).length;
  const runtimeStatusLabel = systemStatus?.runtime.status === "running"
    ? `${t("alert.runtimeOk", { count: systemStatus.runtime.subscriptions.length })}${warmingRuleCount ? t("alert.runtimeWarming", { count: warmingRuleCount }) : ""}`
    : (systemStatus?.runtime.status === "error"
      ? `${t("alert.runtimeBad")}${degradedRuleCount ? t("alert.runtimeRecovering", { count: degradedRuleCount }) : ""}`
      : t("alert.runtimeUnavailable"));
  const deliveryStatusLabel = systemStatus?.webhook.enabled
    ? (systemStatus.webhook.ready
      ? t("alert.webhookQueue", {
          queued: systemStatus.outbox.queued,
          retrying: systemStatus.outbox.retrying,
          dead: systemStatus.outbox.deadLetter,
        })
      : t("alert.webhookConfig", { error: systemStatus.webhook.configurationError || t("alert.unknownError") }))
    : t("alert.webhookDefaultOff");

  const historySinceMs = useMemo(() => {
    const now = new Date();
    if (historyRange === "today") {
      now.setHours(0, 0, 0, 0);
      return now.getTime();
    }
    const days = historyRange === "30d" ? 30 : 7;
    return Date.now() - days * 24 * 60 * 60 * 1000;
  }, [historyRange]);

  const loadAlerts = useCallback(async (signal?: AbortSignal) => {
    setAlertLoading(true);
    setAlertError("");
    try {
      const requestOptions = signal === undefined ? {} : { signal };
      const [nextRules, nextHistory] = await Promise.all([
        fetchAlertRules(requestOptions),
        fetchAlertHistory({
          limit: 100,
          sinceMs: historySinceMs,
          ...(acknowledgementFilter === "all"
            ? {}
            : { acknowledged: acknowledgementFilter === "ack" }),
        }, requestOptions),
      ]);
      setRules(Array.isArray(nextRules) ? nextRules : []);
      setHistory(Array.isArray(nextHistory) ? nextHistory : []);
      try {
        setSystemStatus(await fetchAlertStatus(requestOptions));
      } catch (statusError: unknown) {
        setSystemStatus(null);
        console.warn(t("alert.statusReadFailed"), statusError);
      }
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      setAlertError(errorMessage(err, t("alert.loadFailed")));
    } finally {
      setAlertLoading(false);
    }
  }, [acknowledgementFilter, historySinceMs]);

  const filteredRules = useMemo(() => {
    const needle = searchTerm.trim().toLowerCase();
    return rules.filter((rule) => {
      if (statusFilter === "enabled" && !rule.enabled) return false;
      if (statusFilter === "paused" && rule.enabled) return false;
      if (statusFilter === "expired") {
        const expiresAt = Number(rule.expiresAt);
        if (!Number.isFinite(expiresAt) || expiresAt > Date.now()) return false;
      }
      if (!needle) return true;
      const target = rule.target || {};
      return [
        rule.name,
        rule.description,
        target.symbol,
        target.exchange,
        target.marketType,
        describeAlertRule(rule),
        describeAlertChannels(rule),
      ].some((value) => String(value || "").toLowerCase().includes(needle));
    });
  }, [rules, searchTerm, statusFilter]);

  const ruleById = useMemo(() => new Map(rules.map((rule) => [rule.id, rule])), [rules]);

  const filteredHistory = useMemo(() => {
    const needle = searchTerm.trim().toLowerCase();
    if (!needle) return history;
    return history.filter((event) => {
      const rule = ruleById.get(event.ruleId);
      const target = event.target || rule?.target || {};
      return [
        event.message,
        event.ruleId,
        target.symbol,
        rule?.name,
        JSON.stringify(event.values || {}),
      ].some((value) => String(value || "").toLowerCase().includes(needle));
    });
  }, [history, ruleById, searchTerm]);

  const resetDraft = useCallback(() => {
    setEditingRuleId("");
    setDraft(createDefaultAlertDraft({
      ...((selectedProduct?.symbol || currentSymbol) === undefined
        ? {}
        : { symbol: selectedProduct?.symbol || currentSymbol }),
      interval: effectiveInterval,
      price: displayPrice,
    }));
    setTestResult(null);
    setTab("add");
  }, [currentSymbol, displayPrice, effectiveInterval, selectedProduct]);

  // "Add alert at price" from the chart: start a fresh draft at that price.
  useEffect(() => {
    const applyPendingDraft = () => {
      const request = takePendingAlertDraft();
      if (!request) return;
      setEditingRuleId("");
      setDraft(createDefaultAlertDraft({
        ...((selectedProduct?.symbol || currentSymbol) === undefined
          ? {}
          : { symbol: selectedProduct?.symbol || currentSymbol }),
        interval: effectiveInterval,
        price: request.price,
      }));
      setTestResult(null);
      setTab("add");
    };
    applyPendingDraft();
    window.addEventListener(ALERT_PANEL_OPEN_REQUEST_EVENT, applyPendingDraft);
    return () => window.removeEventListener(ALERT_PANEL_OPEN_REQUEST_EVENT, applyPendingDraft);
  }, [currentSymbol, effectiveInterval, selectedProduct]);

  const applyExpressionAction = useCallback((action: AlertExpressionDraftAction) => {
    setDraft((prev) => ({
      ...prev,
      expression: expressionDraftReducer(prev.expression, action),
    }));
    setTestResult(null);
  }, []);

  const updateTestContext = useCallback((bucket: TestContextBucket, key: TestValueField, value: string) => {
    setTestContext((prev) => ({
      ...prev,
      [bucket]: {
        ...(prev[bucket] || {}),
        [key]: value,
      },
    }));
    setTestResult(null);
  }, []);

  const resetTestContext = useCallback(() => {
    setTestContext(createDefaultTestContext(displayPrice));
    setTestResult(null);
  }, [displayPrice]);

  const runRuleTest = useCallback(async () => {
    if (!canCreateAlert) return;
    setTestLoading(true);
    setAlertError("");
    try {
      const payload = buildAlertPayloadFromDraft({
        draft,
        product: selectedProduct,
        ...(currentSymbol === undefined ? {} : { fallbackSymbol: currentSymbol }),
        ...(currentMarketType === undefined ? {} : { fallbackMarketType: currentMarketType }),
        fallbackExchange: normalizedExchange,
        interval: effectiveInterval,
      });
      const result = await evaluateAlertExpression({
        expression: payload.expression,
        context: normalizeTestContext(testContext),
      });
      setTestResult(result);
    } catch (err: unknown) {
      setAlertError(errorMessage(err, t("alert.testFailed")));
    } finally {
      setTestLoading(false);
    }
  }, [
    canCreateAlert,
    currentMarketType,
    currentSymbol,
    draft,
    effectiveInterval,
    normalizedExchange,
    selectedProduct,
    testContext,
  ]);

  const createCurrentAlert = useCallback(async () => {
    if (!canCreateAlert) return;
    setAlertSaving(true);
    setAlertError("");
    try {
      const payload = buildAlertPayloadFromDraft({
        draft,
        product: selectedProduct,
        ...(currentSymbol === undefined ? {} : { fallbackSymbol: currentSymbol }),
        ...(currentMarketType === undefined ? {} : { fallbackMarketType: currentMarketType }),
        fallbackExchange: normalizedExchange,
        interval: effectiveInterval,
      });
      if (editingRuleId) {
        await updateAlertRule(editingRuleId, payload);
      } else {
        await createAlertRule(payload);
      }
      await loadAlerts();
      setEditingRuleId("");
      setTab("all");
    } catch (err: unknown) {
      setAlertError(errorMessage(err, t("alert.saveFailed", { action: editorModeLabel })));
    } finally {
      setAlertSaving(false);
    }
  }, [
    canCreateAlert,
    currentMarketType,
    currentSymbol,
    draft,
    editingRuleId,
    editorModeLabel,
    effectiveInterval,
    loadAlerts,
    normalizedExchange,
    selectedProduct,
  ]);

  const editRule = useCallback((rule: AlertRule) => {
    if (!rule?.id) return;
    const target = rule.target || {};
    setEditingRuleId(rule.id);
    setDraft(createDraftFromRule(rule));
    setTestResult(null);
    setSelectedInterval(target.interval || "");
    const nextProductKey = buildProductKey({
      symbol: target.symbol,
      marketType: target.marketType,
      exchange: target.exchange,
    });
    if (alertProducts.some((item) => item.key === nextProductKey)) {
      setSelectedProductKey(nextProductKey);
    }
    setTab("add");
  }, [alertProducts]);

  const toggleRule = useCallback(async (rule: AlertRule) => {
    if (!rule?.id) return;
    setAlertSaving(true);
    setAlertError("");
    try {
      const updated = await setAlertRuleEnabled(rule.id, !rule.enabled);
      setRules((prev) => prev.map((item) => (item.id === updated.id ? updated : item)));
      await loadAlerts();
    } catch (err: unknown) {
      setAlertError(errorMessage(err, t("alert.statusFailed")));
    } finally {
      setAlertSaving(false);
    }
  }, [loadAlerts]);

  const removeRule = useCallback(async (rule: AlertRule) => {
    if (!rule?.id) return;
    setAlertSaving(true);
    setAlertError("");
    try {
      await deleteAlertRule(rule.id);
      setRules((prev) => prev.filter((item) => item.id !== rule.id));
    } catch (err: unknown) {
      setAlertError(errorMessage(err, t("alert.deleteFailed")));
    } finally {
      setAlertSaving(false);
    }
  }, []);

  const acknowledgeEvent = useCallback(async (event: AlertHistoryEvent) => {
    setAlertSaving(true);
    setAlertError("");
    try {
      const updated = await setAlertHistoryAcknowledged(event.id, event.acknowledgedAt === null);
      setHistory((current) => {
        if (acknowledgementFilter === "unread" && updated.acknowledgedAt !== null) {
          return current.filter((item) => item.id !== updated.id);
        }
        if (acknowledgementFilter === "ack" && updated.acknowledgedAt === null) {
          return current.filter((item) => item.id !== updated.id);
        }
        return current.map((item) => (item.id === updated.id ? updated : item));
      });
    } catch (err: unknown) {
      setAlertError(errorMessage(err, t("alert.ackFailed")));
    } finally {
      setAlertSaving(false);
    }
  }, [acknowledgementFilter]);

  const duplicateRule = useCallback(async (rule: AlertRule) => {
    if (!rule) return;
    setAlertSaving(true);
    setAlertError("");
    try {
      const { id, createdAt, updatedAt, triggerCount, lastTriggeredAt, ...payload } = rule;
      void id;
      void createdAt;
      void updatedAt;
      void triggerCount;
      void lastTriggeredAt;
      await createAlertRule({
        ...payload,
        name: t("alert.copyName", { name: rule.name || t("alert.fallbackName") }),
        enabled: false,
      });
      await loadAlerts();
    } catch (err: unknown) {
      setAlertError(errorMessage(err, t("alert.copyFailed")));
    } finally {
      setAlertSaving(false);
    }
  }, [loadAlerts]);

  useEffect(() => {
    if (intervalLabel && intervalLabel !== "--") {
      setSelectedInterval((prev) => prev || intervalLabel);
    }
  }, [intervalLabel]);

  useEffect(() => {
    if (!isOpen) return undefined;
    const controller = new AbortController();
    void loadAlerts(controller.signal);
    return () => controller.abort();
  }, [isOpen, loadAlerts]);

  useEffect(() => {
    if (!isOpen) return undefined;
    const refreshTriggeredRule = () => {
      void loadAlerts();
    };
    window.addEventListener(ALERT_RULE_STATE_CHANGED_EVENT, refreshTriggeredRule);
    return () => {
      window.removeEventListener(ALERT_RULE_STATE_CHANGED_EVENT, refreshTriggeredRule);
    };
  }, [isOpen, loadAlerts]);

  const controlId = useId();
  useControlCommands(() => ({ id: `alerts:${controlId}`, title: "Alert rules, drafts and notification history", context: () => ({ market: [currentExchange, currentMarketType, currentSymbol], editingRuleId, draft, rules: rules.map((item) => [item.id, item.updatedAt]), saving: alertSaving }),
    snapshot: () => ({ draft, editingRuleId, products: alertProducts, selectedProductKey, selectedInterval, rules, history, systemStatus, loading: alertLoading, saving: alertSaving, error: alertError, testLoading, testResult, canCreateAlert, tab, searchTerm, statusFilter, historyRange, acknowledgementFilter }), commands: [
      command("refresh", "Refresh alert rules, history and status.", empty, () => loadAlerts()),
      command("filters", "Edit alert panel filters.", object({ tab: optional(choice(["add", "all", "history"])), search: optional(text(256, 0)), status: optional(choice(["all", "enabled", "paused", "expired"])), historyRange: optional(choice(["today", "7d", "30d"])), acknowledged: optional(choice(["all", "unread", "ack"])) }), (input) => {
        if (input.tab) setTab(input.tab); if (input.search !== undefined) setSearchTerm(input.search); if (input.status) setStatusFilter(input.status); if (input.historyRange) setHistoryRange(input.historyRange); if (input.acknowledged) setAcknowledgementFilter(input.acknowledged);
      }),
      command("target", "Select a current watchlist alert product and interval.", object({ productKey: text(256), interval: text(24) }), ({ productKey, interval }) => { if (!alertProducts.some((row) => row.key === productKey)) throw new Error("PRODUCT_UNAVAILABLE"); setSelectedProductKey(productKey); setSelectedInterval(interval); }),
      command("draft", "Patch known alert draft fields, channels and a bounded expression tree.", alertDraftPatchSchema, (patch) => { setDraft((value) => ({ ...value, ...patch })); setTestResult(null); }),
      command("reset", "Start a new alert draft.", empty, () => resetDraft()),
      command("edit", "Edit a currently loaded alert rule.", object({ ruleId: text(128) }), ({ ruleId }) => { const rule = ruleById.get(ruleId); if (!rule) throw new Error("RULE_UNAVAILABLE"); editRule(rule); }),
      command("save", "Create/update the inspected draft through the existing payload validation and save workflow.", empty, () => createCurrentAlert(), { available: () => canCreateAlert && !alertSaving }),
      command("test", "Evaluate the draft with the current test inputs.", empty, () => runRuleTest(), { available: () => canCreateAlert && !testLoading }),
      command("testValue", "Edit a known test input.", object({ bucket: choice(["previous", "values"]), field: choice(["close", "last", "rsi", "macdHist", "ma20", "volume"]), value: text(64, 0) }), ({ bucket, field, value }) => updateTestContext(bucket, field, value)),
      command("enabled", "Set a loaded rule enabled/paused through the existing action.", object({ ruleId: text(128), enabled: bool }), ({ ruleId, enabled }) => { const rule = ruleById.get(ruleId); if (!rule) throw new Error("RULE_UNAVAILABLE"); if (rule.enabled !== enabled) return toggleRule(rule); }, { available: () => !alertSaving }),
      command("delete", "Delete a loaded alert rule with explicit confirmation.", object({ ruleId: text(128), confirmed: choice([true]) }), ({ ruleId }) => { const rule = ruleById.get(ruleId); if (!rule) throw new Error("RULE_UNAVAILABLE"); return removeRule(rule); }, { available: () => !alertSaving }),
      command("duplicate", "Copy a loaded rule in the UI's disabled state.", object({ ruleId: text(128) }), ({ ruleId }) => { const rule = ruleById.get(ruleId); if (!rule) throw new Error("RULE_UNAVAILABLE"); return duplicateRule(rule); }, { available: () => !alertSaving }),
      command("acknowledge", "Set a loaded history event read/unread.", object({ eventId: text(128), acknowledged: bool }), ({ eventId, acknowledged }) => { const event = history.find((row) => row.id === eventId); if (!event) throw new Error("EVENT_UNAVAILABLE"); if ((event.acknowledgedAt !== null) !== acknowledged) return acknowledgeEvent(event); }, { available: () => !alertSaving }),
      command("browserPermission", "Request browser notification permission using the existing OS/browser permission flow.", empty, () => requestBrowserAlertPermission()),
      command("primeSound", "Prepare alert sound through the existing browser audio policy.", empty, () => primeAlertSound()),
      command("close", "Close alert panel.", empty, () => onClose()),
    ] }), isOpen);
  if (!isOpen) return null;

  const productNote = selectedProduct
    ? [
        formatMarket(selectedProduct.exchange, selectedProduct.marketType),
        selectedProduct.listNames.join(" / "),
        ...(selectedProduct.key === currentProductKey && formattedPrice !== "--" ? [`${t("alert.price")} ${formattedPrice}`] : []),
      ].filter(Boolean).join(" · ")
    : "";

  return (
    <OverlayLayer kind="drawer" side="right" onClose={onClose}>
    <div className={`alert-panel-overlay right-drawer-overlay ${isResizing ? "is-resizing" : ""}`}
      onClick={(event) => { if (event.target === event.currentTarget && !isResizing) onClose(); }}
    >
      <aside
        className="alert-panel"
        aria-label={t("alert.center")}
        style={{ width: `${panelWidth}px` }}
      >
        <div
          {...resizeHandleProps}
          className="right-drawer-resize-handle"
          aria-label={t("rail.resizeWidth")}
        />

        <div className="alert-panel-header">
          <div className="alert-panel-heading">
            <h3 className="alert-panel-title">{t("alert.center")}</h3>
            <span className={`alert-runtime-status status-${systemStatus?.runtime.status || "unknown"}`} title={deliveryStatusLabel}>
              {runtimeStatusLabel}
            </span>
          </div>
          <IconButton label={t("alert.closePanel")} icon={<Icon name="close" size={16} />} onClick={onClose} data-overlay-close="" />
        </div>

        <Tabs<AlertTab>
          id={tabsId}
          className="alert-tabs"
          label={t("alert.center")}
          value={tab}
          onChange={setTab}
          tabs={TAB_OPTIONS.map((item) => ({
            value: item.key,
            label: t(item.labelKey),
            ...(item.key === "all" && rules.length > 0 ? { badge: rules.length } : {}),
          }))}
        />

        {(alertError || alertLoading) && (
          <InlineAlert
            className="alert-panel-notice"
            tone={alertError ? "danger" : "info"}
            title={alertError ? t("alert.systemHint") : t("alert.syncing")}
            action={<Button size="sm" onClick={() => loadAlerts()} disabled={alertLoading}>{t("alert.refresh")}</Button>}
          >
            {alertError || t("alert.syncingDesc")}
          </InlineAlert>
        )}

        <TabPanel tabsId={tabsId} value={tab} className="alert-panel-content">
          {tab === "add" && (
            <div className="alert-form">
              <Step n={1} title={t("alert.stepSymbol")}>
                {alertProducts.length > 0 ? (
                  <>
                    <div className="alert-field-row">
                      <Field label={t("alert.product")}>
                        <Select value={effectiveSelectedProductKey} onChange={(event) => setSelectedProductKey(event.target.value)}>
                          {alertProducts.map((item) => (
                            <option key={item.key} value={item.key}>
                              {item.symbol} · {formatMarket(item.exchange, item.marketType)}
                            </option>
                          ))}
                        </Select>
                      </Field>
                      <Field label={t("alert.interval")}>
                        <Select value={effectiveInterval} onChange={(event) => setSelectedInterval(event.target.value)}>
                          {Array.from(new Set([intervalLabel, "1m", "5m", "15m", "1h", "4h", "1d"].filter(Boolean))).map((item) => (
                            <option key={item}>{item}</option>
                          ))}
                        </Select>
                      </Field>
                    </div>
                    {productNote && <p className="alert-step-note">{productNote}</p>}
                  </>
                ) : (
                  <EmptyState
                    compact
                    icon={<Icon name="star" size={20} />}
                    title={t("alert.noProducts")}
                    description={t("alert.noProductsDesc")}
                  />
                )}
                <Field label={t("alert.ruleName")}>
                  <Input value={draft.name} onChange={(event) => setDraft((prev) => ({ ...prev, name: event.target.value }))} />
                </Field>
                <Field label={t("alert.ruleDesc")}>
                  <Textarea value={draft.description} onChange={(event) => setDraft((prev) => ({ ...prev, description: event.target.value }))} rows={2} />
                </Field>
              </Step>

              <Step n={2} title={t("alert.stepLogic")}>
                <NestedLogicBuilder expression={draft.expression} onAction={applyExpressionAction} />
              </Step>

              <ExpiryStep draft={draft} onDraftChange={setDraft} />

              <NotifyStep
                draft={draft}
                onDraftChange={setDraft}
                availableChannels={systemStatus?.registeredChannels || []}
              />

              <RulePreview
                draft={draft}
                product={selectedProduct}
                fallbackSymbol={symbolLabel}
                interval={intervalLabel}
              />

              <RuleTestPanel
                testContext={testContext}
                testResult={testResult}
                testLoading={testLoading}
                onContextChange={updateTestContext}
                onResetContext={resetTestContext}
                onRunTest={runRuleTest}
              />
            </div>
          )}

          {tab === "all" && (
            <div className="alert-list-view">
              <div className="alert-toolbar">
                <Input
                  type="search"
                  size="sm"
                  aria-label={t("alert.searchPlaceholder")}
                  placeholder={t("alert.searchPlaceholder")}
                  value={searchTerm}
                  onChange={(event) => setSearchTerm(event.target.value)}
                />
                <Select size="sm" aria-label={t("alert.statusAll")} value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as AlertStatusFilter)}>
                  <option value="all">{t("alert.statusAll")}</option>
                  <option value="enabled">{t("alert.statusEnabled")}</option>
                  <option value="paused">{t("alert.statusPaused")}</option>
                  <option value="expired">{t("alert.statusExpired")}</option>
                </Select>
                <IconButton size="sm" label={t("alert.refresh")} icon={<Icon name="refresh" size={14} />} onClick={() => loadAlerts()} disabled={alertLoading} />
                <Button size="sm" variant="primary" onClick={resetDraft}>{t("alert.addAlert")}</Button>
              </div>

              {filteredRules.length > 0 ? (
                <ul className="alert-list">
                  {filteredRules.map((rule) => (
                    <RuleListCard
                      key={rule.id}
                      title={rule.name}
                      symbol={rule.target?.symbol || "--"}
                      summary={describeAlertRule(rule)}
                      status={`${alertRuntimeRuleStateLabel(runtimeRuleStateById.get(rule.id)?.state, rule.enabled)} · ${t("alert.triggeredTimes", { count: rule.triggerCount || 0 })}`}
                      expiry={rule.maxTriggers ? t("alert.maxN", { count: rule.maxTriggers }) : t("alert.noLimit")}
                      channels={describeAlertChannels(rule)}
                      enabled={rule.enabled}
                      busy={alertSaving}
                      onEdit={() => editRule(rule)}
                      onToggle={() => toggleRule(rule)}
                      onDuplicate={() => duplicateRule(rule)}
                      onDelete={() => void (async () => {
                        if (await confirmAction({ title: t("alert.deleteConfirm", { name: rule.name }), confirmLabel: t("alert.delete"), tone: "danger" })) void removeRule(rule);
                      })()}
                    />
                  ))}
                </ul>
              ) : (
                <EmptyState
                  title={rules.length === 0 ? t("alert.empty") : t("alert.noMatch")}
                  description={t("alert.emptyDesc")}
                  icon={<Icon name="bell" size={20} />}
                  {...(rules.length === 0 ? { action: <Button size="sm" variant="primary" onClick={resetDraft}>{t("alert.addAlert")}</Button> } : {})}
                />
              )}
            </div>
          )}

          {tab === "history" && (
            <div className="alert-list-view">
              <div className="alert-toolbar">
                <Input
                  type="search"
                  size="sm"
                  aria-label={t("alert.filterPlaceholder")}
                  placeholder={t("alert.filterPlaceholder")}
                  value={searchTerm}
                  onChange={(event) => setSearchTerm(event.target.value)}
                />
                <Select size="sm" aria-label={t("alert.last7d")} value={historyRange} onChange={(event) => setHistoryRange(event.target.value as AlertHistoryRange)}>
                  <option value="today">{t("alert.today")}</option>
                  <option value="7d">{t("alert.last7d")}</option>
                  <option value="30d">{t("alert.last30d")}</option>
                </Select>
                <Select size="sm" aria-label={t("alert.allRecords")} value={acknowledgementFilter} onChange={(event) => setAcknowledgementFilter(event.target.value as AlertAcknowledgementFilter)}>
                  <option value="all">{t("alert.allRecords")}</option>
                  <option value="unread">{t("alert.unread")}</option>
                  <option value="ack">{t("alert.acked")}</option>
                </Select>
                <IconButton size="sm" label={t("alert.refreshHistory")} icon={<Icon name="refresh" size={14} />} onClick={() => loadAlerts()} disabled={alertLoading} />
              </div>

              {filteredHistory.length > 0 ? (
                <ul className="alert-list">
                  {filteredHistory.map((event) => {
                    const rule = ruleById.get(event.ruleId);
                    const target = event.target || rule?.target || {};
                    const values = event.values || {};
                    const valueText = values.close ?? values.value ?? Object.values(values)[0] ?? "--";
                    return (
                      <HistoryItem
                        key={event.id}
                        time={formatAlertTime(event.createdAt)}
                        symbol={target.symbol || rule?.target?.symbol || "--"}
                        title={event.message || t("alert.hitTitle", { name: rule?.name || t("alert.fallbackName") })}
                        value={String(valueText)}
                        channels={describeAlertDispatch(event)}
                        acknowledged={event.acknowledgedAt !== null}
                        busy={alertSaving}
                        onAcknowledge={() => { void acknowledgeEvent(event); }}
                        {...(rule
                          ? {
                              onViewRule: () => {
                                setSearchTerm(rule.name || rule.id);
                                setTab("all");
                              },
                            }
                          : {})}
                      />
                    );
                  })}
                </ul>
              ) : (
                <EmptyState title={t("alert.noHistory")} description={t("alert.noHistoryDesc")} icon={<Icon name="inbox" size={20} />} />
              )}
            </div>
          )}
        </TabPanel>

        {tab === "add" && (
          <div className="alert-panel-footer">
            <Button variant="ghost" onClick={resetDraft} disabled={alertSaving}>{t("alert.newDraft")}</Button>
            <Button variant="primary" onClick={createCurrentAlert} disabled={!canCreateAlert}>
              {alertSaving ? t("alert.saving") : editorModeLabel}
            </Button>
          </div>
        )}
      </aside>
    </div>
    </OverlayLayer>
  );
}
