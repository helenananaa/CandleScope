import { getDateTimeLocale, t, type LocaleId } from "../../i18n/index.js";
import { InlineAlert } from "../../components/ui/index.js";
import type { AccountStatus } from "./accountApi.js";
import { feeRateEstimate, formatFeeRate } from "./accountFees.js";

/** Fee-rate estimates, kept apart from the fees fills and bills actually record. */
export default function AccountFeeRates({ snapshots, locale, date }: {
  snapshots: AccountStatus["snapshots"];
  locale: LocaleId;
  date: (ms: number | null | undefined) => string;
}) {
  const estimate = feeRateEstimate(snapshots);
  const percent = (value: string | null) => {
    if (value === null) return "—";
    const { text, rebate } = formatFeeRate(value, getDateTimeLocale(locale));
    return rebate ? t("account.feeRebate", { rate: text }, locale) : text;
  };
  return <section className="readonly-account-section" aria-label={t("account.feeRates", {}, locale)}>
    <h4>{t("account.feeRates", {}, locale)}</h4>
    <p className="readonly-account-help">{t("account.feeRatesHelp", {}, locale)}</p>
    {!estimate && <p className="readonly-account-empty">{t("account.feeRatesPending", {}, locale)}</p>}
    {estimate?.error && <InlineAlert tone="warning">
      {t(estimate.settlements.length ? "account.feeRatesStale" : "account.feeRatesUnavailable", {}, locale)} <code>{estimate.error}</code>
    </InlineAlert>}
    {estimate?.settlements.map(({ settlement, rates }) => <article className="readonly-account-card" key={settlement}>
      <strong>{t(settlement === "usdtMargined" ? "account.feeUsdtMargined" : "account.feeCoinMargined", {}, locale)}</strong>
      <dl>
        <dt>{t("account.makerRate", {}, locale)}</dt><dd>{percent(rates.maker)}</dd>
        <dt>{t("account.takerRate", {}, locale)}</dt><dd>{percent(rates.taker)}</dd>
      </dl>
    </article>)}
    {estimate && estimate.settlements.length > 0 && <p className="readonly-account-help">
      {t("account.feeTier", { tier: estimate.tier ?? t("account.unknown", {}, locale), time: date(estimate.exchangeTimeMs) }, locale)}
    </p>}
  </section>;
}
