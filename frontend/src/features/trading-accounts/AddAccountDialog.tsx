import { useState } from "react";
import { createPortal } from "react-dom";
import { t, type MessageKey } from "../../i18n/index.js";
import { useLocale } from "../../i18n/useLocale.js";
import { tradingErrorMessage } from "./useTradingAccountsRuntime.js";

type Preset = "practice" | "manual" | "exchange_readonly" | "exchange_trading";

const PRESETS: ReadonlyArray<{ id: Preset; titleKey: MessageKey; bodyKey: MessageKey; planned: boolean }> = [
  { id: "practice", titleKey: "trading.kind.practice", bodyKey: "trading.add.practiceBody", planned: false },
  { id: "manual", titleKey: "trading.kind.manual", bodyKey: "trading.add.manualBody", planned: false },
  { id: "exchange_readonly", titleKey: "trading.kind.exchangeReadonly", bodyKey: "trading.add.readonlyBody", planned: true },
  { id: "exchange_trading", titleKey: "trading.kind.exchangeTrading", bodyKey: "trading.add.tradingBody", planned: true },
];

export default function AddAccountDialog({
  onCreate,
  onClose,
}: {
  onCreate(body: Record<string, unknown>): Promise<unknown>;
  onClose(): void;
}) {
  useLocale();
  const [preset, setPreset] = useState<Preset>("practice");
  const [name, setName] = useState("");
  const [initialBalance, setInitialBalance] = useState("10000");
  const [leverage, setLeverage] = useState("10");
  const [takerFeeRate, setTakerFeeRate] = useState("0.0005");
  const [makerFeeRate, setMakerFeeRate] = useState("0.0002");
  const [slippageBps, setSlippageBps] = useState("1");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (preset !== "practice" && preset !== "manual") return;
    setBusy(true);
    setError(null);
    try {
      await onCreate({
        kind: preset,
        name: name.trim() || t(preset === "practice" ? "trading.kind.practice" : "trading.kind.manual"),
        ...(preset === "practice"
          ? { settings: { initialBalance, leverage, takerFeeRate, makerFeeRate, slippageBps } }
          : {}),
      });
      onClose();
    } catch (cause) {
      setError(tradingErrorMessage(cause));
    } finally {
      setBusy(false);
    }
  };

  return createPortal(
    <div className="trading-modal-backdrop" role="presentation" onMouseDown={onClose}>
      <div
        className="trading-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="trading-add-title"
        onMouseDown={(event) => event.stopPropagation()}
        onKeyDown={(event) => { if (event.key === "Escape") onClose(); }}
      >
        <header className="trading-modal-header">
          <h2 id="trading-add-title">{t("trading.add.title")}</h2>
          <button type="button" className="trading-icon-button" aria-label={t("trading.close")} onClick={onClose}>×</button>
        </header>
        <div className="trading-preset-grid" role="radiogroup" aria-label={t("trading.add.kind")}>
          {PRESETS.map((item) => (
            <button
              key={item.id}
              type="button"
              role="radio"
              aria-checked={preset === item.id}
              aria-disabled={item.planned}
              className="trading-preset"
              data-selected={preset === item.id}
              data-planned={item.planned}
              onClick={() => { if (!item.planned) setPreset(item.id); }}
            >
              <strong>{t(item.titleKey)}</strong>
              <span>{t(item.bodyKey)}</span>
              {item.planned && <em className="trading-badge" data-tone="muted">{t("trading.add.planned")}</em>}
            </button>
          ))}
        </div>
        <label className="trading-field">
          <span>{t("trading.add.name")}</span>
          <input
            value={name}
            maxLength={80}
            placeholder={t(preset === "manual" ? "trading.kind.manual" : "trading.kind.practice")}
            onChange={(event) => setName(event.target.value)}
          />
        </label>
        {preset === "practice" && (
          <>
            <div className="trading-field-row">
              <label className="trading-field">
                <span>{t("trading.add.initialBalance")}</span>
                <input inputMode="decimal" value={initialBalance} onChange={(event) => setInitialBalance(event.target.value)} />
              </label>
              <label className="trading-field">
                <span>{t("trading.add.leverage")}</span>
                <input inputMode="decimal" value={leverage} onChange={(event) => setLeverage(event.target.value)} />
              </label>
            </div>
            <div className="trading-field-row">
              <label className="trading-field">
                <span>{t("trading.add.takerFee")}</span>
                <input inputMode="decimal" value={takerFeeRate} onChange={(event) => setTakerFeeRate(event.target.value)} />
              </label>
              <label className="trading-field">
                <span>{t("trading.add.makerFee")}</span>
                <input inputMode="decimal" value={makerFeeRate} onChange={(event) => setMakerFeeRate(event.target.value)} />
              </label>
              <label className="trading-field">
                <span>{t("trading.add.slippage")}</span>
                <input inputMode="decimal" value={slippageBps} onChange={(event) => setSlippageBps(event.target.value)} />
              </label>
            </div>
            <p className="trading-help">{t("trading.add.practiceModel")}</p>
          </>
        )}
        {error && <p className="trading-error" role="alert">{error}</p>}
        <footer className="trading-modal-footer">
          <button type="button" className="trading-button" onClick={onClose}>{t("trading.cancel")}</button>
          <button
            type="button"
            className="trading-button"
            data-variant="primary"
            disabled={busy || (preset !== "practice" && preset !== "manual")}
            onClick={() => { void submit(); }}
          >
            {t("trading.add.create")}
          </button>
        </footer>
      </div>
    </div>,
    document.body,
  );
}
