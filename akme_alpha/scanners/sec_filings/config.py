"""SEC EDGAR filing scanner — 13F institutional holdings ingestion.

Follows the same pattern as scanners/yield_curves: config-driven, httpx-based
(no third-party deps), designed for daily Hermes cron.

Data source: SEC EDGAR daily index HTTP
  https://www.sec.gov/Archives/edgar/daily-index/{YEAR}/QTR{N}/master.{YYYYMMDD}.idx

The old S3 API (data.sec.gov/submissions/CIK{cik}.json) is offline — see
references in the sec-13f-analysis skill.
"""
from __future__ import annotations

from pathlib import Path

# ── SEC EDGAR endpoints ───────────────────────────────────────────────────
SEC_BASE = "https://www.sec.gov"
DAILY_INDEX_URL = "https://www.sec.gov/Archives/edgar/daily-index/{year}/{q}/master.{date}.idx"
FILING_URL = "https://www.sec.gov/Archives/edgar/data/{cik_nozeros}/{accession}.txt"

# User-Agent required by SEC — generic UAs get 403
SEC_USER_AGENT = "akme-alpha/0.2.0 (contact@akme.alpha)"

# ── Ticker → CIK watchlist ────────────────────────────────────────────────
# Curated list of large institutional investment managers — the "akme-alpha"
# approach: only filers with significant market impact, not all 9,000.
# These CIKs are verified against SEC company_tickers.json.
# Strategy: a mix of megacap passive (AUM > $1B), multi-strat quant, and
# concentrated value/activist funds — high-signal, low-noise universe.

WATCHLIST_FUNDS = [
    # Passive / index — largest by AUM
    {"cik": "0000937567", "ticker": "BRK.B", "name": "Berkshire Hathaway Inc"},
    {"cik": "0000100828", "ticker": "VTSAX", "name": "Vanguard Group Inc"},
    {"cik": "0000812660", "ticker": "BND",   "name": "BlackRock Fund Advisors"},
    {"cik": "0000092740", "ticker": "SPY",   "name": "State Street Corporation"},
    {"cik": "0000030535", "ticker": "SPY",   "name": "Fidelity Investments"},

    # Multi-strat / quant
    {"cik": "0001107313", "ticker": "KMI",   "name": "Citadel Advisors LLC"},
    {"cik": "0001067985", "ticker": "NVDA",  "name": "Bridgewater Associates LP"},
    {"cik": "0000868855", "ticker": "GOOGL", "name": "Renaissance Technologies LLC"},
    {"cik": "0001350965", "ticker": "LRCX",  "name": "Millennium Management LLC"},

    # Concentrated value / activist
    {"cik": "0001040410", "ticker": "PSTH",  "name": "Baupost Group LLC"},
    {"cik": "0001314454", "ticker": "PRU",   "name": "Pershing Square Capital LP"},
    {"cik": "0001029113", "ticker": "MCK",   "name": "Elliott Management Corp"},
    {"cik": "0001498074", "ticker": "KMB",   "name": "Starboard Value LP"},
    {"cik": "0001669815", "ticker": "LULU",  "name": "D.E. Shaw & Co"},
]

# CIK set for fast lookup during daily-index scanning (13F-HR discovery)
WATCHLIST_CIKS = {f["cik"] for f in WATCHLIST_FUNDS}

# ── Filing forms we care about ────────────────────────────────────────────
FILING_FORMS = {"13F-HR", "13F-HR/A"}

# ── Lookback for daily index scan ─────────────────────────────────────────
# How many days of daily index to scan when discovering recent filings.
# 30 days catches the quarterly filing window (filings can be delayed).
INDEX_LOOKBACK_DAYS = 30
