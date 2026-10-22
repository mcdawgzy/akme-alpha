"""Market Snapshot scanner configuration.

31 tickers across 7 sections — large/liquid names only, no full-universe
scraping. All data sourced from Yahoo Finance (no API key required).
"""
from __future__ import annotations

# ── 31-ticker universe across 7 sections ─────────────────────────────────
SECTIONS: dict[str, list[str]] = {
    "US Equities": [
        "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN",
        "META", "TSLA", "BRK-B", "JPM", "V",
        "XOM", "JNJ",
    ],                                               # 12 → 12
    "Global Equities": [
        "SPY", "QQQ", "EEM", "EFA",
    ],                                               # 4  → 16
    "US Rates": [
        "^IRX",  # 3-month (displayed as 2Y proxy; see YIELD_LABELS)
        "^FVX",  # 5-year
        "^TNX",  # 10-year
        "^TYX",  # 30-year
    ],                                               # 4  → 20
    "FX": [
        "UUP", "FXE", "FXF", "FXY",
    ],                                               # 4  → 24
    "Commodities": [
        "CL=F", "NG=F", "GC=F", "HG=F",
    ],                                               # 4  → 28
    "Market Internals": [
        "^VIX",
    ],                                               # 1  → 29
    "Crypto": [
        "BTC-USD", "ETH-USD",
    ],                                               # 2  → 31
}

# Yield tickers are displayed as treasury maturities (Level = yield %, Move = bps)
YIELD_TICKERS = {"^IRX", "^FVX", "^TNX", "^TYX"}

# Yahoo ticker → display label
YIELD_LABELS = {
    "^IRX": "2Y*",  # 3-month T-bill (closest free proxy for 2Y on Yahoo)
    "^FVX": "5Y",
    "^TNX": "10Y",
    "^TYX": "30Y",
}

# Friendly names for non-yield tickers (for display)
TICKER_NAMES = {
    "AAPL": "Apple", "MSFT": "Microsoft", "NVDA": "Nvidia",
    "GOOGL": "Google", "AMZN": "Amazon", "META": "Meta",
    "TSLA": "Tesla", "BRK-B": "Berkshire", "JPM": "JPMorgan",
    "V": "Visa", "XOM": "Exxon", "JNJ": "Johnson&Johnson",
    "SPY": "S&P 500", "QQQ": "Nasdaq 100", "EEM": "Emerging Mkts",
    "EFA": "EAFE", "UUP": "Dollar Index", "FXE": "Euro",
    "FXF": "CHF", "CL=F": "Crude Oil", "NG=F": "Nat Gas",
    "GC=F": "Gold", "HG=F": "Copper", "^VIX": "VIX",
    "BTC-USD": "Bitcoin", "ETH-USD": "Ethereum",
    "FXY": "Yen ETF",
}

# ── Yahoo Finance ─────────────────────────────────────────────────────────
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
YAHOO_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
# Fetch 10 trading days to compute 1d and 5d changes
FETCH_RANGE_DAYS = 10
HTTP_TIMEOUT = 30

# ── Design constants (ultra-minimal) ─────────────────────────────────────
WIDTH = 1280
HEIGHT = 720
MARGIN = 48
BG = "#0A0A0C"
TEXT = "#E8E8EC"
GRAY = "#6B7280"
GRAY_LT = "#37383A"
GREEN = "#22C57E"
RED = "#EF4444"
BRASS = "#C9A24E"

# Number of top-movers that get 2-3 sentence narratives (tiered depth)
TOP_N_NARRATIVE = 5
