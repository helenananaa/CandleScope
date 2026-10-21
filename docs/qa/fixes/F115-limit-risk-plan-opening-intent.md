# F115: opening intent for limit risk plans

The ticket exposed risk-based sizing for limit orders but sent `NET` to order
capacity/preview, including the fresh preflight before submission. The backend
correctly rejected the plan because plans require opening orders. A normal
production-package run reproduced the failure with a valid 63.5 limit, 0.5 risk,
63 invalidation and 64.5 target. The market-order control rendered its expected
quantity/risk/reward ratio; neither native case placed an order.

Use `OPEN` for enabled eligible opening risk plans and share that intent between
scheduled advisory requests and fresh submission validation. Include it in the
capacity and sizing identities so changing the plan does not reuse a `NET`
context. Plain limit, reduce-only and protection semantics retain `NET`; market
opening orders retain `OPEN`. The backend opening-only guard and sizing,
matching, fees and account math are unchanged.

Validation: 600 replay frontend tests, type checks, scoped ESLint and production
build pass. An actual mounted React ticket reproduced the rejected scheduled and
fresh requests before the change, then sent `OPEN` and preserved fixed-risk and
percentage-plan payloads after it. Turning the plan off/on refreshed `NET`/`OPEN`
capacity contexts. That advisory fixture used only local mocks; its submissions
are not real trading or financial acceptance evidence. Temporary fixture files,
Vite and the browser tab were removed/stopped after preserving receipts outside
the product checkout.

Native fix qualification remains pending on the combined official candidate,
including actual risk-sized orders, immutable plan snapshots and full restart.
The original native failure baseline and its zero-order financial evidence remain
unchanged.
