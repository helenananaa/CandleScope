# Trading accounts

The live page's "Accounts" rail view: local practice trading, manual fill
entry, the three-stage trade journal and quick replay. The backend owner is
`backend/app/trading_accounts` behind `/api/v1/trading`.

## Accounts

- `practice`: virtual funds on this computer. Orders are matched by the backend
  against live 1m candles (see the backend README). Nothing reaches an exchange.
- `manual`: fills entered by hand, for trades made elsewhere.
- `exchange_readonly` / `exchange_trading` are shown as planned and cannot be
  created until a verified connector exists.

The Accounts view is host-owned (`hostOwned` in `marketRailTypes.ts`): plugin
rail contributions cannot replace it, because it can place orders.

## Journal

One template document per trade plus timestamped quick notes. The stage is not
chosen: it follows from when a revision was saved relative to the linked trade.
Pre-trade fields first written after the first fill carry a "written after
entry" badge. Entry, stop, target and risk (USDT) are locked at the first fill
and are the only R denominator. `auto` template fields render from the ledger
and are never stored as text.

## Quick replay

`QuickReplayOverlay` covers the chart cell while the live source is paused. It
loads a bounded candle window once and keeps a `SeriesWindowStore` that only
holds candles closed before the cursor; the forming candle is rebuilt from finer
candles when the step is smaller than the chart interval (`quickReplayModel.ts`).
Fill markers, notes, position and P&L use the same cut. Indicators run through
`useProvidedBarsIndicatorRuntime`, which computes on exactly the bars shown and
resets on rewind. Current drawings are not shown; snapshot images are the
record of what was on the chart at the time.
