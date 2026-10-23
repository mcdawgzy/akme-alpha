#!/usr/bin/env python3
"""Populate regime_daily table with historical regime analysis.

Runs the regime analyzer for each date available in regime_factors table
to build historical regime verdicts.
"""
import json
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path("C:/Users/cho_i/akme_alpha")
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from akme_alpha.scanners.regime import analyze

DB_PATH = PROJECT_ROOT / "akme_alpha" / "data" / "akme_alpha.db"


def backfill_regime_history():
    """Run regime analysis for all available dates."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Get all dates with factor data
    cursor.execute("""
        SELECT DISTINCT date FROM regime_factors 
        WHERE date NOT IN (SELECT date FROM regime_daily)
        ORDER BY date
    """)
    dates = [r[0] for r in cursor.fetchall()]
    conn.close()

    if not dates:
        print("[backfill] No new dates to process")
        return

    print(f"[backfill] Processing {len(dates)} historical dates...")

    # Import analyze module to reuse logic
    from importlib import reload
    import akme_alpha.scanners.regime.analyze as analyze_mod
    reload(analyze_mod)

    count = 0
    for date in dates:
        result = analyze_mod.analyze(db_path=str(DB_PATH), target_date=date)
        if "error" not in result:
            count += 1
            print(f"[backfill] {date}: {result['verdict']} ({result['composite_score']:+.3f})")

    print(f"[backfill] Processed {count} regime records")


if __name__ == "__main__":
    backfill_regime_history()