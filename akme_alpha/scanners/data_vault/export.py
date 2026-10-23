#!/usr/bin/env python
"""Data vault export — generates CSVs for public download.

This cron job exports pre-computed datasets from purrtfolio.db
to the data_vault/ directory for public consumption.

Each CSV ships with a reproducible Python script that can regenerate it,
following the milkman transparency model.

Outputs:
- regime_yield_curve_history.csv — daily regime classifications (367 days)
- short_interest_latest.csv — latest FINRA short interest (19 tickers)
- institutional_flows.csv — 13F consensus positions (tickers with holdings)

Usage: hermes cron run data-vault-export
"""
import csv
import json
import sqlite3
from pathlib import Path

OUTPUT_DIR = Path("/c/Users/cho_i/AppData/Local/hermes/cache/scratch/data_vault")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def export_yield_curve_regime(conn: sqlite3.Connection) -> Path:
    """Export yield curve regime history as CSV."""
    rows = conn.execute("""
        SELECT date, spread_3m10, spread_5y10, spread_3m30, regime, 
               classification, zscore_3m10, y10_level_6m, notes
        FROM yield_curve_regime
        ORDER BY date DESC
    """).fetchall()

    path = OUTPUT_DIR / "regime_yield_curve_history.csv"
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "date", "spread_3m10", "spread_5y10", "spread_3m30",
            "regime", "classification", "zscore_3m10", "y10_level_6m", "notes"
        ])
        for r in rows:
            writer.writerow(r)

    return path


def export_short_interest(conn: sqlite3.Connection) -> Path:
    """Export latest short interest data per ticker."""
    latest_dates = conn.execute("""
        SELECT symbol, settlement_date, issue_name, exchange, current_short,
               previous_short, avg_daily_volume, days_to_cover, change_pct
        FROM short_interest
        WHERE settlement_date = (SELECT MAX(settlement_date) FROM short_interest)
        ORDER BY current_short DESC
    """).fetchall()

    path = OUTPUT_DIR / "short_interest_latest.csv"
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "symbol", "settlement_date", "issue_name", "exchange",
            "current_short", "previous_short", "avg_daily_volume",
            "days_to_cover", "change_pct"
        ])
        for r in latest_dates:
            writer.writerow(r)

    return path


def export_institutional_flows(conn: sqlite3.Connection) -> Path:
    """Export latest 13F institutional flows (aggregated fund positions)."""
    rows = conn.execute("""
        SELECT ticker, report_period, num_funds, total_value_usd,
               net_change_shares, net_change_usd, pct_change
        FROM institutional_flows
        WHERE report_period = (SELECT MAX(report_period) FROM institutional_flows)
        ORDER BY total_value_usd DESC
    """).fetchall()

    path = OUTPUT_DIR / "institutional_flows.csv"
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "ticker", "report_period", "num_funds", "total_value_usd",
            "net_change_shares", "net_change_usd", "pct_change"
        ])
        for r in rows:
            writer.writerow(r)

    return path


def main():
    """Run all exports."""
    with sqlite3.connect("akme_alpha/data/akme_alpha.db") as conn:
        yc_path = export_yield_curve_regime(conn)
        si_path = export_short_interest(conn)
        if_path = export_institutional_flows(conn)

    print("Data vault exports complete:")
    print(f"  regime_yield_curve_history.csv: {yc_path.stat().st_size:,} bytes")
    print(f"  short_interest_latest.csv: {si_path.stat().st_size:,} bytes")
    if if_path.exists():
        print(f"  institutional_flows.csv: {if_path.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()