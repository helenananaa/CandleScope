import { useMemo, useState } from "react";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";

import {
  getCommonLocalIntervals,
  resolveLocalIntervalSupport,
} from "./localIntervalPolicy.js";
import type { LocalDatasetManifest } from "./localDataTypes.js";
import { CALENDAR_ZONES, type CalendarZone } from "../../utils/calendarBasis.js";
import { formatIntervalLabel, intervalWithAnchor, parseIntervalParts } from "../../utils/intervals.js";


export default function LocalIntervalSelector({
  manifest,
  interval,
  onSelect,
}: {
  manifest: LocalDatasetManifest;
  interval: string;
  onSelect(interval: string): void;
}) {
  useLocale();
  const [custom, setCustom] = useState("90m");
  const [mode, setMode] = useState<"default" | "anchor" | "calendar">("default");
  const [zone, setZone] = useState<CalendarZone>("UTC");
  const [anchorTime, setAnchorTime] = useState("");
  const [customEdited, setCustomEdited] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const common = useMemo(() => {
    const values = getCommonLocalIntervals(manifest);
    const active = resolveLocalIntervalSupport(manifest, interval);
    if (active.supported && !values.includes(active.target)) values.push(active.target);
    return values;
  }, [interval, manifest]);
  const customValue = useMemo(() => {
    if (mode === "calendar") return `${custom}~c1~${zone}`;
    if (mode === "anchor") {
      const at = Date.parse(`${anchorTime}Z`);
      if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$/.test(anchorTime) || !Number.isFinite(at)
        || new Date(at).toISOString().slice(0, 16) !== anchorTime) return "";
      return intervalWithAnchor(custom, at);
    }
    return custom;
  }, [custom, mode, zone, anchorTime]);
  const customSupport = useMemo(() => {
    const support = resolveLocalIntervalSupport(manifest, customValue);
    return mode === "anchor" && !customValue
      ? { ...support, message: t("interval.anchorInvalid") } : support;
  }, [customValue, manifest, mode]);

  return (
    <div className="local-interval-selector" aria-label={t("local.intervalAria")}>
      <div className="local-interval-buttons" role="toolbar" aria-label={t("local.availableIntervals")}>
        {common.map((value) => {
          const support = resolveLocalIntervalSupport(manifest, value);
          return (
            <button
              type="button"
              key={value}
              className={support.target === interval ? "active" : ""}
              onClick={() => {
                onSelect(support.target);
                setFeedback(support.message);
              }}
              title={support.message}
            >
              {formatIntervalLabel(value)}
              {support.derived && !value.includes("~c1~") && <small>{support.factor}×</small>}
            </button>
          );
        })}
      </div>
      <form
        className="local-custom-interval"
        onSubmit={(event) => {
          event.preventDefault();
          if (!customSupport.supported) {
            setFeedback(customSupport.message);
            return;
          }
          onSelect(customSupport.target);
          setFeedback(customSupport.message);
        }}
      >
        <label>
          {t("local.custom")}
          <input
            value={custom}
            onChange={(event) => {
              setCustom(event.target.value);
              setCustomEdited(true);
              setFeedback(null);
            }}
            placeholder="90m"
            aria-label={t("local.customInterval")}
          />
        </label>
        <label><input type="checkbox" checked={mode === "anchor"} onChange={(event) => { setMode(event.target.checked ? "anchor" : "default"); setCustomEdited(true); setFeedback(null); }} />{t("interval.anchorEnabled")}</label>
        {mode === "anchor" && <label>{t("interval.anchorTime")}<input type="datetime-local" step="60" value={anchorTime} onChange={(event) => { setAnchorTime(event.target.value); setFeedback(null); }} /></label>}
        <label><input type="checkbox" checked={mode === "calendar"} onChange={(event) => {
          setMode(event.target.checked ? "calendar" : "default"); setCustomEdited(true); setFeedback(null);
          if (event.target.checked && !["d", "w", "M"].includes(parseIntervalParts(custom)?.unit ?? "")) setCustom("1d");
        }} />{t("interval.calendarEnabled")}</label>
        {mode === "calendar" && <select aria-label={t("interval.calendarZone")} value={zone} onChange={(event) => { setZone(event.target.value as CalendarZone); setFeedback(null); }}>
          {CALENDAR_ZONES.map(value => <option key={value} value={value}>{value}</option>)}
        </select>}
        <button type="submit" disabled={!customSupport.supported}>{t("local.switch")}</button>
      </form>
      <span
        className={`local-interval-feedback ${customSupport.supported ? "ok" : "error"}`}
        role={customSupport.supported ? "status" : "alert"}
      >
        {feedback ?? (customEdited ? customSupport.message : "")}
      </span>
    </div>
  );
}
