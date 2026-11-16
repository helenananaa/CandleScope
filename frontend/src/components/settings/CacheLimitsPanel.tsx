import { useEffect, useState, type KeyboardEvent } from "react";
import { SegmentedControl } from "../ui/Choice.js";
import { Disclosure, InlineAlert } from "../ui/Display.js";
import { Checkbox, Field, Input } from "../ui/Field.js";
import { t } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import type {
    CacheRowLimits,
    ChartSettings,
} from "../../features/settings/chartAppearanceSettings.js";

type CacheTierKey = keyof CacheRowLimits;
const CACHE_TIER_KEYS: CacheTierKey[] = ["seconds", "minutes", "hours", "daily"];

interface CacheTier {
    key: CacheTierKey;
    labelKey: "settings.cache.seconds" | "settings.cache.minutes" | "settings.cache.hours" | "settings.cache.daily";
    descKey: "settings.cache.secondsDesc" | "settings.cache.minutesDesc" | "settings.cache.hoursDesc" | "settings.cache.dailyDesc";
    representativeSec: number;
}

interface CachePreset {
    key: string;
    labelKey: "settings.cache.compact" | "settings.cache.standard" | "settings.cache.generous" | "settings.cache.unlimited";
    descKey: "settings.cache.compactDesc" | "settings.cache.standardDesc" | "settings.cache.generousDesc" | "settings.cache.unlimitedDesc";
    level: 1 | 2 | 3 | 4;
    limits: CacheRowLimits;
}

const EPHEMERAL_CACHE_OPTIONS = [
    { value: 3600, labelKey: "settings.cache.hour1" as const, bars: 3600 },
    { value: 14400, labelKey: "settings.cache.hour4" as const, bars: 14400 },
    { value: 43200, labelKey: "settings.cache.hour12" as const, bars: 43200 },
    { value: 86400, labelKey: "settings.cache.hour24" as const, bars: 86400 },
];

const DEFAULT_EPHEMERAL_BARS = 86400;
const DEFAULT_FRONTEND_CACHE_BUDGET_BYTES = 64 * 1024 * 1024;

const DB_TIERS: CacheTier[] = [
    {
        key: "seconds",
        labelKey: "settings.cache.seconds",
        descKey: "settings.cache.secondsDesc",
        representativeSec: 1,
    },
    {
        key: 'minutes',
        labelKey: 'settings.cache.minutes',
        descKey: 'settings.cache.minutesDesc',
        representativeSec: 60,
    },
    {
        key: 'hours',
        labelKey: 'settings.cache.hours',
        descKey: 'settings.cache.hoursDesc',
        representativeSec: 3600,
    },
    {
        key: 'daily',
        labelKey: 'settings.cache.daily',
        descKey: 'settings.cache.dailyDesc',
        representativeSec: 86400,
    },
];

const DB_PRESETS: CachePreset[] = [
    {
        key: 'compact',
        labelKey: 'settings.cache.compact',
        descKey: 'settings.cache.compactDesc',
        level: 1,
        limits: { seconds: 3600, minutes: 50000, hours: 20000, daily: 0 },
    },
    {
        key: 'standard',
        labelKey: 'settings.cache.standard',
        descKey: 'settings.cache.standardDesc',
        level: 2,
        limits: { seconds: 86400, minutes: 200000, hours: 50000, daily: 0 },
    },
    {
        key: 'generous',
        labelKey: 'settings.cache.generous',
        descKey: 'settings.cache.generousDesc',
        level: 3,
        limits: { seconds: 604800, minutes: 500000, hours: 100000, daily: 0 },
    },
    {
        key: 'unlimited',
        labelKey: 'settings.cache.unlimited',
        descKey: 'settings.cache.unlimitedDesc',
        level: 4,
        limits: { seconds: 0, minutes: 0, hours: 0, daily: 0 },
    },
];

const DEFAULT_DB_LIMITS: CacheRowLimits = { seconds: 86400, minutes: 200000, hours: 50000, daily: 0 };

