#!/usr/bin/env python3
"""Daily cron job: yield curve ingestion + regime analysis.

Scheduled via Hermes cron: 0 6 * * * (6 AM UTC+10, before market open).
Usage: python run_yield_curve_daily.py
"""
import json
import sys
from pathlib import Path

# Ensure package importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from akme_alpha.scanners.yield_curves import ingest, analyze


def main():
    db_path = Path(__file__).parent / "data" / "akme_alpha.db"
    print(f"[yield-curve] Running daily pipeline, DB: {db_path}")

    # Update DB with FRED key from env
    import os
    if os.environ.get("FRED_API_KEY"):
        print(f"[yield-curve] FRED_API_KEY set, economic indicators enabled")

    # 1. Ingest latest Yahoo Finance yields
    result = ingest(db_path=str(db_path))
    print(f"[yield-curve] Ingested {result['total']} rows across {len(result)-2} maturities")

    # 2. Compute regime for latest date
    regime_result = analyze(db_path=str(db_path))
    if "error" in regime_result:
        print(f"[yield-curve] Regime error: {regime_result['error']}")
    else:
        print(f"[yield-curve] Regime updated: {regime_result['date']} → {regime_result['regime']} ({regime_result['classification']})")

    print(f"[yield-curve] Pipeline complete")


if __name__ == "__main__":
    main()