#!/usr/bin/env python3
"""Quarterly cron job: full 13F backfill + QoQ comparison.

Scheduled via Hermes cron: 0 6 15 2,5,8,11 * (6 AM UTC+10 on the 15th of
Feb/May/Aug/Nov — SEC 45-day deadline + 1 day buffer).

Runs the daily ingest (60-day window to catch late filings), then forces
a full re-computation of institutional_flows across all quarters.
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
DB_PATH = PROJECT_ROOT / "akme_alpha" / "data" / "akme_alpha.db"

def main():
    print(f"[13f-quarterly] Running quarterly backfill + QoQ analysis, DB: {DB_PATH}")

    # 1. Run daily ingest (wider window for quarterly catch-up)
    from akme_alpha.scanners.sec_filings import ingest
    result = ingest.ingest(db_path=str(DB_PATH), days=60)
    print(f"[13f-quarterly] Ingest: {result['filings_found']} found, "
          f"{result['filings_processed']} processed, {result['holdings_written']} holdings")

    # 2. Compute flows for ALL quarters (full backfill)
    from akme_alpha.scanners.sec_filings import analyze
    flow_result = analyze.analyze(db_path=str(DB_PATH))
    if "error" in flow_result:
        print(f"[13f-quarterly] Error: {flow_result['error']}")
        return

    print(f"[13f-quarterly] Flows computed for {flow_result['latest_quarter']}")
    print(f"[13f-quarterly] Total tickers: {flow_result['summary']['total_tickers']}")
    print(f"[13f-quarterly] Total value: ${flow_result['summary']['total_value_usd']/1e9:.1f}B")

    print(f"\n[13f-quarterly] Pipeline complete at {dt.datetime.now(tz=dt.timezone.utc).isoformat()}")


if __name__ == "__main__":
    main()