function barsToHumanTime(bars: number, representativeSec: number): string {
    if (bars === 0) return t("settings.cache.noCleanup");
    const totalSec = bars * representativeSec;
    if (totalSec < 3600) return t("settings.cache.approxMinutes", { count: Math.round(totalSec / 60) });
    if (totalSec < 86400) return t("settings.cache.approxHours", { count: (totalSec / 3600).toFixed(1) });
    if (totalSec < 86400 * 365) return t("settings.cache.approxDays", { count: Math.round(totalSec / 86400) });
    return t("settings.cache.approxYears", { count: (totalSec / (86400 * 365)).toFixed(0) });
}

function barsToStorageSize(bars: number): string {
    if (bars === 0) return '--';
    const bytes = bars * 200;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function barsToMemorySize(bars: number): string {
    if (bars === 0) return '--';
    const bytes = bars * 200;
    if (bytes < 1024 * 1024) return `≈ ${(bytes / 1024).toFixed(0)} KB`;
    return `≈ ${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function bytesToGbInput(bytes: number | null): string {
    const value = Number(bytes || 0);
    if (!value) return '';
    return (value / 1024 / 1024 / 1024).toFixed(2);
}

function gbInputToBytes(value: string): number | null {
    const parsed = Number(value);
    if (!Number.isFinite(parsed) || parsed <= 0) return null;
    return Math.round(parsed * 1024 * 1024 * 1024);
}

function bytesToMbInput(bytes: number): string | number {
    const value = Number(bytes || 0);
    if (!value) return '';
    return Math.round(value / 1024 / 1024);
}

function mbInputToBytes(value: string): number {
    const parsed = Number(value);
    if (!Number.isFinite(parsed) || parsed <= 0) return DEFAULT_FRONTEND_CACHE_BUDGET_BYTES;
    return Math.round(parsed * 1024 * 1024);
}

export interface CacheLimitsPanelProps {
    settings: ChartSettings;
    onUpdate(settings: ChartSettings): void;
    showAdvanced: boolean;
    onToggleAdvanced(): void;
}

export default function CacheLimitsPanel({
    settings,
    onUpdate,
    showAdvanced,
}: CacheLimitsPanelProps) {
    const locale = useLocale();
    const currentPreset = settings.cachePreset || 'standard';
    const currentLimits = settings.cacheLimits || { ...DEFAULT_DB_LIMITS };
    const currentEphemeralBars = settings.ephemeralCacheBars ?? DEFAULT_EPHEMERAL_BARS;
    const currentFrontendBudget = settings.frontendCacheBudgetBytes ?? DEFAULT_FRONTEND_CACHE_BUDGET_BYTES;
    const currentSqliteBudget = settings.sqliteStorageBudgetBytes ?? null;
    const rowLimitsEnabled = Boolean(settings.storageRowLimitsEnabled);
    const isCustomPreset = currentPreset === 'custom';
    const [frontendBudgetDraft, setFrontendBudgetDraft] = useState(
        String(bytesToMbInput(currentFrontendBudget)),
    );
    const [sqliteBudgetDraft, setSqliteBudgetDraft] = useState(
        bytesToGbInput(currentSqliteBudget),
    );

    useEffect(() => {
        setFrontendBudgetDraft(String(bytesToMbInput(currentFrontendBudget)));
    }, [currentFrontendBudget]);

    useEffect(() => {
        setSqliteBudgetDraft(bytesToGbInput(currentSqliteBudget));
    }, [currentSqliteBudget]);

    const handlePresetChange = (presetKey: string) => {
        const preset = DB_PRESETS.find((item) => item.key === presetKey);
        if (preset) {
            onUpdate({
                ...settings,
                cachePreset: presetKey,
                cacheLimits: { ...preset.limits },
            });
        }
    };

    const handleLimitChange = (tierKey: CacheTierKey, value: number) => {
        const newLimits = { ...currentLimits, [tierKey]: value };
        const matchingPreset = DB_PRESETS.find((preset) =>
            CACHE_TIER_KEYS.every((key) => preset.limits[key] === newLimits[key])
        );
        onUpdate({
            ...settings,
            cachePreset: matchingPreset ? matchingPreset.key : 'custom',
            cacheLimits: newLimits,
        });
    };

    const handleEphemeralChange = (value: number) => {
        onUpdate({
            ...settings,
            ephemeralCacheBars: value,
        });
    };

    const commitFrontendBudget = () => {
        const parsed = Number(frontendBudgetDraft);
        if (!Number.isFinite(parsed) || parsed < 16 || parsed > 4096) {
            setFrontendBudgetDraft(String(bytesToMbInput(currentFrontendBudget)));
            return;
        }
        onUpdate({
            ...settings,
            frontendCacheBudgetBytes: mbInputToBytes(frontendBudgetDraft),
        });
    };

    const commitSqliteBudget = () => {
        const parsed = Number(sqliteBudgetDraft);
        if (sqliteBudgetDraft !== '' && (!Number.isFinite(parsed) || parsed <= 0 || parsed > 16384)) {
            setSqliteBudgetDraft(bytesToGbInput(currentSqliteBudget));
            return;
        }
        onUpdate({
            ...settings,
            sqliteStorageBudgetBytes: gbInputToBytes(sqliteBudgetDraft),
        });
    };

    const handleRowLimitsEnabledChange = (enabled: boolean) => {
        onUpdate({
            ...settings,
            storageRowLimitsEnabled: enabled,
        });
    };

    // Enter commits (by blurring); Escape restores the saved value.
    const budgetKeys = (reset: () => void) => (event: KeyboardEvent<HTMLInputElement>) => {
        if (event.key === 'Enter') event.currentTarget.blur();
        if (event.key === 'Escape') {
            event.preventDefault();
            reset();
        }
    };

    return (
        <>
            <section className="st-group">
                <div className="st-group-title">{t("settings.cache.ephemeralTitle")}</div>
                <div className="st-group-desc">{t("settings.cache.ephemeralSummary")}</div>
                <SegmentedControl
                    label={t("settings.cache.ephemeralTitle")}
                    value={String(currentEphemeralBars)}
                    onChange={(value) => handleEphemeralChange(Number(value))}
                    options={EPHEMERAL_CACHE_OPTIONS.map((option) => ({ value: String(option.value), label: t(option.labelKey) }))}
                />
                <dl className="st-kv st-kv-inline">
                    <dt>{t("settings.cache.capacity")}</dt>
                    <dd>{t("settings.cache.bars", { count: currentEphemeralBars.toLocaleString(locale) })}</dd>
                    <dt>{t("settings.cache.coverage")}</dt>
                    <dd>{barsToHumanTime(currentEphemeralBars, 1).replace('≈ ', '')}</dd>
                    <dt>{t("settings.cache.memoryUse")}</dt>
                    <dd>{barsToMemorySize(currentEphemeralBars)} {t("settings.cache.perSymbol")}</dd>
                </dl>
            </section>

            <section className="st-group">
                <div className="st-group-title">{t("settings.cache.dbTitle")}</div>
                <div className="st-group-desc">{t("settings.cache.dbSummary")}</div>
                <div className="st-preset-cards">
                    {DB_PRESETS.map((preset) => (
                        <button
                            key={preset.key}
                            type="button"
                            className={`st-preset-card ${currentPreset === preset.key ? 'active' : ''}`}
                            aria-pressed={currentPreset === preset.key}
                            onClick={() => handlePresetChange(preset.key)}
                        >
                            <span className="st-preset-level" aria-hidden="true">{[1, 2, 3, 4].map((step) => <span key={step} className={step <= preset.level ? "on" : undefined} />)}</span>
                            <span className="st-preset-name">{t(preset.labelKey)}</span>
                            <span className="st-preset-desc">{t(preset.descKey)}</span>
                        </button>
                    ))}
                </div>
                {isCustomPreset && <InlineAlert>{t("settings.cache.custom")}</InlineAlert>}
                <div className="st-budget-fields">
                    <Field label={`${t("settings.cache.frontendBudget")} (MB)`} hint={t("settings.cache.frontendBudgetHint")}>
                        <Input
                            type="number"
                            value={frontendBudgetDraft}
                            min={16}
                            max={4096}
                            step={16}
                            onChange={(event) => setFrontendBudgetDraft(event.target.value)}
                            onBlur={commitFrontendBudget}
                            onKeyDown={budgetKeys(() => setFrontendBudgetDraft(String(bytesToMbInput(currentFrontendBudget))))}
                            title={t("settings.cache.frontendBudgetTitle")}
                        />
                    </Field>
                    <Field label={`${t("settings.cache.sqliteBudget")} (GB)`} hint={t("settings.cache.sqliteBudgetHint")}>
                        <Input
                            type="number"
                            value={sqliteBudgetDraft}
                            min={0}
                            max={16384}
                            step={0.25}
                            placeholder={t("settings.cache.unset")}
                            onChange={(event) => setSqliteBudgetDraft(event.target.value)}
                            onBlur={commitSqliteBudget}
                            onKeyDown={budgetKeys(() => setSqliteBudgetDraft(bytesToGbInput(currentSqliteBudget)))}
                            title={t("settings.cache.sqliteBudgetTitle")}
                        />
                    </Field>
                </div>
            </section>

            <section className="st-group">
                <Disclosure summary={t("settings.cache.advanced")} defaultOpen={showAdvanced}>
                    <div className="st-limits">
                        <p className="st-group-desc">{t("settings.cache.advancedDesc")}</p>
                        <Checkbox
                            label={t("settings.cache.enableRowLimits")}
                            checked={rowLimitsEnabled}
                            onChange={(event) => handleRowLimitsEnabledChange(event.target.checked)}
                        />
                        <table className="st-limits-table">
                            <thead>
                                <tr>
                                    <th scope="col">{t("settings.cache.tier")}</th>
                                    <th scope="col">{t("settings.cache.maxBars")}</th>
                                    <th scope="col">{t("settings.cache.duration")}</th>
                                    <th scope="col">{t("settings.cache.disk")}</th>
                                </tr>
                            </thead>
                            <tbody>
                                {DB_TIERS.map((tier) => {
                                    const limit = currentLimits[tier.key] ?? 0;
                                    return (
                                        <tr key={tier.key}>
                                            <th scope="row">
                                                {t(tier.labelKey)}
                                                <span>{t(tier.descKey)}</span>
                                            </th>
                                            <td>
                                                {rowLimitsEnabled && tier.key !== 'daily' ? (
                                                    <Input
                                                        size="sm"
                                                        type="number"
                                                        aria-label={`${t(tier.labelKey)} · ${t("settings.cache.maxBars")}`}
                                                        value={limit}
                                                        min={0}
                                                        step={1000}
                                                        onChange={(event) => handleLimitChange(tier.key, Math.max(0, parseInt(event.target.value) || 0))}
                                                        title={t("settings.cache.zeroNoCleanup")}
                                                    />
                                                ) : (
                                                    <span className="st-limits-value">
                                                        {!rowLimitsEnabled ? t("settings.cache.off") : limit === 0 ? '∞' : limit.toLocaleString(locale)}
                                                    </span>
                                                )}
                                            </td>
                                            <td>{barsToHumanTime(limit, tier.representativeSec)}</td>
                                            <td>{barsToStorageSize(limit)}</td>
                                        </tr>
                                    );
                                })}
                            </tbody>
                        </table>
                        <p className="st-group-desc">{t("settings.cache.zeroHint")}</p>
                    </div>
                </Disclosure>
            </section>
        </>
    );
}
