import { createRoot } from "react-dom/client";
import { flushSync } from "react-dom";
import PracticeOrderTicket from "./PracticeOrderTicket.js";
import type { PracticeOrder, TradingAccount, TradingChartContext } from "./tradingTypes.js";

function assert(condition: unknown, message: string): asserts condition { if (!condition) throw new Error(message); }
const settle = () => new Promise(resolve => setTimeout(resolve, 0));
async function until<T>(read: () => T | null | undefined | false, message: string, timeoutMs = 5_000): Promise<T> {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) { const value = read(); if (value) return value; await settle(); }
  throw new Error(message);
}

type Action = "openLong" | "openShort" | "closeLong" | "closeShort";
/**
 * The intent each HEDGE action must send. The backend derives the side from it
 * (`buy` when LONG opens or SHORT closes) and rejects a side or reduceOnly that
 * disagrees, so the ticket must send all four fields consistently.
 */
const HEDGE_INTENTS: Record<Action, { side: "buy" | "sell"; positionSide: "LONG" | "SHORT"; positionEffect: "open" | "close"; reduceOnly: boolean }> = {
  openLong: { side: "buy", positionSide: "LONG", positionEffect: "open", reduceOnly: false },
  openShort: { side: "sell", positionSide: "SHORT", positionEffect: "open", reduceOnly: false },
  closeLong: { side: "sell", positionSide: "LONG", positionEffect: "close", reduceOnly: true },
  closeShort: { side: "buy", positionSide: "SHORT", positionEffect: "close", reduceOnly: true },
};

const account = (positionMode: "HEDGE" | "ONE_WAY"): TradingAccount => ({ id: `qa-${positionMode.toLowerCase()}`, kind: "practice",
  name: "QA practice", quoteCurrency: "USDT", createdAtMs: 1_800_000_000_000, archived: false,
  settings: { positionMode, initialBalance: "10000", takerFeeRate: "0.0005", makerFeeRate: "0.0002", slippageBps: "1", leverage: "10" },
  capabilities: { placeOrders: true, manualFills: false, sync: false } });
type Market = "futures" | "spot" | "swap.linear" | "swap.inverse" | "stock" | "index.future" | "index.future.published";
const context = (marketType: Market): TradingChartContext => marketType === "stock"
  ? { exchange: "twelvedata", marketType, symbol: "AAPL:NASDAQ", interval: "1m", lastPrice: 100 }
  : marketType.startsWith("index.future") ? { exchange: "acme", marketType, symbol: "ESZ6", interval: "1m", lastPrice: 5000 }
  : { exchange: marketType.startsWith("swap") ? "gate" : "binance", marketType, symbol: "BTCUSDT", interval: "1m", lastPrice: 100 };
/**
 * The backend's market rules (ADR-DATA-002 D5b, D5d): Gate's linear swaps are contracts, its inverse
 * swaps open nothing, and index futures hold a margin per contract of 50 index units.
 */
const RULES: Record<Market, string> = { futures: "crypto_linear", spot: "cash", "swap.linear": "crypto_linear", "swap.inverse": "crypto_inverse",
  stock: "cash", "index.future": "futures_margin", "index.future.published": "futures_margin" };

