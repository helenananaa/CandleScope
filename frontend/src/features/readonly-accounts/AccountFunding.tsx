import { useEffect, useState } from "react";
import { t, type LocaleId, type MessageKey } from "../../i18n/index.js";
import { InlineAlert } from "../../components/ui/index.js";
import { AccountApiError, getFundingHistory, type AccountStatus } from "./accountApi.js";
import { accountErrorHelp } from "./accountErrors.js";
import {
  fundingBalances, fundingHistory, fundingReadError, shownAmount,
  type FundingHistory, type FundingRow, type FundingState, type TransferAccount,
} from "./fundingRows.js";

const STATE_LABEL: Record<FundingState, MessageKey> = {
  pending: "account.status.pending", completed: "account.status.completed", failed: "account.status.failed",
  canceled: "account.status.canceled", held: "account.status.held", unknown: "account.unknown",
};
const ACCOUNT_LABEL: Record<TransferAccount, MessageKey> = {
  funding: "account.fundingAccount", trading: "account.tradingAccount", other: "account.otherAccount",
};
const KIND_LABEL: Record<FundingRow["kind"], MessageKey> = {
  deposit: "account.deposit", withdrawal: "account.withdrawal", transfer: "account.transfer",
};

/** The funding account: its balances and its deposits, withdrawals and transfers, apart from trading. */
export default function AccountFunding({ snapshots, locale, date }: {
  snapshots: AccountStatus["snapshots"];
  locale: LocaleId;
  date: (ms: number | null | undefined) => string;
}) {
  const balances = fundingBalances(snapshots);
  const balancesError = fundingReadError(snapshots, "funding_balances");
  const historyError = fundingReadError(snapshots, "funding_history");
  const historyRead = snapshots.funding_history_state?.receivedMs ?? null;
  const [history, setHistory] = useState<FundingHistory | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    getFundingHistory(controller.signal).then((value) => { setHistory(fundingHistory(value)); setLoadError(null); }, (failure: unknown) => {
      if (!controller.signal.aborted) setLoadError(failure instanceof AccountApiError ? failure.code : "ACCOUNT_UNAVAILABLE");
    });
    return () => controller.abort();
  }, [historyRead]);
  const failed = (code: string | null) => code && <InlineAlert tone="warning">
    {t("account.fundingReadFailed", {}, locale)} {t(accountErrorHelp(code), {}, locale)} <code>{code}</code>
  </InlineAlert>;
  const money = (value: string, currency: string) => `${value} ${currency}`;
  return <>
    <section className="readonly-account-section" aria-label={t("account.fundingBalances", {}, locale)}>
      <h4>{t("account.fundingBalances", {}, locale)}</h4>
      <p className="readonly-account-help">{t("account.fundingHelp", {}, locale)}</p>
      {balances && <p className="readonly-account-help">{t("account.snapshotTime", { time: date(balances.receivedMs) }, locale)}</p>}
      {failed(balancesError)}
      {!balances && !balancesError && <p className="readonly-account-empty">{t("account.fundingNotRead", {}, locale)}</p>}
      {balances?.balances.length === 0 && <p className="readonly-account-empty">{t("account.fundingEmpty", {}, locale)}</p>}
      {balances?.balances.map((row) => <article className="readonly-account-card" key={row.currency}>
        <strong>{row.currency}</strong>
        <dl>
          <dt>{t("account.fundingTotal", {}, locale)}</dt><dd>{row.total}</dd>
          <dt>{t("account.fundingAvailable", {}, locale)}</dt><dd>{row.available}</dd>
          <dt>{t("account.fundingFrozen", {}, locale)}</dt><dd>{row.frozen}</dd>
        </dl>
      </article>)}
    </section>
    <section className="readonly-account-section" aria-label={t("account.fundingHistory", {}, locale)}>
      <h4>{t("account.fundingHistory", {}, locale)}</h4>
      <p className="readonly-account-help">{t("account.fundingHistoryHelp", {}, locale)}</p>
      {history && <p className="readonly-account-help">{t("account.snapshotTime", { time: date(history.receivedMs) }, locale)}</p>}
      {failed(historyError ?? loadError)}
      {!history && !historyError && !loadError && <p className="readonly-account-empty">{t("account.fundingNotRead", {}, locale)}</p>}
      {history && !history.complete && <InlineAlert tone="warning">{t("account.fundingHistoryPartial", {}, locale)}</InlineAlert>}
      {history?.rows.length === 0 && <p className="readonly-account-empty">{t("account.fundingHistoryEmpty", {}, locale)}</p>}
      {history?.rows.map((row) => <article className="readonly-account-card" key={`${row.kind}:${row.id}`}>
        <strong>{t(KIND_LABEL[row.kind], {}, locale)} · {row.currency}</strong>
        <dl>
          <dt>{t("account.fundingAmount", {}, locale)}</dt><dd>{money(shownAmount(row), row.currency)}</dd>
          {row.kind === "transfer"
            ? <><dt>{t("account.transfer", {}, locale)}</dt><dd>{t("account.transferRoute", {
              from: t(ACCOUNT_LABEL[row.from], {}, locale), to: t(ACCOUNT_LABEL[row.to], {}, locale) }, locale)}</dd></>
            : <>
              {row.chain && <><dt>{t("account.chain", {}, locale)}</dt><dd>{row.chain}</dd></>}
              {row.kind === "withdrawal" && row.fee !== null && <><dt>{t("account.withdrawalFee", {}, locale)}</dt><dd>{money(row.fee, row.feeCurrency)}</dd></>}
              <dt>{t("account.status", {}, locale)}</dt><dd>{t(STATE_LABEL[row.state], {}, locale)}</dd>
            </>}
          <dt>{t("account.exchangeTime", {}, locale)}</dt><dd>{date(row.eventTimeMs)}</dd>
        </dl>
      </article>)}
    </section>
  </>;
}
