#!/usr/bin/env python3
"""Daily cron job: 13F filing ingestion + consensus flow computation.

Scheduled via Hermes cron: 0 6 * * * (6 AM UTC+10, before market open).
Usage: python scripts/run_13f_daily.py [--days N]

Pipeline:
1. Scan SEC daily index for recent 13F-HR filings matching watchlist CIKs
2. Download + parse infoTable XML for each filing
3. Upsert filings_13f + holdings_13f
4. Compute institutional_flows consensus (net changes vs prior quarter)
"""
import json
import sys
from pathlib import Path

# Ensure package importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from akme_alpha.scanners.sec_filings import ingest, analyze


def main():
    db_path = Path(__file__).parent.parent / "akme_alpha" / "data" / "akme_alpha.db"
    print(f"[13f] Running daily pipeline, DB: {db_path}")

    # 1. Ingest recent 13F-HR filings
    result = ingest.ingest(db_path=str(db_path), days=30)
    print(f"[13f] Found {result['filings_found']} filings, "
          f"processed {result['filings_processed']}, "
          f"wrote {result['holdings_written']} holdings")
    if result.get("errors"):
        print(f"[13f] {len(result['errors'])} errors during ingest")

    # 2. Compute consensus institutional flows
    if result["filings_processed"] > 0 and result["holdings_written"] > 0:
        flow_result = analyze.analyze(db_path=str(db_path))
        if "error" not in flow_result:
            top_buy = flow_result["top_buys"][0] if flow_result["top_buys"] else None
            top_sell = flow_result["top_sells"][0] if flow_result["top_sells"] else None
            print(f"[13f] Flows computed for {flow_result['latest_quarter']}: "
                  f"{flow_result['summary']['total_tickers']} tickers, "
                  f"${flow_result['summary']['total_value_usd'] / 1e9:.1f}B total")
            if top_buy:
                print(f"[13f] Top buy: {top_buy['ticker']} +${top_buy['net_change_usd'] / 1e6:.1f}M")
            if top_sell:
                print(f"[13f] Top sell: {top_sell['ticker']} ${top_sell['net_change_usd'] / 1e6:.1f}M")
        else:
            print(f"[13f] Flow analysis: {flow_result['error']}")

    print(f"[13f] Pipeline complete (status: {result.get('status', 'ok')})")


if __name__ == "__main__":
    main()
