"""Regime indicator factor configuration.

All data sourced from free providers — no redistribution constraints.
Factor weights sum to ~1.0; missing factors (FCF, revenue growth, stability)
contribute 0 in Phase 1 and will be re-weighted in Phase 1b.
"""

# ── Factor definitions ─────────────────────────────────────────────────
# weight: 0-1 contribution to composite score
# direction: 'positive' = higher value → risk-on (Exp/Rec)
#            'negative' = higher value → risk-off (Slow/Rec)

FACTORS = {
    "valuation_cape": {
        "weight": 0.20,
        "direction": "positive",
        "description": "SPY 200-day price deviation z-score (valuation proxy)",
        "tickers": ["SPY"],
        "source": "yahoo_finance",
    },
    "growth_value": {
        "weight": 0.15,
        "direction": "positive",
        "description": "Growth/Value ETF ratio z-score (IWF/IWD)",
        "tickers": ["IWF", "IWD"],
        "source": "yahoo_finance",
    },
    "momentum": {
        "weight": 0.15,
        "direction": "positive",
        "description": "Broad market 12-month momentum z-score (SPY)",
        "tickers": ["SPY"],
        "momentum_days": 252,
        "source": "yahoo_finance",
    },
    "yield_curve": {
        "weight": 0.15,
        "direction": "positive",
        "description": "3-month / 10-year spread z-score (from DB)",
        "source": "db",
    },
    "credit_spreads": {
        "weight": 0.10,
        "direction": "positive",
        "description": "Credit spread proxy z-score (HYG/LQD — higher=risk-on)",
        "tickers": ["HYG", "LQD"],
        "source": "yahoo_finance",
    },
    "fcf_yield": {
        "weight": 0.00,  # Phase 1b: enable with weight 0.10
        "direction": "positive",
        "description": "S&P 500 FCF yield z-score (Yardeni/multpl)",
        "source": "yardeni",
    },
    "commodities": {
        "weight": 0.10,
        "direction": "positive",
        "description": "Commodity index momentum z-score (from DB)",
        "source": "db",
    },
    "asset_growth": {
        "weight": 0.00,  # Phase 1b: enable with weight 0.05
        "direction": "positive",
        "description": "Revenue growth trend z-score",
        "source": "yahoo_finance",
    },
    "stability": {
        "weight": 0.00,  # Phase 1b: enable with weight 0.05
        "direction": "positive",
        "description": "Earnings surprise volatility proxy",
        "source": "yahoo_finance",
    },
    "fx_strength": {
        "weight": 0.03,
        "direction": "negative",
        "description": "DXY strength proxy z-score (UUP)",
        "tickers": ["UUP"],
        "source": "yahoo_finance",
    },
}

# ── Regime verdict thresholds (composite z-score bands) ─────────────────
# Expansion: > +0.5  (risk-on, growth above trend)
# Recovery:  0 to +0.5  (risk-on, emerging from trough)
# Slowdown:  -0.5 to 0  (risk-off, growth decelerating)
# Recession: < -0.5  (severe stress, contraction)
REGIME_UPPER = 0.5
REGIME_LOWER = -0.5

REGIME_COLORS = {
    "Expansion": "#22C57E",   # green
    "Recovery": "#4ADE80",    # light green
    "Slowdown": "#F87171",    # light red
    "Recession": "#EF4444",   # red
}

# ── Z-score settings ────────────────────────────────────────────────────
ZSCORE_LOOKBACK = 504  # ~2 years trading days

# ── Yahoo Finance ───────────────────────────────────────────────────────
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
YAHOO_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# ── Shiller CAPE data ───────────────────────────────────────────────────
# Monthly data going back to 1871. Try multiple mirrors for resilience.
SHILLER_URLS = [
    "http://www.econ.yale.edu/~shiller/data/ie_data.csv",
    "https://raw.githubusercontent.com/datasets/cape/master/data/cape.csv",
    "https://www.spaghetti-monitor.com/cape.csv",  # fallback mirror
]

# ── HTTP ────────────────────────────────────────────────────────────────
HTTP_TIMEOUT = 30
