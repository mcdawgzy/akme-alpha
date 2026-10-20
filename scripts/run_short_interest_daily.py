#!/usr/bin/env python3
"""Daily cron job: FINRA short interest ingestion + signal computation.

Scheduled via Hermes cron: 0 6 * * * (6 AM UTC+10, before market open).
Publication lags settlement by ~7 business days, so daily runs catch new
data as it's published (typically around the 20th/8th of each month).

Usage: python run_short_interest_daily.py
"""
import json
import sys
from pathlib import Path
import datetime as dt

# Platform-agnostic path resolution (works on local and Render)
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent

# Add project to path for imports
sys.path.insert(0, str(PROJECT_ROOT))

# DB path relative to project root (works locally or in /opt/render/project/)
DB_PATH = PROJECT_ROOT / "data" / "akme_alpha.db"

def main():
    print(f"[short-interest] Running daily pipeline, DB: {DB_PATH}")

    from akme_alpha.scanners.finra_short_interest import ingest, analyze

    # 1. Ingest latest available FINRA data (auto-detects settlement date)
    result = ingest.ingest(db_path=str(DB_PATH), settlement_date=None)
    print(f"[short-interest] {result}")

    # 2. Compute signals if we got new data
    if result.get("rows_written", 0) > 0:
        signals = analyze.analyze(db_path=str(DB_PATH))
        if "error" not in signals:
            s = signals["summary"]
            print(f"[short-interest] Signals for {s['latest_settlement']}: "
                  f"{s['tracked_tickers']} tickers, "
                  f"${s['total_short_interest']/1e9:.1f}B total short interest")
            sc = s["signal_counts"]
            print(f"[short-interest] Spikes: {sc['spikes']}, High DTC: {sc['high_dtc']}, "
                  f"Covering: {sc['covering']}")
            if signals.get("spikes"):
                top = signals["spikes"][0]
                print(f"[short-interest] Top spike: {top['symbol']} +{top['change_pct']*100:.0f}% "
                      f"({top['current_short']:,} shorts, DTC={top['days_to_cover']:.1f})")
        else:
            print(f"[short-interest] Analysis: {signals['error']}")

    print(f"[short-interest] Pipeline complete at {dt.datetime.now(tz=dt.timezone.utc).isoformat()}")
    print(f"[short-interest] Status: {result.get('status', 'ok')}")


if __name__ == "__main__":
    main()
