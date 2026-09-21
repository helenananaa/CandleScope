"""Deterministic relevance without changing instrument or series identity."""
from functools import lru_cache
import re
import unicodedata

# Search aliases only: these never rewrite the selected symbol's identity.
ALIASES = {
    "btc": ("bitcoin", "比特币"), "eth": ("ethereum", "以太坊", "以太币"),
    "sol": ("solana", "索拉纳"), "doge": ("dogecoin", "狗狗币"),
    "aapl": ("apple", "苹果"), "msft": ("microsoft", "微软"),
    "nvda": ("nvidia", "英伟达", "英伟达公司"), "tsla": ("tesla", "特斯拉"),
    "xau": ("gold", "黄金"), "xag": ("silver", "白银"),
    "gbp": ("pound", "英镑"), "eur": ("euro", "欧元"), "jpy": ("yen", "日元"),
}


def compact(value: str) -> str:
    return re.sub(r"[\s/_-]+", "", unicodedata.normalize("NFKC", value)).casefold()


def one_edit(left: str, right: str) -> bool:
    if min(len(left), len(right)) < 4 or abs(len(left) - len(right)) > 1:
        return False
    if len(left) == len(right):
        differences = [i for i, (a, b) in enumerate(zip(left, right)) if a != b]
        return len(differences) == 1 or (len(differences) == 2
            and differences[1] == differences[0] + 1
            and left[differences[0]] == right[differences[1]]
            and left[differences[1]] == right[differences[0]])
    short, long = sorted((left, right), key=len)
    index = next((i for i, (a, b) in enumerate(zip(short, long)) if a != b), len(short))
    return short[index:] == long[index + 1:]


@lru_cache(maxsize=100_000)
def prepared(symbol: str, base: str, quote: str, name: str, venue: str, mic: str) -> tuple:
    codes = tuple(compact(value) for value in (symbol, base, base + quote) if value)
    aliases = ALIASES.get(compact(base), ())
    names = tuple(compact(value) for value in (name, *aliases, *(alias + quote for alias in aliases)) if value)
    fields = (*codes, *names, compact(quote), compact(venue), compact(mic))
    words = tuple(set(re.findall(r"\w+", name.casefold()) + list(names) + [compact(base)]))
    return codes, names, fields, words


def relevance(row: dict, search: str) -> int | None:
    if not search.strip():
        return 0
    # A colon prefix is a source qualifier only when it names this source.
    prefix = str(row.get("exchange", "")) + ":"
    if search.casefold().startswith(prefix.casefold()):
        search = search[len(prefix):]
    needle = compact(search)
    codes, names, fields, words = prepared(*(str(row.get(key) or "") for key in
        ("symbol", "baseAsset", "quoteAsset", "displayName", "venue", "venueMic")))
    if needle in codes:
        return 0
    if needle in names:
        return 1
    if any(value.startswith(needle) for value in (*codes, *names)):
        return 2
    tokens = [compact(value) for value in search.split()]
    if all(any(token in value for value in fields) for token in tokens):
        return 3
    if 4 <= len(needle) <= 24 and any(one_edit(needle, word) for word in words):
        return 4
    return None


def contract_rank(row: dict) -> int:
    market = str(row.get("marketType", "")).lower()
    if row.get("optionRight") or "option" in market:
        return 3
    if row.get("expiryAtMs") or row.get("contractType") in {"delivery", "dated"}:
        return 2
    return 0 if market in {"spot", "stock", "etf", "forex", "index", "commodity"} else 1


def provider_search_text(search: str) -> str:
    needle = compact(search)
    return next((code.upper() for code, aliases in ALIASES.items() if needle in aliases), search.strip())
