"""Ingest daily Treasury yield curve data from Yahoo Finance (no API key).

Usage:
    python -m scanners.yield_curves.ingest --db C:/Users/cho_i/purrtfolio.db

Fetches 3m/5y/10y/30y yields for the last LOOKBACK_DAYS and upserts into
the yield_curves table. Designed to run daily via Hermes cron.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import urllib.request

import httpx

from .config import LOOKBACK_DAYS, MATURITY_TICKERS


YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"


def _fetch_yahoo(ticker: str, range_days: int = LOOKBACK_DAYS) -> list[dict]:
    """Return [{date, yield_pct}, ...] for a single Yahoo ticker.

    Uses httpx with a browser UA. Yahoo returns timestamps + close prices;
    close == the yield for these CBOE indices.
    """
    url = YAHOO_CHART_URL.format(ticker=ticker)
    params = {
        "range": f"{range_days}d",
        "interval": "1d",
    }
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
        )
    }
    resp = httpx.get(url, params=params, headers=headers, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    result = data["chart"]["result"][0]
    timestamps = result["timestamp"]
    closes = result["indicators"]["quote"][0]["close"]

    rows = []
    for ts, val in zip(timestamps, closes):
        if val is None:
            continue
        date = dt.datetime.fromtimestamp(ts, dt.timezone.utc).date().isoformat()
        rows.append({"date": date, "yield_pct": round(val, 6)})
    return rows


def ingest(db_path: str | None = None, dry_run: bool = False) -> dict:
    """Fetch latest yields for all maturities and upsert into the DB.

    Returns a summary dict: {maturity: rows_written, ...} + total.
    """
    from ... import db as dbmod

    db = dbmod.init_db(db_path)
    summary = {}

    for maturity, ticker in MATURITY_TICKERS.items():
        rows = _fetch_yahoo(ticker)
        summary[maturity] = len(rows)
        if dry_run or not rows:
            continue
        with dbmod.get_connection(db) as conn:
            for row in rows:
                conn.execute(
                    """INSERT INTO yield_curves (date, maturity, yield_pct, source)
                       VALUES (?, ?, ?, 'yahoo_finance')
                       ON CONFLICT(date, maturity) DO UPDATE SET
                         yield_pct = excluded.yield_pct,
                         source      = excluded.source,
                         ingested_at = CURRENT_TIMESTAMP""",
                    (row["date"], maturity, row["yield_pct"]),
                )
            conn.commit()

    summary["total"] = sum(v for k, v in summary.items() if isinstance(v, int))
    summary["db_path"] = str(db)
    return summary


def main():
    ap = argparse.ArgumentParser(description="Ingest Treasury yield curve data")
    # --db must come before subcommand (matches project convention)
    ap.add_argument("--db", default=None, help="DB path (default: from config)")
    ap.add_argument("--dry-run", action="store_true", help="Fetch but don't write")
    args = ap.parse_args()
    result = ingest(db_path=args.db, dry_run=args.dry_run)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
