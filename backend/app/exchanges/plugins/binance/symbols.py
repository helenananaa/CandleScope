from app.exchanges.plugin import DefaultSymbolNormalizer


class BinanceSymbolNormalizer(DefaultSymbolNormalizer):
    """Binance accepts compact symbols; also tolerate dashed variants from old state."""

    _PERP_SUFFIXES = {"SWAP", "PERP", "PERPETUAL"}

    def normalize(self, symbol: str, market_type: str = "spot") -> str:
        normalized = super().normalize(symbol, market_type)
        if "-" not in normalized:
            return normalized

        parts = [part for part in normalized.split("-") if part]
        if not parts:
            return normalized
        if str(market_type or "spot").strip().lower() == "futures" and parts[-1] in self._PERP_SUFFIXES:
            parts = parts[:-1]
        return "".join(parts)

    # Pine names Binance perpetuals ``BTCUSDT.P``; Pine contexts may call the
    # market usdm or swap.
    _PINE_PERPETUAL_MARKETS = {"futures", "usdm", "swap"}

    def pine_ticker(self, symbol: str, market_type: str = "spot") -> str:
        if str(market_type or "").lower() in self._PINE_PERPETUAL_MARKETS and not symbol.endswith(".P"):
            return symbol + ".P"
        return symbol

    def storage_symbol_from_pine(self, ticker: str, market_type: str = "spot") -> str:
        if str(market_type or "").lower() in self._PINE_PERPETUAL_MARKETS:
            return ticker.removesuffix(".P")
        return ticker
