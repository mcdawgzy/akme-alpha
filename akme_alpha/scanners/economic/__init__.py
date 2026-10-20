"""Economic and commodity data scanners — feed the market regime classifier.

Core schedule: Daily cron at 6 AM UTC+10 (before market open).

Sources by priority:
1. FRED API (requires key) — CPI, PPI, Fed funds, Treasury yields
2. Yahoo Finance (no key) — Crude, Gas, Gold, Silver, Treasury yields
3. SEC EDGAR (no key) — CPI via BLS feed (rarely used)

The system is source-pluggable: add FRED/BLS API keys to .env and the
ingestion modules will automatically use keyed sources when available,
fall back to no-key alternatives when not.
"""