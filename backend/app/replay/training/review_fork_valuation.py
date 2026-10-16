"""Compare the selected frozen wallet with a recovered HEDGE child."""

from decimal import Decimal
from collections.abc import Mapping

from .errors import TrainingRunError

_FIELDS = ("equity", "available_equity", "unrealized_pnl", "margin_used", "reserved_margin")


def assert_selected_valuation(projection, portfolio):
    selected = projection["domain"].get("portfolio")
    if selected is None:
        from .review_account import legacy_account

        selected = legacy_account(projection)
    if isinstance(selected, Mapping) and selected.get("status") == "LEGACY_FLAT":
        # A flat, order-free legacy wallet has no position/order margin. Its
        # saved equity and isolated cash allocation remain independently known.
        selected = {"margin_used": "0", "reserved_margin": "0", **selected}
    if not isinstance(selected, Mapping) or any(selected.get(key) is None for key in _FIELDS):
        raise TrainingRunError(
            "REVIEW_FORK_VALUATION_UNAVAILABLE",
            "This historical event has no complete frozen account valuation. Choose another event to continue training.",
            details={"fallback_applied": False},
        )
    differences = [key for key in _FIELDS if Decimal(str(selected[key])) != Decimal(str(portfolio[key]))]
    if differences:
        raise TrainingRunError(
            "REVIEW_FORK_VALUATION_MISMATCH",
            "This historical event uses a different account valuation. The child was removed; choose another event to continue training.",
            details={"fallback_applied": False, "differences": differences,
                     "selected": {key: selected[key] for key in differences},
                     "recovered": {key: portfolio[key] for key in differences}},
        )
