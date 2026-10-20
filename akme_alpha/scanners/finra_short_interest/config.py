"""FINRA Short Interest scanner configuration.

Data source: FINRA CDN (pipe-delimited CSV, no auth required)
  https://cdn.finra.org/equity/otcmarket/biweekly/shrt{YYYYMMDD}.csv

Key fact: FINRA short interest is AGGREGATE per ticker — total short shares
across ALL market participants. There is no public per-fund short interest.

Publication calendar:
  - Settlement dates: 15th of month + last business day of month
  - Publication: ~7 business days after settlement date
  - Data covers NYSE, NASDAQ, ARCA, BZX, OTC
"""
from __future__ import annotations

# ── FINRA CDN endpoints ─────────────────────────────────────────────────
FINRA_CSV_URL = "https://cdn.finra.org/equity/otcmarket/biweekly/shrt{date}.csv"

# ── User-Agent (SEC/FINRA blocks generic UAs) ───────────────────────────
FINRA_USER_AGENT = "akme-alpha/0.2.0 (contact@akme.alpha)"

# ── Signal thresholds ───────────────────────────────────────────────────
THRESHOLDS = {
    "spike_pct": 0.5,            # >50% WoW increase in shorts
    "spike_min_short": 1_000_000,  # min absolute short for spike
    "high_dtc": 10,              # days to cover > 10
    "high_dtc_min_short": 1_000_000,
    "covering_pct": -0.3,        # >30% decrease in shorts (covering)
    "covering_min_short": 1_000_000,
    "consensus_min_avg_short": 5_000_000,  # avg 5M+ across 3+ periods
    "consensus_min_periods": 3,
}

# ── Curated watchlist: large, liquid tickers with meaningful short interest
# These mirror akme_alpha's 31-ticker market snapshot universe
WATCHLIST = [
    # US Equities (large cap)
    "AAPL", "MSFT", "NVDA", "GOOGL", "AMZN", "META", "TSLA", "BRK.B",
    "AVGO", "LLY", "JPM", "V", "XOM", "UNH", "JNJ",
    # Global Equities (ETFs)
    "SPY", "QQQ", "EEM", "EFA", "EWJ",
    # Crypto
    "BTC-USD", "ETH-USD",
]