/** The actual ticket, clicked like a user: every HEDGE action sends its own intent. */
export async function checkPracticeOrderTicket() {
  const originalFetch = window.fetch;
  const requests: { path: string; body: Record<string, unknown> }[] = [];
  const margins: { path: string; body: Record<string, unknown> }[] = [];
  let accountMargin: string | null = null;
  const rulesFor = (market: Market) => {
    const model = RULES[market];
    const contract = model !== "cash";
    // D5c: a stock is priced in USD and trades whole shares; crypto here is priced in the account's USDT.
    const stock = market === "stock" ? { currency: "USD", quantityStep: "1", minQuantity: "1" } : { currency: "USDT" };
    // D5d: one contract is 50 index units; the margin is published or the account's own figure.
    const margin = market === "index.future.published" ? "20000" : market === "index.future" ? accountMargin : null;
    const future = model === "futures_margin" ? {
      currency: "USD", quantityStep: "50", minQuantity: "50", contractSize: "50",
      ...(margin ? { marginPerContract: margin, marginSource: market === "index.future" ? "account" : "catalog" } : {}),
    } : {};
    return { accountModel: model, declared: true, leverage: model === "crypto_linear", shorting: contract, hedge: contract,
      opensPositions: model === "cash" || model === "crypto_linear" || Boolean(margin), ...stock, ...future };
  };
  window.fetch = async (input, init) => {
    const url = new URL(input instanceof Request ? input.url : String(input), location.href);
    const path = url.pathname;
    if ((init?.method ?? "GET") === "GET" && path.endsWith("/trading/market-rules")) {
      return Response.json(rulesFor(url.searchParams.get("marketType") as Market));
    }
    if (init?.method === "PUT" && /\/trading\/accounts\/[^/]+\/contract-margins$/.test(path)) {
      const body = JSON.parse(String(init.body)) as Record<string, unknown>;
      margins.push({ path, body });
      accountMargin = typeof body.marginPerContract === "string" ? body.marginPerContract : null;
      return Response.json(rulesFor(body.marketType as Market));
    }
    assert(init?.method === "POST" && /\/trading\/accounts\/[^/]+\/orders$/.test(path), `unexpected request: ${init?.method ?? "GET"} ${path}`);
    const body = JSON.parse(String(init.body)) as Record<string, unknown>;
    requests.push({ path, body });
    const order: Partial<PracticeOrder> = { id: `ord_${requests.length}`, status: "filled", fillPrice: "100" };
    return Response.json({ order, priceSource: "client" });
  };
  const host = document.createElement("div"); document.body.append(host);
  const root = createRoot(host);
  let placed = 0;
  const render = (positionMode: "HEDGE" | "ONE_WAY", marketType: Market) => flushSync(() => root.render(
    <PracticeOrderTicket key={positionMode + marketType} account={account(positionMode)} summary={null} context={context(marketType)}
      onPlaced={() => { placed += 1; }} onPlanTrade={() => undefined} />));
  const actionGroup = () => host.querySelectorAll<HTMLElement>(".trading-ticket [role=radiogroup]")[0];
  const field = (index: number) => {
    const inputs = host.querySelectorAll<HTMLInputElement>(".trading-ticket input[inputmode=decimal]");
    assert(inputs[index], `ticket input ${index} missing`);
    return inputs[index];
  };
  const type = (input: HTMLInputElement, value: string) => flushSync(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  const submitButton = () => {
    const button = host.querySelector<HTMLButtonElement>(".trading-submit");
    assert(button, "submit button missing");
    return button;
  };
  async function submit() {
    const before = requests.length;
    const button = submitButton();
    assert(!button.disabled, "submit stayed disabled with a quantity");
    flushSync(() => button.click());
    await until(() => requests.length === before + 1 && host.querySelector(".ui-inline-alert, [role=status], [role=alert]"), "order was not sent or acknowledged");
    return requests.at(-1)!.body;
  }
  const checks: Record<string, unknown> = {};
  try {
    render("HEDGE", "futures");
    const offered = [...actionGroup()!.querySelectorAll<HTMLButtonElement>("[role=radio]")].map(button => button.dataset.value);
    assert(offered.join() === "openLong,openShort,closeLong,closeShort", `HEDGE ticket offered ${offered.join()}`);
    assert(!host.querySelector(".trading-ticket input[type=checkbox]"), "HEDGE ticket offered a reduce-only box; the action decides it");
    type(field(0), "2");
    for (const action of ["openLong", "openShort", "closeLong", "closeShort"] as const) {
      const segment = actionGroup()!.querySelector<HTMLButtonElement>(`[data-value=${action}]`);
      assert(segment, `${action} segment missing`);
      flushSync(() => segment.click()); await settle();
      assert(segment.getAttribute("aria-checked") === "true", `${action} was not selected`);
      const intent = HEDGE_INTENTS[action];
      const opening = intent.positionEffect === "open";
      // Opening shows the bracket fields; enter both so a later close proves it drops them.
      const decimals = host.querySelectorAll(".trading-ticket input[inputmode=decimal]").length;
      assert(decimals === (opening ? 3 : 1), `${action} showed ${decimals} price fields`);
      if (opening) { type(field(1), action === "openLong" ? "95" : "105"); type(field(2), action === "openLong" ? "110" : "90"); }
      assert(submitButton().dataset.side === intent.side, `${action} button shows ${submitButton().dataset.side}`);
      const body = await submit();
      const sent = { side: body.side, positionSide: body.positionSide, positionEffect: body.positionEffect, reduceOnly: body.reduceOnly };
      assert(JSON.stringify(sent) === JSON.stringify(intent), `${action} sent ${JSON.stringify(sent)}, expected ${JSON.stringify(intent)}`);
      assert(body.type === "market" && body.qty === "2" && body.symbol === "BTCUSDT" && body.marketType === "futures"
        && body.referencePrice === "100", `${action} sent the wrong order: ${JSON.stringify(body)}`);
      if (opening) {
        assert(body.bracketStop === (action === "openLong" ? "95" : "105") && body.bracketTarget === (action === "openLong" ? "110" : "90"),
          `${action} dropped its bracket: ${JSON.stringify(body)}`);
      } else {
        assert(!("bracketStop" in body) && !("bracketTarget" in body), `${action} sent a bracket on a closing order: ${JSON.stringify(body)}`);
      }
      checks[action] = sent;
    }
    assert(placed === 4, `onPlaced ran ${placed} times for four orders`);

    // One-way futures and spot keep the plain side ticket and send no hedge intent,
    // which the backend rejects on those markets.
    for (const [mode, market] of [["ONE_WAY", "futures"], ["HEDGE", "spot"]] as const) {
      render(mode, market);
      const sides = [...actionGroup()!.querySelectorAll<HTMLButtonElement>("[role=radio]")].map(button => button.dataset.value);
      assert(sides.join() === "buy,sell", `${mode} ${market} ticket offered ${sides.join()}`);
      type(field(0), "1");
      const body = await submit();
      assert(!("positionSide" in body) && !("positionEffect" in body) && body.side === "buy" && body.reduceOnly === false,
        `${mode} ${market} sent hedge intent: ${JSON.stringify(body)}`);
      checks[`${mode}-${market}`] = { side: body.side, reduceOnly: body.reduceOnly };
    }

    // A linear swap on another venue declares the same contract rules as futures, so a HEDGE
    // account trades it by leg once the rules arrive; an inverse swap warns that it opens nothing.
    render("HEDGE", "swap.linear");
    const legs = await until(() => {
      const values = [...actionGroup()!.querySelectorAll<HTMLButtonElement>("[role=radio]")].map(button => button.dataset.value);
      return values.join() === "openLong,openShort,closeLong,closeShort" && values;
    }, "HEDGE swap.linear ticket never offered hedge actions");
    assert(!host.querySelector(".ui-alert[data-tone=warning]"), "a linear swap warned that it cannot open positions");
    render("ONE_WAY", "swap.inverse");
    await until(() => host.querySelector(".ui-alert[data-tone=warning]"), "an inverse swap showed no unsupported notice");
    checks["swap.linear"] = legs;

    // A cash stock (D5c) shows its whole-share grid, says it is priced in USD while the account
    // books USDT, and shows the account's fee rates; crypto priced in USDT shows no currency notice.
    render("HEDGE", "stock");
    const notice = await until(() => host.querySelector(".ui-alert[data-tone=info]")?.textContent, "a USD stock showed no currency notice");
    assert(notice.includes("USD") && notice.includes("USDT"), `currency notice reads ${notice}`);
    const hint = host.querySelector(".trading-ticket .ui-field-hint")?.textContent ?? "";
    assert(/\b1\b/.test(hint), `quantity hint reads ${JSON.stringify(hint)}`);
    const sides = [...actionGroup()!.querySelectorAll<HTMLButtonElement>("[role=radio]")].map(button => button.dataset.value);
    assert(sides.join() === "buy,sell", `a cash stock offered ${sides.join()}`);
    const fees = [...host.querySelectorAll(".trading-kv dd")].at(-1)?.textContent ?? "";
    assert(fees.includes("0.05") && fees.includes("0.02"), `fees row reads ${JSON.stringify(fees)}`);
    render("ONE_WAY", "spot");
    await until(() => host.querySelector(".trading-ticket .ui-field-hint") === null && host.querySelector(".trading-ticket"), "spot ticket did not render");
    await settle(); await settle();
    assert(!host.querySelector(".ui-alert[data-tone=info]"), "a USDT market showed a currency notice on a USDT account");
    checks.stock = { notice, hint, fees };

    // A per-contract future (D5d) whose source publishes no margin asks for the account's figure,
    // counts the quantity in contracts of 50 and holds the margin per contract once it is saved.
    render("HEDGE", "index.future");
    const save = await until(() => host.querySelector<HTMLButtonElement>(".trading-margin-save"), "no margin input for an unpublished margin");
    await until(() => host.querySelector(".ui-alert[data-tone=warning]"), "an unpublished margin showed no warning");
    const values = () => [...host.querySelectorAll(".trading-kv dd")].map(node => node.textContent ?? "");
    type(field(0), "400");
    assert(values()[4]?.includes("50") && values()[5] === "8" && values()[6] === "—", `contract rows read ${JSON.stringify(values())}`);
    const marginInput = save.closest(".trading-field-row")?.querySelector<HTMLInputElement>("input");
    assert(marginInput, "margin input missing");
    type(marginInput, "12000");
    flushSync(() => save.click());
    await until(() => margins.length === 1 && !host.querySelector(".ui-alert[data-tone=warning]"), "saving the margin did not clear the warning");
    assert(margins[0]!.path.endsWith("/accounts/qa-hedge/contract-margins")
      && JSON.stringify(margins[0]!.body) === JSON.stringify({ exchange: "acme", marketType: "index.future", symbol: "ESZ6", marginPerContract: "12000" }),
      `margin request ${JSON.stringify(margins[0])}`);
    await until(() => /96/.test(values()[6] ?? ""), `margin row reads ${JSON.stringify(values())}`);
    const future = await submit();
    assert(future.qty === "400" && future.positionSide === "LONG", `future order ${JSON.stringify(future)}`);
    // A published margin is shown, not asked for.
    render("HEDGE", "index.future.published");
    await until(() => values().length === 8, `published margin rows read ${JSON.stringify(values())}`);
    assert(!host.querySelector(".trading-margin-save") && values()[6]?.includes("20") && values()[6]?.includes("USD"),
      `published margin reads ${JSON.stringify(values())}`);
    checks.futureMargin = { saved: margins[0]!.body, rows: values() };
    return { passed: true, checks, scope: "Actual PracticeOrderTicket with a controlled order endpoint; not backend matching" };
  } finally { window.fetch = originalFetch; flushSync(() => root.unmount()); host.remove(); }
}
