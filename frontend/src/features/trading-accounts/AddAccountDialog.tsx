import { useState } from "react";
import { Badge, Button, Dialog, Field, InlineAlert, Input } from "../../components/ui/index.js";
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

  const creatable = preset === "practice" || preset === "manual";
  return (
    <Dialog
      open
      onClose={onClose}
      dismissible={!busy}
      title={t("trading.add.title")}
      className="trading-add-dialog"
      footer={<>
        <Button onClick={onClose}>{t("trading.cancel")}</Button>
        <Button variant="primary" disabled={busy || !creatable} onClick={() => { void submit(); }}>
          {t("trading.add.create")}
        </Button>
      </>}
    >
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
            {item.planned && <Badge className="trading-preset-badge">{t("trading.add.planned")}</Badge>}
          </button>
        ))}
      </div>
      <Field label={t("trading.add.name")}>
        <Input
          value={name}
          maxLength={80}
          placeholder={t(preset === "manual" ? "trading.kind.manual" : "trading.kind.practice")}
          onChange={(event) => setName(event.target.value)}
        />
      </Field>
      {preset === "practice" && (
        <>
          <div className="trading-field-row">
            <Field label={t("trading.add.initialBalance")}>
              <Input inputMode="decimal" value={initialBalance} onChange={(event) => setInitialBalance(event.target.value)} />
            </Field>
            <Field label={t("trading.add.leverage")}>
              <Input inputMode="decimal" value={leverage} onChange={(event) => setLeverage(event.target.value)} />
            </Field>
          </div>
          <div className="trading-field-row">
            <Field label={t("trading.add.takerFee")}>
              <Input inputMode="decimal" value={takerFeeRate} onChange={(event) => setTakerFeeRate(event.target.value)} />
            </Field>
            <Field label={t("trading.add.makerFee")}>
              <Input inputMode="decimal" value={makerFeeRate} onChange={(event) => setMakerFeeRate(event.target.value)} />
            </Field>
            <Field label={t("trading.add.slippage")}>
              <Input inputMode="decimal" value={slippageBps} onChange={(event) => setSlippageBps(event.target.value)} />
            </Field>
          </div>
          <p className="trading-help">{t("trading.add.practiceModel")}</p>
        </>
      )}
      {error && <InlineAlert tone="danger">{error}</InlineAlert>}
    </Dialog>
  );
}
