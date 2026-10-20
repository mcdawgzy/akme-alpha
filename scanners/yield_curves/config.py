"""Yield curve scanner configuration.

Maps Yahoo Finance tickers to Treasury maturities. The system is pluggable:
when a FRED API key is provided, the FRED series IDs can be added here
for full curve coverage (DGS3MO, DGS1, DGS2, DGS3, DGS5, DGS7, DGS10, DGS20, DGS30).
"""

# Maturity → (Yahoo Finance ticker, label)
# 3mo (IRX = 13-week T-bill), 5y (FVX), 10y (TNX), 30y (TYX)
# Source: CBOE interest-rate indices, no API key required.
MATURITY_TICKERS = {
    "3m":  "^IRX",
    "5y":  "^FVX",
    "10y": "^TNX",
    "30y": "^TYX",
}

# How many days of history to fetch per ingestion run
LOOKBACK_DAYS = 365

# Yield curve regime thresholds (basis points; spread = long − short)
# Convention: 3m10s = 10y − 3m. Negative = inverted, positive = normally sloped.
REGIME_THRESHOLDS = {
    "inverted":            0,     # 3m10s ≤ 0 bps  → INVERTED (recession warning)
    "flat":               25,    # |3m10s| < 25 bps → FLAT
    "steep":              150,   # 3m10s > 150 bps AND z > 1 → STEEP (bull steepening)
    "normal_risk_on":      50,    # 3m10s > 50 bps → normally sloped, risk-on
}

# Z-score lookback window (days) for normalising the 3m10s spread
ZSCORE_LOOKBACK = 504  # ~2 years trading days
